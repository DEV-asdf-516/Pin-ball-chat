import os
import tempfile
import unittest
from unittest.mock import patch

from ai.errors import ProviderErrorCode, ProviderRuntimeError
from ai.specs import ProviderName
from core.db import new_id
from core.db.sqlite import connect as _sqlite_connect, init_db
from domain.prompts.summary.chunks import (
    DEFAULT_SUMMARY_CHUNK_CHAR_LIMIT,
    OLLAMA_SUMMARY_CHUNK_CHAR_LIMIT,
    render_summary_dialogue,
    smaller_summary_chunk_char_limit,
    summary_chunk_char_limit,
    take_summary_chunk,
)
from domain.prompts.summary import writer


async def _tokens(*chunks):
    for chunk in chunks:
        yield chunk


async def _failure(error):
    raise error
    yield ""


class SummaryChunkTests(unittest.TestCase):
    def test_chunk_preserves_message_boundaries_and_order(self):
        messages = [
            {"rowid": 1, "role": "user", "content": "1234"},
            {"rowid": 2, "role": "assistant", "content": "5678"},
            {"rowid": 3, "role": "assistant", "content": "90"},
        ]

        chunk = take_summary_chunk(messages, "사용자", 12)

        self.assertEqual([message["rowid"] for message in chunk], [1])
        self.assertEqual(render_summary_dialogue(chunk, "사용자"), "사용자: 1234")

    def test_oversized_single_message_still_makes_progress(self):
        messages = [{"rowid": 1, "role": "assistant", "content": "x" * 100}]

        self.assertEqual(take_summary_chunk(messages, "사용자", 10), messages)

    def test_ollama_uses_smaller_application_chunk_limit(self):
        self.assertEqual(summary_chunk_char_limit(ProviderName.OLLAMA), OLLAMA_SUMMARY_CHUNK_CHAR_LIMIT)
        self.assertEqual(summary_chunk_char_limit(ProviderName.CLAUDE_CLI), DEFAULT_SUMMARY_CHUNK_CHAR_LIMIT)
        self.assertEqual(summary_chunk_char_limit(ProviderName.OPENAI_CODEX), DEFAULT_SUMMARY_CHUNK_CHAR_LIMIT)

    def test_failed_chunk_limit_reduces_but_stays_positive(self):
        self.assertEqual(smaller_summary_chunk_char_limit(70_000, 60_000), 30_000)
        self.assertEqual(smaller_summary_chunk_char_limit(2_000, 2_000), 2_000)


class SummaryWriterTests(unittest.IsolatedAsyncioTestCase):
    # RECENT_WINDOW=1로 두면 "가장 최근 메시지 1개"만 pending에서 빠지므로, 나머지 메시지 수를
    # SUMMARY_TRIGGER로 그대로 맞춰 pending 목록을 원하는 크기로 통제할 수 있다.
    _RECENT_WINDOW = 1

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmpdir.name, "test.sqlite")
        writer._summary_locks.clear()

        def _connect():
            conn = _sqlite_connect(self._db_path)
            init_db(conn)
            return conn

        self._connect = _connect
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plots (id, title, plot_json, created_at, updated_at) VALUES (?,?,?,?,?)",
                ("plot-1", "plot", '{"id":"plot-1","type":"plot","sourceText":"","title":"플롯"}', "t", "t"),
            )
            conn.execute(
                "INSERT INTO characters (id, name, plot_id, sort_order, profile_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                ("char-1", "char", "plot-1", 0, '{"id":"char-1","type":"character","sourceText":"","name":"캐릭"}', "t", "t"),
            )
            conn.execute(
                "INSERT INTO user_profiles (id, name, profile_json, created_at, updated_at) VALUES (?,?,?,?,?)",
                ("user-1", "user", '{"id":"user-1","type":"user_profile","sourceText":"","name":"사용자"}', "t", "t"),
            )
            conn.execute(
                "INSERT INTO conversations (id, plot_id, user_profile_id, created_at, updated_at) VALUES (?,?,?,?,?)",
                ("conv-1", "plot-1", "user-1", "t", "t"),
            )
            conn.commit()

    def tearDown(self):
        writer._summary_locks.clear()
        self._tmpdir.cleanup()

    def _insert_pending_messages(self, contents: list[str]) -> list[int]:
        # RECENT_WINDOW=1이 걷어낼 "최근 메시지" 한 개를 pending 뒤에 추가해, contents 전체가
        # 그대로 pending으로 잡히게 한다.
        rowids: list[int] = []
        with self._connect() as conn:
            for content in [*contents, "(recent, excluded)"]:
                cursor = conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
                    (new_id("msg"), "conv-1", "assistant", content, "t"),
                )
                rowids.append(cursor.lastrowid)
            conn.commit()
        return rowids[:-1]

    def _summary_state(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT summary_text, summary_through_rowid FROM conversations WHERE id=:id",
                {"id": "conv-1"},
            ).fetchone()

    async def test_large_backlog_is_written_one_chunk_at_a_time(self):
        rowids = self._insert_pending_messages(["first", "second", "third"])
        requests = []

        def _stream_text(req, provider_name):
            requests.append(req)
            return _tokens(f"summary-{len(requests)}")

        with (
            patch.object(writer, "connect", self._connect),
            patch.object(writer, "RECENT_WINDOW", self._RECENT_WINDOW),
            patch.object(writer, "SUMMARY_TRIGGER", len(rowids)),
            patch.object(writer, "summary_chunk_char_limit", return_value=6),
            patch.object(writer, "stream_text", _stream_text),
        ):
            await writer.maybe_update_summary("conv-1")

        state = self._summary_state()
        self.assertEqual(len(requests), 3)
        self.assertEqual(state["summary_text"], "summary-3")
        self.assertEqual(state["summary_through_rowid"], rowids[-1])
        self.assertNotIn("second", requests[0].messages[0].content)

    async def test_failed_later_chunk_keeps_completed_progress(self):
        rowids = self._insert_pending_messages(["first", "second", "third"])
        calls = 0
        error = ProviderRuntimeError(
            ProviderErrorCode.PROVIDER_BAD_GATEWAY,
            "summary failed",
            ProviderName.LOCAL_STUB,
        )

        def _stream_text(req, provider_name):
            nonlocal calls
            calls += 1
            return _tokens("summary-1") if calls == 1 else _failure(error)

        with (
            patch.object(writer, "connect", self._connect),
            patch.object(writer, "RECENT_WINDOW", self._RECENT_WINDOW),
            patch.object(writer, "SUMMARY_TRIGGER", len(rowids)),
            patch.object(writer, "summary_chunk_char_limit", return_value=6),
            patch.object(writer, "stream_text", _stream_text),
            patch.object(writer.log, "exception"),
        ):
            await writer.maybe_update_summary("conv-1")

        state = self._summary_state()
        self.assertEqual(calls, 2)
        self.assertEqual(state["summary_text"], "summary-1")
        self.assertEqual(state["summary_through_rowid"], rowids[0])

    async def test_failed_large_chunk_retries_smaller_chunks(self):
        rowids = self._insert_pending_messages(["x" * 1_500, "y" * 1_500, "z" * 1_500])
        calls = 0
        error = ProviderRuntimeError(
            ProviderErrorCode.PROVIDER_BAD_GATEWAY,
            "input rejected",
            ProviderName.LOCAL_STUB,
        )

        def _stream_text(req, provider_name):
            nonlocal calls
            calls += 1
            return _failure(error) if calls == 1 else _tokens(f"summary-{calls}")

        with (
            patch.object(writer, "connect", self._connect),
            patch.object(writer, "RECENT_WINDOW", self._RECENT_WINDOW),
            patch.object(writer, "SUMMARY_TRIGGER", len(rowids)),
            patch.object(writer, "summary_chunk_char_limit", return_value=5_000),
            patch.object(writer, "stream_text", _stream_text),
            patch.object(writer.log, "warning"),
        ):
            await writer.maybe_update_summary("conv-1")

        state = self._summary_state()
        self.assertEqual(calls, 4)
        self.assertEqual(state["summary_through_rowid"], rowids[-1])


if __name__ == "__main__":
    unittest.main()
