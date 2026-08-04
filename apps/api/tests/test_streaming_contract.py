import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from ai.errors import ProviderRuntimeError, ProviderTimeoutError
from ai.specs import Message
from core.db.sqlite import connect as _sqlite_connect, init_db
from domain.prompts.system.reader import BuiltPrompt
from domain.specs import GenerationParams
from domain.turns import streaming
from domain.turns.specs import ActionType, PreparedGeneration


def _seed_conversation(conn) -> None:
    conn.execute(
        "INSERT INTO plots (id, title, plot_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("plot-1", "plot", "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO characters (id, name, plot_id, sort_order, profile_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("char-1", "char", "plot-1", 0, "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO user_profiles (id, name, profile_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("user-1", "user", "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO conversations (id, plot_id, user_profile_id, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("conv-1", "plot-1", "user-1", "t", "t"),
    )
    conn.commit()


def _prepared() -> PreparedGeneration:
    built = BuiltPrompt(system="system", messages=[Message(role="user", content="hi")], warnings=[], plot={"id": "plot-1"}, char={"id": "char-1"}, user={"id": "user-1"})
    return PreparedGeneration(
        conversation_id="conv-1",
        turn_id="turn-1",
        user_message="hi",
        built=built,
        action_type=ActionType.GENERATION_SHOWN,
        message_id="msg-1",
        created_at="t",
    )


async def _tokens(*chunks):
    for chunk in chunks:
        yield chunk


async def _tokens_then_raise(chunks, error):
    for chunk in chunks:
        yield chunk
    raise error


class StreamingContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmpdir.name, "test.sqlite")

        def _connect():
            conn = _sqlite_connect(self._db_path)
            init_db(conn)
            return conn

        self._connect = _connect
        with self._connect() as conn:
            _seed_conversation(conn)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _generation_rows(self):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM generations").fetchall()

    async def test_success_emits_start_tokens_done_exactly_once_and_persists(self):
        params = GenerationParams(model="local-stub")
        with (
            patch.object(streaming, "connect", self._connect),
            patch.object(streaming, "stream_text", lambda req, provider_name: _tokens("Hello", " world")),
        ):
            events = [chunk async for chunk in streaming.stream_response(_prepared(), params)]

        starts = [e for e in events if e.startswith("event: start")]
        tokens = [e for e in events if e.startswith("event: token")]
        dones = [e for e in events if e.startswith("event: done")]
        errors = [e for e in events if e.startswith("event: error")]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(tokens), 2)
        self.assertEqual(len(dones), 1)
        self.assertEqual(len(errors), 0)

        rows = self._generation_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["output_text"], "Hello world")

    async def test_mid_stream_failure_emits_error_once_no_done_and_persists_nothing(self):
        params = GenerationParams(model="local-stub")
        error = ProviderTimeoutError("codex event queue was blocked", provider="openai-codex", phase="idle")
        with (
            patch.object(streaming, "connect", self._connect),
            patch.object(streaming, "stream_text", lambda req, provider_name: _tokens_then_raise(["Hello"], error)),
        ):
            events = [chunk async for chunk in streaming.stream_response(_prepared(), params)]

        starts = [e for e in events if e.startswith("event: start")]
        tokens = [e for e in events if e.startswith("event: token")]
        dones = [e for e in events if e.startswith("event: done")]
        errors = [e for e in events if e.startswith("event: error")]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(len(dones), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('"code": "provider_timeout"', errors[0])
        self.assertIn('"phase": "idle"', errors[0])

        self.assertEqual(len(self._generation_rows()), 0)

    async def test_generic_provider_runtime_error_emits_error_once_no_done(self):
        params = GenerationParams(model="local-stub")
        error = ProviderRuntimeError(code="provider_runtime_crashed", message="codex crashed", provider="openai-codex", retryable=False, phase="idle")
        with (
            patch.object(streaming, "connect", self._connect),
            patch.object(streaming, "stream_text", lambda req, provider_name: _tokens_then_raise([], error)),
        ):
            events = [chunk async for chunk in streaming.stream_response(_prepared(), params)]

        dones = [e for e in events if e.startswith("event: done")]
        errors = [e for e in events if e.startswith("event: error")]
        self.assertEqual(len(dones), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('"code": "provider_runtime_crashed"', errors[0])
        self.assertEqual(len(self._generation_rows()), 0)

    async def test_disconnect_sends_no_done_or_error(self):
        params = GenerationParams(model="local-stub")
        release = asyncio.Event()

        async def _blocked_tokens(req, provider_name):
            yield "Hello"
            await release.wait()
            yield "unreachable"

        with (
            patch.object(streaming, "connect", self._connect),
            patch.object(streaming, "stream_text", _blocked_tokens),
        ):
            gen = streaming.stream_response(_prepared(), params)
            events = []
            events.append(await anext(gen))  # start
            events.append(await anext(gen))  # token "Hello"
            await gen.aclose()

        self.assertFalse(any(e.startswith("event: done") for e in events))
        self.assertFalse(any(e.startswith("event: error") for e in events))
        self.assertEqual(len(self._generation_rows()), 0)
        release.set()

    async def test_heartbeat_ping_emitted_while_waiting_for_first_token(self):
        params = GenerationParams(model="local-stub")

        async def _slow_tokens(req, provider_name):
            await asyncio.sleep(0.05)
            yield "Hello"

        with (
            patch.object(streaming, "connect", self._connect),
            patch.object(streaming, "stream_text", _slow_tokens),
            patch.object(streaming, "SSE_HEARTBEAT_SECONDS", 0.01),
        ):
            events = [chunk async for chunk in streaming.stream_response(_prepared(), params)]

        self.assertTrue(any(e == ": ping\n\n" for e in events))
        self.assertEqual(len([e for e in events if e.startswith("event: done")]), 1)


if __name__ == "__main__":
    unittest.main()
