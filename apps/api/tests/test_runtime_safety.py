import asyncio
import json
import os
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, classify_provider_error, runtime_error_factory
from ai.auth import claude_auth
from ai.auth.claude_auth import ClaudeGenerationActiveError
from ai.runtime.queue import BoundedRuntimeQueue
from ai.protocol.codex_protocol import CodexTurnStateMachine
from ai.protocol.codex_protocol import is_secure_thread as codex_is_secure_thread
from ai.protocol.codex_protocol import parse_started_turn_id as codex_parse_turn_start
from ai.protocol.codex_protocol import parse_model_page as codex_validate_model_page
from ai.protocol.codex_protocol import is_valid_device_login as codex_is_valid_device_login
from ai.protocol.claude_protocol import _classify_event_error as classify_claude_event_error
from ai.protocol.claude_protocol import _contains_prohibited_tool_use as claude_contains_prohibited_tool_use
from ai.protocol.claude_protocol import _extract_text_delta as extract_claude_text_delta
from ai.protocol.claude_protocol import find_structure_violation as claude_structure_violation
from ai.protocol.claude_protocol import ClaudeTurnPhase
from ai.protocol.claude_protocol import ClaudeTurnStateMachine
from ai.runtime.claude_runtime import _build_runtime_env as build_claude_runtime_env
from ai.runtime.claude_runtime import ClaudeCliRuntime
from ai.runtime.claude_runtime import _RUNTIME_ROOT as CLAUDE_RUNTIME_ROOT
from ai.providers.claude_cli import ClaudeCliProvider
from ai.protocol.codex_protocol import classify_event_error as codex_event_error
from ai.runtime.codex.runtime import _build_runtime_env as codex_runtime_env
from ai.runtime.codex.runtime import _RUNTIME_ROOT as CODEX_RUNTIME_ROOT
from ai.runtime.codex.connection import CodexRpcConnection
from ai.runtime.codex.router import _TurnRoute, CodexTurnRouter
from ai.runtime.codex.runtime import CodexAppServer
from ai.auth import codex_auth
from ai.auth.codex_auth import CodexAuthSession
from ai.runtime.util import GenerationGateBusyError, ProcessOutput, decode_runtime_message, drain_stderr, redacted, reap_process_group
from ai.settings import RUNTIME_QUEUE_SIZE
from ai.specs import GenerateRequest, Message, ProviderName


@asynccontextmanager
async def _no_op_async_gate():
    yield


@asynccontextmanager
async def _busy_async_gate():
    raise GenerationGateBusyError("a generation is currently active")
    yield


class RuntimeSafetyTests(unittest.IsolatedAsyncioTestCase):
    credential_names = (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BASE_URL",
    )

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("PINBALLCHAT_RUNTIME_ROOT")
        os.environ["PINBALLCHAT_RUNTIME_ROOT"] = self.temp_dir.name
        self.old_credentials = {name: os.environ.get(name) for name in self.credential_names}
        for name in self.old_credentials:
            os.environ[name] = "secret-value"

    def tearDown(self):
        for name, value in self.old_credentials.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if self.old_root is None:
            os.environ.pop("PINBALLCHAT_RUNTIME_ROOT", None)
        else:
            os.environ["PINBALLCHAT_RUNTIME_ROOT"] = self.old_root
        self.temp_dir.cleanup()

    def test_child_environments_are_allowlisted_and_private(self):
        for env in (codex_runtime_env(), build_claude_runtime_env()):
            self.assertFalse(set(self.credential_names) & env.keys())
            self.assertEqual(Path(env["HOME"]).stat().st_mode & 0o777, 0o700)
            self.assertEqual(Path(self.temp_dir.name).stat().st_mode & 0o777, 0o700)
            self.assertEqual((Path(self.temp_dir.name) / "scratch").stat().st_mode & 0o777, 0o700)
        self.assertIn("CODEX_HOME", codex_runtime_env())
        self.assertIn("CLAUDE_CONFIG_DIR", build_claude_runtime_env())
        self.assertEqual(build_claude_runtime_env()["DISABLE_AUTOUPDATER"], "1")
        self.assertEqual(build_claude_runtime_env()["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")

    def test_stderr_redaction_and_stable_error_mapping(self):
        self.assertEqual(redacted("prompt and oauth-code and sk-secret-token"), "[redacted]")
        self.assertEqual(codex_event_error({"error": {"code": "quota_exhausted"}}).code, "provider_quota_exhausted")
        self.assertEqual(codex_event_error({"error": {"codexErrorInfo": "unauthorized"}}).code, "provider_auth_required")
        self.assertEqual(classify_claude_event_error({"type": "error", "error": {"type": "authentication_error"}}).code, "provider_auth_required")
        self.assertEqual(classify_claude_event_error({"type": "assistant", "error": "authentication_failed"}).code, "provider_auth_required")
        self.assertEqual(classify_claude_event_error({"type": "error", "error": {"type": "model_not_found"}}).code, "model_unavailable")
        self.assertEqual(classify_claude_event_error({"type": "result", "subtype": "error_max_budget_usd", "is_error": True}).code, "provider_quota_exhausted")
        self.assertEqual(classify_provider_error("openai", {"code": "model_not_found"}).code, "model_unavailable")
        self.assertEqual(classify_provider_error("anthropic", {"type": "rate_limit_error"}).code, "provider_quota_exhausted")
        self.assertEqual(classify_provider_error("gemini", {"details": [{"reason": "API_KEY_SERVICE_BLOCKED"}]}).code, "provider_auth_required")

    def test_codex_is_secure_thread(self):
        scratch = CODEX_RUNTIME_ROOT / "scratch"
        thread_start = {
            "cwd": str(scratch), "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
            "instructionSources": [], "model": "model-1",
        }
        self.assertTrue(codex_is_secure_thread(thread_start, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "cwd": "/tmp/elsewhere"}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "approvalPolicy": "always"}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "sandbox": {"type": "workspace-write", "networkAccess": False}}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "sandbox": {"type": "readOnly", "networkAccess": True}}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "instructionSources": ["file"]}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "model": "model-2"}, "model-1", scratch))
        self.assertFalse(codex_is_secure_thread({**thread_start, "cwd": None}, "model-1", scratch))

    def test_codex_validate_model_page(self):
        self.assertEqual(codex_validate_model_page({"data": [{"model": "a", "hidden": False}, {"model": "b", "hidden": True}]}), ["a"])
        self.assertEqual(codex_validate_model_page({"data": []}), [])
        with self.assertRaisesRegex(Exception, "malformed model list"):
            codex_validate_model_page({"data": "not-a-list"})
        with self.assertRaisesRegex(Exception, "malformed model list"):
            codex_validate_model_page({"data": [{"model": "a"}]})
        with self.assertRaisesRegex(Exception, "malformed model cursor"):
            codex_validate_model_page({"data": [], "nextCursor": 123})

    def test_decode_runtime_message_covers_malformed_json_invalid_utf8_and_non_dict(self):
        make_error = runtime_error_factory(ProviderName.OPENAI_CODEX)
        cases = {
            "malformed JSON": (b"not-json", "codex runtime emitted malformed JSON"),
            "invalid UTF-8": (b"\xff", "codex runtime emitted malformed JSON"),
            "non-dict top level": (b"[1, 2, 3]", "codex runtime emitted a malformed message"),
        }
        for label, (line, expected_message) in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(ProviderRuntimeError, expected_message):
                    decode_runtime_message(
                        line,
                        runtime_name="codex",
                        non_dict_message="codex runtime emitted a malformed message",
                        make_error=make_error,
                    )

        self.assertEqual(
            decode_runtime_message(b'{"a": 1}', runtime_name="codex", non_dict_message="x", make_error=make_error),
            {"a": 1},
        )

    def test_codex_parse_turn_start(self):
        self.assertEqual(codex_parse_turn_start({"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}), "turn-1")
        self.assertIsNone(codex_parse_turn_start({"turn": {"id": "turn-1", "items": [], "status": 1}}))
        self.assertIsNone(codex_parse_turn_start({"turn": {"id": "turn-1", "items": "not-a-list", "status": "inProgress"}}))
        self.assertIsNone(codex_parse_turn_start({"turn": {"items": [], "status": "inProgress"}}))
        self.assertIsNone(codex_parse_turn_start({}))

    def test_codex_is_valid_device_login(self):
        valid = {"type": "chatgptDeviceCode", "loginId": "l", "verificationUrl": "https://x", "userCode": "ABCD"}
        self.assertTrue(codex_is_valid_device_login(valid))
        self.assertFalse(codex_is_valid_device_login({**valid, "type": "other"}))
        self.assertFalse(codex_is_valid_device_login({**valid, "loginId": ""}))
        self.assertFalse(codex_is_valid_device_login({**valid, "userCode": None}))

    def test_codex_turn_state_machine_delta_and_has_emitted(self):
        machine = CodexTurnStateMachine("turn-1")
        self.assertFalse(machine.has_emitted)
        self.assertEqual(machine.consume_event({"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i", "delta": ""}}), "")
        self.assertFalse(machine.has_emitted)
        self.assertEqual(machine.consume_event({"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i", "delta": "hi"}}), "hi")
        self.assertTrue(machine.has_emitted)

    def test_codex_turn_state_machine_malformed_delta(self):
        machine = CodexTurnStateMachine("turn-1")
        with self.assertRaisesRegex(Exception, "malformed agent message delta"):
            machine.consume_event({"method": "item/agentMessage/delta", "params": {"threadId": "t"}})

    def test_codex_turn_state_machine_item_types(self):
        machine = CodexTurnStateMachine("turn-1")
        self.assertEqual(machine.consume_event({"method": "item/started", "params": {"item": {"type": "agentMessage"}}}), "")
        with self.assertRaisesRegex(Exception, "malformed item event"):
            machine.consume_event({"method": "item/started", "params": {"item": {"type": 1}}})
        with self.assertRaisesRegex(Exception, "prohibited tool action"):
            machine.consume_event({"method": "item/started", "params": {"item": {"type": "commandExecution"}}})
        with self.assertRaisesRegex(Exception, "unknown item type"):
            machine.consume_event({"method": "item/started", "params": {"item": {"type": "mysteryType"}}})

    def test_codex_turn_state_machine_prohibited_method(self):
        machine = CodexTurnStateMachine("turn-1")
        with self.assertRaisesRegex(Exception, "prohibited tool action"):
            machine.consume_event({"method": "item/tool/call", "params": {}})

    def test_codex_turn_state_machine_completed(self):
        machine = CodexTurnStateMachine("turn-1")
        self.assertEqual(machine.consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}}), "")
        self.assertTrue(machine.completed)
        self.assertTrue(machine.terminal_received)

    def test_codex_turn_state_machine_malformed_completion_still_marks_terminal_received(self):
        machine = CodexTurnStateMachine("turn-1")
        with self.assertRaisesRegex(Exception, "malformed turn completion"):
            machine.consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}})
        self.assertTrue(machine.terminal_received)
        self.assertFalse(machine.completed)

    def test_codex_turn_state_machine_ignores_top_level_status_fallback(self):
        machine = CodexTurnStateMachine("turn-1")
        with self.assertRaisesRegex(Exception, "malformed turn completion"):
            machine.consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1"}, "status": "completed"}})
        self.assertTrue(machine.terminal_received)
        self.assertFalse(machine.completed)

    def test_codex_turn_state_machine_interrupted_and_failed_and_invalid(self):
        with self.assertRaisesRegex(Exception, "Codex generation was interrupted"):
            CodexTurnStateMachine("turn-1").consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "interrupted"}}})
        with self.assertRaises(Exception) as ctx:
            CodexTurnStateMachine("turn-1").consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "failed", "error": {"code": "quota_exhausted"}}}})
        self.assertEqual(ctx.exception.code, "provider_quota_exhausted")
        with self.assertRaisesRegex(Exception, "invalid status"):
            CodexTurnStateMachine("turn-1").consume_event({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "weird"}}})

    def test_codex_turn_state_machine_ignores_unrelated_method(self):
        machine = CodexTurnStateMachine("turn-1")
        self.assertEqual(machine.consume_event({"method": "some/other/event", "params": {}}), "")
        self.assertFalse(machine.completed)
        self.assertFalse(machine.terminal_received)

    def test_claude_nested_stream_events(self):
        event = {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}}
        self.assertEqual(extract_claude_text_delta(event), "hello")
        tool = {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}}}
        self.assertTrue(claude_contains_prohibited_tool_use(tool))

    @staticmethod
    def _claude_structure_error(event):
        return claude_structure_violation(event)

    def test_claude_structure_error_matches_legacy_messages(self):
        scratch = str(CLAUDE_RUNTIME_ROOT / "scratch")
        self.assertIsNone(self._claude_structure_error({"type": "system", "subtype": "init", "cwd": scratch, "tools": [], "mcp_servers": []}))
        self.assertEqual(self._claude_structure_error({"type": 1}), "claude runtime emitted a malformed stream event")
        self.assertEqual(self._claude_structure_error({"type": "stream_event", "event": "not-a-dict"}), "claude runtime emitted a malformed nested stream event")
        self.assertEqual(self._claude_structure_error({"type": "stream_event", "event": {"type": 1}}), "claude runtime emitted a malformed nested stream event")
        self.assertEqual(
            self._claude_structure_error({"type": "stream_event", "event": {"type": "content_block_start", "content_block": "nope"}}),
            "claude runtime emitted a malformed content block",
        )
        self.assertEqual(
            self._claude_structure_error({"type": "content_block_start", "content_block": "nope"}),
            "claude runtime emitted a malformed content block",
        )
        self.assertEqual(
            self._claude_structure_error({"type": "stream_event", "event": {"type": "error", "error": "nope"}}),
            "claude runtime emitted a malformed error event",
        )
        self.assertEqual(self._claude_structure_error({"type": "error", "error": "nope"}), "claude runtime emitted a malformed error event")
        self.assertEqual(self._claude_structure_error({"type": "assistant", "message": "nope"}), "claude runtime emitted a malformed message event")
        self.assertEqual(
            self._claude_structure_error({"type": "user", "message": {"content": "nope"}}),
            "claude runtime emitted a malformed message event",
        )
        self.assertIsNone(self._claude_structure_error({"type": "assistant", "message": {"content": []}}))

    @staticmethod
    def _claude_init_event():
        return {"type": "system", "subtype": "init", "cwd": str(CLAUDE_RUNTIME_ROOT / "scratch"), "tools": [], "mcp_servers": []}

    @staticmethod
    def _claude_result_event(result="hi", output_tokens=1):
        return {
            "type": "result", "subtype": "success", "is_error": False,
            "result": result, "usage": {"input_tokens": 3, "output_tokens": output_tokens},
            "permission_denials": [],
        }

    @staticmethod
    def _claude_delta_event(text):
        return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}

    def test_claude_turn_state_machine_phase_transitions(self):
        machine = ClaudeTurnStateMachine(CLAUDE_RUNTIME_ROOT / "scratch")
        self.assertEqual(machine.phase, ClaudeTurnPhase.AWAITING_INIT)

        with self.assertRaisesRegex(Exception, "text before initialization"):
            machine.consume_event(self._claude_delta_event("too early"))

        self.assertEqual(machine.consume_event(self._claude_init_event()), "")
        self.assertEqual(machine.phase, ClaudeTurnPhase.STREAMING)

        with self.assertRaisesRegex(Exception, "duplicate initialization"):
            machine.consume_event(self._claude_init_event())

        self.assertEqual(machine.consume_event(self._claude_result_event()), "")
        self.assertEqual(machine.phase, ClaudeTurnPhase.FINISHED)
        self.assertEqual(machine.result_text, "hi")
        self.assertEqual(machine.result_usage, {"input_tokens": 3, "output_tokens": 1})

        with self.assertRaisesRegex(Exception, "event after the final result"):
            machine.consume_event(self._claude_delta_event("late"))

    def test_claude_turn_state_machine_result_without_init(self):
        machine = ClaudeTurnStateMachine(CLAUDE_RUNTIME_ROOT / "scratch")
        self.assertEqual(machine.consume_event(self._claude_result_event(result="done")), "")
        self.assertEqual(machine.phase, ClaudeTurnPhase.FINISHED_WITHOUT_INIT)
        self.assertEqual(machine.result_text, "done")
        self.assertIsNotNone(machine.result_usage)

        with self.assertRaisesRegex(Exception, "event after the final result"):
            machine.consume_event(self._claude_delta_event("late"))

    def test_claude_turn_state_machine_yields_top_level_delta(self):
        machine = ClaudeTurnStateMachine(CLAUDE_RUNTIME_ROOT / "scratch")
        machine.consume_event(self._claude_init_event())
        top_level_delta = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
        self.assertEqual(machine.consume_event(top_level_delta), "hi")

    def test_claude_turn_state_machine_accumulates_emitted_text(self):
        machine = ClaudeTurnStateMachine(CLAUDE_RUNTIME_ROOT / "scratch")
        machine.consume_event(self._claude_init_event())
        self.assertEqual(machine.consume_event(self._claude_delta_event("he")), "he")
        self.assertEqual(machine.consume_event(self._claude_delta_event("llo")), "llo")
        self.assertEqual(machine.emitted_text, ["he", "llo"])
        self.assertTrue(machine.has_emitted_text)

    async def test_claude_bounded_queue_fails_when_consumer_is_blocked(self):
        runtime = ClaudeCliRuntime()
        stream = asyncio.StreamReader()
        stream.feed_data(b'{"type":"system"}\n{"type":"system"}\n')
        stream.feed_eof()
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=0.01)
        await runtime._read_event_stream(stream, queue)
        with self.assertRaises(ProviderTimeoutError) as ctx:
            await queue.get(timeout=1)
        self.assertEqual(ctx.exception.phase, "idle")

    async def test_codex_interrupt_requires_interrupted_completion(self):
        app_server = CodexAppServer()
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.put({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}}})
        with (
            patch.object(app_server, "call_runtime", new=AsyncMock(return_value={})),
            patch.object(app_server, "_terminate_runtime", new=AsyncMock()) as terminate,
        ):
            with self.assertRaisesRegex(Exception, "did not complete as interrupted"):
                await app_server._interrupt_turn("thread-1", "turn-1", queue)
            terminate.assert_awaited_once()

    async def test_codex_crash_reaches_a_full_inflight_queue(self):
        app_server = CodexAppServer()
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        await queue.put({"method": "old"})
        app_server._router._turn_routes["turn-1"] = _TurnRoute(queue=queue)
        await app_server._crash(codex_event_error({"error": {"code": "quota_exhausted"}}))
        with self.assertRaises(Exception) as ctx:
            await queue.get(timeout=1)
        self.assertEqual(ctx.exception.code, "provider_quota_exhausted")

    async def test_codex_generator_close_interrupts_the_turn(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)

        async def request_rpc(method, params, *_args, **_kwargs):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                self.assertEqual(params.get("baseInstructions"), "system")
                self.assertNotIn("developerInstructions", params)
                return {
                    "thread": {"id": "thread-1", "ephemeral": True},
                    "cwd": str(CODEX_RUNTIME_ROOT / "scratch"),
                    "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                    "instructionSources": [], "model": "model-1",
                }
            if method == "turn/start":
                return {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}
            raise AssertionError(method)

        with (
            patch.object(app_server, "ensure_started", new=AsyncMock()),
            patch.object(app_server, "rpc", side_effect=request_rpc),
            patch.object(app_server, "_interrupt_turn", new=AsyncMock()) as interrupt,
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
        ):
            stream = app_server.stream(request)
            first = asyncio.create_task(anext(stream))
            for _ in range(100):
                if "turn-1" in app_server._router._turn_routes:
                    break
                await asyncio.sleep(0)
            self.assertIn("turn-1", app_server._router._turn_routes)
            await app_server._router._turn_routes["turn-1"].queue.put({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "hi"},
            })
            self.assertEqual(await first, "hi")
            await stream.aclose()
            interrupt.assert_awaited_once()

    async def test_codex_tombstoned_turn_late_event_is_ignored_not_rebuffered(self):
        # K1 이후 라우팅은 CodexTurnRouter가 전담하므로 reader/connection 없이 직접 검증한다.
        app_server = CodexAppServer()
        app_server._router._turn_tombstones["turn-1"] = None
        await app_server._router.route_event({
            "method": "item/agentMessage/delta",
            "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "late"},
        })
        self.assertNotIn("turn-1", app_server._router._early_turn_events)
        self.assertNotIn("turn-1", app_server._router._turn_routes)

    async def test_codex_early_buffered_events_preserve_order_after_route_creation(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)
        app_server._router._early_turn_events["turn-1"] = [
            {"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "he"}},
            {"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "llo"}},
        ]

        async def request_rpc(method, params, *_args, **_kwargs):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return {
                    "thread": {"id": "thread-1", "ephemeral": True},
                    "cwd": str(CODEX_RUNTIME_ROOT / "scratch"),
                    "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                    "instructionSources": [], "model": "model-1",
                }
            if method == "turn/start":
                return {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}
            raise AssertionError(method)

        with (
            patch.object(app_server, "ensure_started", new=AsyncMock()),
            patch.object(app_server, "rpc", side_effect=request_rpc),
            patch.object(app_server, "_interrupt_turn", new=AsyncMock()),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
        ):
            stream = app_server.stream(request)
            first = await anext(stream)
            second = await anext(stream)
            self.assertEqual([first, second], ["he", "llo"])
            await stream.aclose()

    async def test_codex_open_secure_thread_schedules_cleanup_with_correct_persisted_on_violation(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)

        async def request_rpc(method, params, *_args, **_kwargs):
            if method == "thread/start":
                return {
                    "thread": {"id": "thread-1", "ephemeral": False},
                    "cwd": str(CODEX_RUNTIME_ROOT / "scratch"),
                    "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                    "instructionSources": [], "model": "a-different-model",
                }
            raise AssertionError(method)

        with (
            patch.object(app_server, "rpc", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()) as cleanup,
        ):
            with self.assertRaisesRegex(ProviderRuntimeError, "isolated runtime policy"):
                await app_server._start_isolated_thread(request, time.monotonic() + 1.0)
        # ephemeral False => persisted True
        cleanup.assert_called_once_with("thread-1", True)

    async def test_codex_route_retirement_handles_either_completion_order(self):
        app_server = CodexAppServer()

        queue_a = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        app_server._router._turn_routes["turn-a"] = _TurnRoute(queue=queue_a)
        await app_server._router.route_event({"method": "turn/completed", "params": {"turnId": "turn-a"}})
        self.assertIn("turn-a", app_server._router._turn_routes)
        app_server._router.mark_consumer_finished("turn-a")
        self.assertNotIn("turn-a", app_server._router._turn_routes)
        self.assertIn("turn-a", app_server._router._turn_tombstones)

        queue_b = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        app_server._router._turn_routes["turn-b"] = _TurnRoute(queue=queue_b)
        app_server._router.mark_consumer_finished("turn-b")
        self.assertIn("turn-b", app_server._router._turn_routes)
        await app_server._router.route_event({"method": "turn/completed", "params": {"turnId": "turn-b"}})
        self.assertNotIn("turn-b", app_server._router._turn_routes)
        self.assertIn("turn-b", app_server._router._turn_tombstones)

    async def test_codex_overflow_on_one_turn_propagates_failure_to_other_turns(self):
        app_server = CodexAppServer()
        full_queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        await full_queue.put({"method": "old"})
        other_queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        app_server._router._turn_routes["turn-1"] = _TurnRoute(queue=full_queue)
        app_server._router._turn_routes["turn-2"] = _TurnRoute(queue=other_queue)

        # K2 이후 라우팅+승격은 _on_notification(facade)이 담당한다 — reader/connection 없이 직접 호출.
        # _abort_connection의 identity guard(process/epoch)를 통과시키려면 현재 상태와 맞춰줘야 한다.
        # _terminate_runtime은 mock한다 — F1 이후 이 경로가 실제 terminate를 fire-and-forget으로
        # 예약하는데, mock pid=1로 진짜 reap_process_group을 태우면 os.killpg(1, ...)(=init)을
        # 시도하게 된다.
        process = Mock(pid=1, returncode=None)
        app_server._process = process
        app_server._current_epoch = 1
        with patch.object(app_server, "_terminate_runtime", new=AsyncMock()):
            keep_reading = await app_server._on_notification(process, 1, {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "x"},
            })
            await asyncio.sleep(0)
        self.assertFalse(keep_reading)

        for queue in (full_queue, other_queue):
            with self.assertRaises(ProviderRuntimeError) as caught:
                await queue.get(timeout=1)
            self.assertEqual(caught.exception.code, ProviderErrorCode.PROVIDER_TIMEOUT)
            self.assertTrue(caught.exception.retryable)
            self.assertEqual(caught.exception.phase, "idle")

    async def test_codex_crash_discards_pending_items_and_delivers_error_immediately(self):
        app_server = CodexAppServer()
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.put({"method": "pending-item"})
        app_server._router._turn_routes["turn-1"] = _TurnRoute(queue=queue)
        error = codex_event_error({"error": {"code": "quota_exhausted"}})
        await app_server._crash(error)
        with self.assertRaises(Exception) as ctx:
            await queue.get(timeout=1)
        self.assertIs(ctx.exception, error)
        self.assertNotIn("turn-1", app_server._router._turn_routes)
        self.assertIn("turn-1", app_server._router._turn_tombstones)

    async def test_codex_late_routing_to_closed_queue_is_harmless(self):
        app_server = CodexAppServer()
        closed_queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await closed_queue.close()
        app_server._router._turn_routes["turn-1"] = _TurnRoute(queue=closed_queue, terminal_seen=True)

        await app_server._router.route_event({
            "method": "item/agentMessage/delta",
            "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "late"},
        })

        self.assertIsNone(app_server._crash_error)
        self.assertIn("turn-1", app_server._router._turn_routes)

    @staticmethod
    def _codex_request_rpc_for_turn_1():
        async def request_rpc(method, params, *_args, **_kwargs):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return {
                    "thread": {"id": "thread-1", "ephemeral": True},
                    "cwd": str(CODEX_RUNTIME_ROOT / "scratch"),
                    "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                    "instructionSources": [], "model": "model-1",
                }
            if method == "turn/start":
                return {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}
            raise AssertionError(method)
        return request_rpc

    async def test_codex_disconnect_confirms_interrupt_and_tombstones_route(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)

        with (
            patch.object(app_server, "ensure_started", new=AsyncMock()),
            patch.object(app_server, "rpc", side_effect=self._codex_request_rpc_for_turn_1()),
            patch.object(app_server, "call_runtime", new=AsyncMock(return_value={})),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
        ):
            stream = app_server.stream(request)
            first = asyncio.create_task(anext(stream))
            for _ in range(100):
                if "turn-1" in app_server._router._turn_routes:
                    break
                await asyncio.sleep(0)
            route = app_server._router._turn_routes["turn-1"]
            await route.queue.put({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "hi"},
            })
            self.assertEqual(await first, "hi")

            async def deliver_interrupted_completion():
                # router 역할을 흉내낸다: turn/completed(interrupted)를 넣고 route를 닫는다.
                await asyncio.sleep(0.01)
                route.terminal_seen = True
                await route.queue.put({
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turnId": "turn-1", "turn": {"id": "turn-1", "status": "interrupted"}},
                })
                await route.queue.close()

            deliver_task = asyncio.create_task(deliver_interrupted_completion())
            await stream.aclose()
            await deliver_task

            self.assertNotIn("turn-1", app_server._router._turn_routes)
            self.assertIn("turn-1", app_server._router._turn_tombstones)

    async def test_codex_interrupt_grace_timeout_fails_all_inflight_routes(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)
        other_queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        app_server._router._turn_routes["turn-2"] = _TurnRoute(queue=other_queue)

        with (
            patch.object(app_server, "ensure_started", new=AsyncMock()),
            patch.object(app_server, "rpc", side_effect=self._codex_request_rpc_for_turn_1()),
            patch.object(app_server, "call_runtime", new=AsyncMock(return_value={})),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
            patch("ai.runtime.codex.runtime.RUNTIME_INTERRUPT_GRACE_SECONDS", 0.02),
        ):
            stream = app_server.stream(request)
            first = asyncio.create_task(anext(stream))
            for _ in range(100):
                if "turn-1" in app_server._router._turn_routes:
                    break
                await asyncio.sleep(0)
            route = app_server._router._turn_routes["turn-1"]
            await route.queue.put({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "hi"},
            })
            self.assertEqual(await first, "hi")

            # 아무도 interrupted 완료를 넣어주지 않음 — grace timeout으로 전체 crash.
            await stream.aclose()

        self.assertIsNotNone(app_server._crash_error)
        with self.assertRaises(Exception):
            await other_queue.get(timeout=1)

    async def test_codex_route_removed_only_after_consumer_and_terminal_both_done(self):
        app_server = CodexAppServer()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)

        with (
            patch.object(app_server, "ensure_started", new=AsyncMock()),
            patch.object(app_server, "rpc", side_effect=self._codex_request_rpc_for_turn_1()),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
        ):
            stream = app_server.stream(request)
            first = asyncio.create_task(anext(stream))
            for _ in range(100):
                if "turn-1" in app_server._router._turn_routes:
                    break
                await asyncio.sleep(0)
            route = app_server._router._turn_routes["turn-1"]
            await route.queue.put({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "hi"},
            })
            self.assertEqual(await first, "hi")

            # turn/completed 도착 전 — route는 아직 남아있어야 한다.
            self.assertIn("turn-1", app_server._router._turn_routes)
            self.assertFalse(route.terminal_seen)
            self.assertFalse(route.consumer_done)

            # router 역할을 흉내낸다.
            route.terminal_seen = True
            await route.queue.put({
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "turn": {"id": "turn-1", "status": "completed"}},
            })
            await route.queue.close()

            with self.assertRaises(StopAsyncIteration):
                await anext(stream)

            self.assertNotIn("turn-1", app_server._router._turn_routes)
            self.assertIn("turn-1", app_server._router._turn_tombstones)

    async def test_codex_auth_login_completed_hook_marks_connected_and_cancels_timeout(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)

        async def sleep_forever():
            await asyncio.sleep(100)

        session._login_state = codex_auth._CodexLoginState(status="login_pending", verification_url="https://example.com", user_code="ABCD", started_at=0.0, login_id="login-1")
        session._login_timeout_task = asyncio.create_task(sleep_forever())
        await asyncio.sleep(0)

        # 가짜 reader 경로: runtime이 malformed 검증을 통과시킨 뒤 hook을 호출하는 상황을 흉내낸다.
        app_server._on_login_completed(True)
        await asyncio.sleep(0)

        self.assertEqual(session.get_login_state()["status"], "connected")
        self.assertTrue(session._login_timeout_task.cancelled())

    async def test_codex_auth_crash_hook_reverts_login_pending_to_error(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)
        session._login_state = codex_auth._CodexLoginState(status="login_pending", verification_url="https://example.com", user_code="ABCD", started_at=0.0, login_id="login-1")

        app_server._on_crash(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED)

        self.assertEqual(session._login_state, codex_auth._CodexLoginState(status="error", error_code=ProviderErrorCode.PROVIDER_RUNTIME_CRASHED))

    async def test_codex_turn_router_attach_route_mark_consumer_finished_boundary(self):
        router = CodexTurnRouter()
        queue, overflow = await router.attach_turn("turn-1")
        self.assertIsNone(overflow)

        await router.route_event({
            "method": "item/agentMessage/delta",
            "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i", "delta": "hi"},
        })
        self.assertEqual((await queue.get(timeout=1))["params"]["delta"], "hi")

        await router.route_event({
            "method": "turn/completed",
            "params": {"turnId": "turn-1", "turn": {"id": "turn-1", "status": "completed"}},
        })
        self.assertIn("turn-1", router._turn_routes)

        router.mark_consumer_finished("turn-1")
        self.assertNotIn("turn-1", router._turn_routes)
        self.assertIn("turn-1", router._turn_tombstones)

    async def test_codex_turn_router_early_buffer_aggregate_overflow_contract(self):
        router = CodexTurnRouter()
        for i in range(RUNTIME_QUEUE_SIZE):
            await router.route_event({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "t", "turnId": f"turn-{i % 2}", "itemId": "i", "delta": "x"},
            })
        with self.assertRaises(ProviderRuntimeError) as caught:
            await router.route_event({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "t", "turnId": "turn-0", "itemId": "i", "delta": "x"},
            })
        self.assertEqual(caught.exception.code, ProviderErrorCode.PROVIDER_TIMEOUT)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.phase, "idle")

    async def test_codex_turn_router_fail_all_boundary(self):
        router = CodexTurnRouter()
        queue_a, _ = await router.attach_turn("turn-a")
        queue_b, _ = await router.attach_turn("turn-b")
        error = codex_event_error({"error": {"code": "quota_exhausted"}})

        await router.abort_all(error)

        self.assertNotIn("turn-a", router._turn_routes)
        self.assertNotIn("turn-b", router._turn_routes)
        self.assertIn("turn-a", router._turn_tombstones)
        self.assertIn("turn-b", router._turn_tombstones)
        for queue in (queue_a, queue_b):
            with self.assertRaises(Exception) as ctx:
                await queue.get(timeout=1)
            self.assertIs(ctx.exception, error)

    async def test_codex_connection_concurrent_requests_match_correct_response(self):
        connection = CodexRpcConnection()
        written: list[bytes] = []

        class FakeStdin:
            def write(self, value): written.append(value)
            async def drain(self): pass

        stdout = asyncio.StreamReader()
        process = Mock(pid=1, returncode=None, stdin=FakeStdin(), stdout=stdout)
        connection.bind(process, AsyncMock(return_value=True), AsyncMock())

        task_a = asyncio.create_task(connection.call("a/method", {}))
        task_b = asyncio.create_task(connection.call("b/method", {}))
        for _ in range(100):
            if len(written) == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(written), 2)
        ids = [json.loads(payload)["id"] for payload in written]
        self.assertNotEqual(ids[0], ids[1])

        # 응답을 요청 순서와 반대로 흘려도 각 future가 자기 ID에 맞는 결과를 받아야 한다.
        stdout.feed_data((json.dumps({"id": ids[1], "result": {"who": "b"}}) + "\n").encode())
        stdout.feed_data((json.dumps({"id": ids[0], "result": {"who": "a"}}) + "\n").encode())

        self.assertEqual(await task_a, {"who": "a"})
        self.assertEqual(await task_b, {"who": "b"})

    async def test_codex_connection_rebind_isolates_stale_reader(self):
        connection = CodexRpcConnection()
        process_a = Mock(pid=1, returncode=None, stdout=asyncio.StreamReader())
        notifications: list[tuple[int, dict]] = []
        failure_calls: list[tuple[int, ProviderRuntimeError]] = []

        async def on_notification(_process, epoch, event):
            notifications.append((epoch, event))
            return True

        async def on_failure(_process, epoch, error):
            failure_calls.append((epoch, error))

        epoch_a = connection.bind(process_a, on_notification, on_failure)
        process_b = Mock(pid=2, returncode=None, stdout=asyncio.StreamReader())
        epoch_b = connection.bind(process_b, on_notification, on_failure)
        self.assertNotEqual(epoch_a, epoch_b)

        # rebind 후 예전 reader(epoch_a)에 이벤트/EOF가 흘러도 현재 connection에는 무영향이어야 한다.
        process_a.stdout.feed_data(b'{"method":"ignored","params":{}}\n')
        process_a.stdout.feed_eof()
        for _ in range(100):
            await asyncio.sleep(0)

        self.assertEqual(notifications, [])
        self.assertEqual(failure_calls, [])
        self.assertTrue(connection.is_bound)

    async def test_codex_active_route_overflow_schedules_terminate(self):
        # F1 회귀 테스트: 살아있는 route의 overflow도 early-buffer overflow와 마찬가지로
        # crash뿐 아니라 해당 process의 terminate까지 예약해야 한다.
        app_server = CodexAppServer()
        full_queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        await full_queue.put({"method": "old"})
        app_server._router._turn_routes["turn-1"] = _TurnRoute(queue=full_queue)
        process = Mock(pid=1, returncode=None)
        app_server._process = process
        app_server._current_epoch = 1

        with patch.object(app_server, "_terminate_runtime", new=AsyncMock()) as terminate:
            keep_reading = await app_server._on_notification(process, 1, {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i", "delta": "x"},
            })
            await asyncio.sleep(0)

        self.assertFalse(keep_reading)
        self.assertIsNotNone(app_server._crash_error)
        terminate.assert_awaited_once()
        _, kwargs = terminate.call_args
        self.assertIs(kwargs.get("target"), process)

    async def test_codex_early_buffer_overflow_schedules_terminate(self):
        # F1 회귀 테스트 — early-buffer 합산 overflow(router.route()의 elif 분기)도
        # _on_notification을 거쳐 crash+terminate로 승격돼야 한다.
        app_server = CodexAppServer()
        process = Mock(pid=1, returncode=None)
        app_server._process = process
        app_server._current_epoch = 1
        for i in range(RUNTIME_QUEUE_SIZE):
            await app_server._router.route_event({
                "method": "item/agentMessage/delta",
                "params": {"threadId": "t", "turnId": f"turn-{i % 2}", "itemId": "i", "delta": "x"},
            })

        with patch.object(app_server, "_terminate_runtime", new=AsyncMock()) as terminate:
            keep_reading = await app_server._on_notification(process, 1, {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "t", "turnId": "turn-0", "itemId": "i", "delta": "x"},
            })
            await asyncio.sleep(0)

        self.assertFalse(keep_reading)
        self.assertIsNotNone(app_server._crash_error)
        terminate.assert_awaited_once()

    async def test_codex_abort_connection_ignores_stale_process_epoch(self):
        # F3 회귀 테스트: stale (process, epoch)로 _abort_connection이 불려도 현재 runtime을
        # crash/terminate하면 안 된다.
        app_server = CodexAppServer()
        current_process = Mock(pid=2, returncode=None)
        app_server._process = current_process
        app_server._current_epoch = 2
        stale_process = Mock(pid=1, returncode=None)
        error = codex_event_error({"error": {"code": "quota_exhausted"}})

        with patch.object(app_server, "_terminate_runtime", new=AsyncMock()) as terminate:
            # process도 epoch도 stale인 경우
            await app_server._abort_connection(stale_process, 1, error)
            self.assertIsNone(app_server._crash_error)
            terminate.assert_not_called()

            # process는 현재와 같지만 epoch만 stale인 경우
            await app_server._abort_connection(current_process, 1, error)
            self.assertIsNone(app_server._crash_error)
            terminate.assert_not_called()

    async def test_codex_crash_does_not_touch_already_done_futures(self):
        app_server = CodexAppServer()
        loop = asyncio.get_running_loop()
        done_future = loop.create_future()
        done_future.set_result({"ok": True})
        app_server._connection._pending_requests[1] = done_future
        # done future에 set_exception을 다시 호출하면 InvalidStateError가 난다 — crash가
        # future.done() 체크를 지키는지 이 방식으로 검증한다.
        await app_server._crash(codex_event_error({"error": {"code": "quota_exhausted"}}))
        self.assertEqual(await done_future, {"ok": True})

    async def test_codex_start_serializes_concurrent_callers_to_one_initialize(self):
        app_server = CodexAppServer()
        initialize_calls = 0

        async def fake_timed_request(method, *_args, **_kwargs):
            nonlocal initialize_calls
            if method == "initialize":
                initialize_calls += 1
                await asyncio.sleep(0.01)
            return {}

        process = Mock(pid=1, returncode=None, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())
        with (
            patch("ai.runtime.codex.runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch.object(app_server, "_preflight", new=AsyncMock(return_value="codex-cli 0.0.0")),
            patch.object(app_server, "rpc", side_effect=fake_timed_request),
            patch.object(app_server, "call_runtime", new=AsyncMock(return_value={})),
        ):
            await asyncio.gather(app_server.ensure_started(), app_server.ensure_started(), app_server.ensure_started())
        self.assertEqual(initialize_calls, 1)

    async def test_codex_start_waits_out_restart_backoff_after_a_crash(self):
        app_server = CodexAppServer()
        app_server._last_crash_at = time.monotonic()
        process = Mock(pid=1, returncode=None, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())
        with (
            patch("ai.runtime.codex.runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch.object(app_server, "_preflight", new=AsyncMock(return_value="codex-cli 0.0.0")),
            patch.object(app_server, "rpc", new=AsyncMock(return_value={})),
            patch.object(app_server, "call_runtime", new=AsyncMock(return_value={})),
            patch("ai.runtime.codex.runtime.RUNTIME_RESTART_BACKOFF_SECONDS", 0.05),
            patch("ai.runtime.codex.runtime.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            await app_server.ensure_started()
        self.assertTrue(sleep.await_args_list)
        self.assertGreater(sleep.await_args_list[0].args[0], 0)

    async def test_codex_try_cleanup_request_returns_result_on_success(self):
        app_server = CodexAppServer()
        with patch.object(app_server, "call_runtime", new=AsyncMock(return_value={"ok": True})):
            result = await app_server._try_cleanup_request("thread/list", {})
        self.assertEqual(result, {"ok": True})

    async def test_codex_try_cleanup_request_logs_warning_and_returns_none_on_failure(self):
        app_server = CodexAppServer()
        with (
            patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=RuntimeError("boom"))),
            self.assertLogs("ai.runtime.codex.runtime", level="WARNING") as captured,
        ):
            result = await app_server._try_cleanup_request("thread/list", {}, warning="cleanup failed")
        self.assertIsNone(result)
        self.assertIn("cleanup failed", captured.output[0])

    async def test_codex_try_cleanup_request_fails_silently_without_warning(self):
        app_server = CodexAppServer()
        with (
            patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=RuntimeError("boom"))),
            self.assertNoLogs("ai.runtime.codex.runtime", level="WARNING"),
        ):
            result = await app_server._try_cleanup_request("thread/unsubscribe", {})
        self.assertIsNone(result)

    async def test_codex_try_cleanup_request_propagates_cancellation(self):
        app_server = CodexAppServer()
        with patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await app_server._try_cleanup_request("thread/list", {}, warning="cleanup failed")

    async def test_codex_persisted_thread_cleanup_paginates_and_continues_past_delete_failure(self):
        app_server = CodexAppServer()
        process = Mock(pid=1, returncode=None, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())
        deleted_thread_ids = []

        async def fake_raw_request(method, params):
            if method == "thread/list" and not params.get("cursor"):
                return {"data": [{"id": "thread-1", "ephemeral": False}], "nextCursor": "page-2"}
            if method == "thread/list" and params.get("cursor") == "page-2":
                return {"data": [{"id": "thread-2", "ephemeral": False}], "nextCursor": None}
            if method == "thread/delete" and params.get("threadId") == "thread-1":
                raise RuntimeError("delete failed")
            if method == "thread/delete" and params.get("threadId") == "thread-2":
                deleted_thread_ids.append(params["threadId"])
                return {}
            raise AssertionError((method, params))

        with (
            patch("ai.runtime.codex.runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch.object(app_server, "_preflight", new=AsyncMock(return_value="codex-cli 0.0.0")),
            patch.object(app_server, "rpc", new=AsyncMock(return_value={})),
            patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=fake_raw_request)),
            self.assertLogs("ai.runtime.codex.runtime", level="WARNING") as captured,
        ):
            await app_server.ensure_started()
        self.assertEqual(deleted_thread_ids, ["thread-2"])
        self.assertIn("Codex persisted thread cleanup failed", captured.output[0])

    async def test_codex_persisted_thread_cleanup_tolerates_thread_list_failure(self):
        app_server = CodexAppServer()
        process = Mock(pid=1, returncode=None, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())

        async def fake_raw_request(method, params):
            if method == "thread/list":
                raise RuntimeError("list failed")
            raise AssertionError((method, params))

        with (
            patch("ai.runtime.codex.runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch.object(app_server, "_preflight", new=AsyncMock(return_value="codex-cli 0.0.0")),
            patch.object(app_server, "rpc", new=AsyncMock(return_value={})),
            patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=fake_raw_request)),
            self.assertLogs("ai.runtime.codex.runtime", level="WARNING") as captured,
        ):
            await app_server.ensure_started()
        self.assertEqual(len(captured.output), 1)
        self.assertIn("Codex startup thread cleanup failed", captured.output[0])

    async def test_codex_schedule_thread_cleanup_ignores_unsubscribe_and_delete_failures(self):
        app_server = CodexAppServer()
        with patch.object(app_server, "call_runtime", new=AsyncMock(side_effect=RuntimeError("boom"))):
            app_server._schedule_thread_cleanup("thread-1", True)
            tasks = tuple(app_server._cleanup_tasks)
            self.assertEqual(len(tasks), 1)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_codex_cancelled_request_ignores_its_late_response_once(self):
        app_server = CodexAppServer()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self):
                raise asyncio.CancelledError()

        process = Mock(pid=1, returncode=None, stdin=FakeStdin())
        app_server._connection._process = process
        app_server._connection._epoch = 1
        with self.assertRaises(asyncio.CancelledError):
            await app_server.call_runtime("some/method", {})
        self.assertIn(1, app_server._connection._ignored_response_ids)

        # 같은 connection(process, epoch)에서 late response가 도착하는 상황을 흉내낸다.
        # EOF를 주지 않아 finally의 crash 경로는 타지 않는다 — 늦은 response 무시만 검증.
        stdout = asyncio.StreamReader()
        stdout.feed_data(b'{"id":1,"result":{}}\n')
        process.stdout = stdout
        reader_task = asyncio.create_task(app_server._connection._read_events(process, 1))
        try:
            for _ in range(100):
                if 1 not in app_server._connection._ignored_response_ids:
                    break
                await asyncio.sleep(0)
            self.assertNotIn(1, app_server._connection._ignored_response_ids)
            self.assertIsNone(app_server._crash_error)
        finally:
            reader_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await reader_task

    async def test_claude_generator_close_reaps_the_process_group(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stdout.feed_data((
            '{"type":"system","subtype":"init","cwd":"' + str(CLAUDE_RUNTIME_ROOT / "scratch") + '","tools":[],"mcp_servers":[]}\n'
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}\n'
        ).encode())
        stderr = asyncio.StreamReader()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): pass
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()) as reap,
        ):
            stream = runtime.stream(request)
            self.assertEqual(await anext(stream), "hi")
            await stream.aclose()
            self.assertGreaterEqual(reap.await_count, 1)

    async def test_claude_malformed_event_propagates_as_failure(self):
        runtime = ClaudeCliRuntime()
        stream = asyncio.StreamReader()
        stream.feed_data(b"not-json\n")
        stream.feed_eof()
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await runtime._read_event_stream(stream, queue)
        with self.assertRaisesRegex(Exception, "malformed JSON"):
            await queue.get(timeout=1)

    async def test_claude_compatibility_check_covers_generation_and_auth_surfaces(self):
        runtime = ClaudeCliRuntime()
        generation_flags = " ".join((
            "--print", "--output-format", "--verbose", "--include-partial-messages", "--safe-mode",
            "--system-prompt", "--tools", "--disallowedTools", "--strict-mcp-config",
            "--disable-slash-commands", "--no-chrome", "--no-session-persistence", "--model",
        ))
        outputs = {
            ("--help",): generation_flags,
            ("auth", "--help"): "login logout status",
            ("auth", "login", "--help"): "--claudeai",
            ("auth", "status", "--help"): "--json",
        }

        async def capture(_command, *args, **_kwargs):
            return ProcessOutput(returncode=0, stdout=outputs[args].encode(), stderr=b"")

        with (
            patch.object(runtime, "version", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.run_subprocess_capture", new=AsyncMock(side_effect=capture)) as run,
        ):
            await runtime.verify_compatibility("login")
        self.assertEqual([call.args[1:] for call in run.await_args_list], list(outputs))

    async def test_claude_prompt_delivery_timeout_reaps_the_child(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): raise TimeoutError()
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()) as reap,
        ):
            with self.assertRaises(ProviderTimeoutError) as ctx:
                async for _ in runtime.stream(request):
                    pass
        self.assertEqual(ctx.exception.phase, "first_delta")
        self.assertGreaterEqual(reap.await_count, 1)

    async def test_claude_result_without_init_ends_without_initialization(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stdout.feed_data((
            '{"type":"result","subtype":"success","is_error":false,"result":"hi","usage":{"input_tokens":3,"output_tokens":1},"permission_denials":[]}\n'
        ).encode())
        stdout.feed_eof()
        stderr = asyncio.StreamReader()
        stderr.feed_eof()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): pass
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock(return_value=0)
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()),
        ):
            with self.assertRaisesRegex(Exception, "claude runtime ended without initialization"):
                async for _ in runtime.stream(request):
                    pass

    async def test_claude_eof_without_result_is_not_treated_as_success(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stdout.feed_data((
            '{"type":"system","subtype":"init","cwd":"' + str(CLAUDE_RUNTIME_ROOT / "scratch") + '","tools":[],"mcp_servers":[]}\n'
        ).encode())
        stdout.feed_eof()
        stderr = asyncio.StreamReader()
        stderr.feed_eof()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): pass
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock(return_value=0)
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()),
        ):
            with self.assertRaisesRegex(Exception, "ended without a result event"):
                async for _ in runtime.stream(request):
                    pass

    async def test_claude_success_compares_result_and_collects_usage(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stdout.feed_data((
            '{"type":"system","subtype":"init","cwd":"' + str(CLAUDE_RUNTIME_ROOT / "scratch") + '","tools":[],"mcp_servers":[]}\n'
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}\n'
            '{"type":"result","subtype":"success","is_error":false,"result":"hi","usage":{"input_tokens":3,"output_tokens":1},"permission_denials":[]}\n'
        ).encode())
        stdout.feed_eof()
        stderr = asyncio.StreamReader()
        stderr.feed_eof()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): pass
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock(return_value=0)
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()),
            self.assertLogs("ai.runtime.claude_runtime", level="INFO") as captured,
        ):
            self.assertEqual([token async for token in runtime.stream(request)], ["hi"])
        self.assertIn("input_tokens=3", "\n".join(captured.output))
        self.assertIn("output_tokens=1", "\n".join(captured.output))

    async def test_claude_result_must_match_streamed_text(self):
        runtime = ClaudeCliRuntime()
        stdout = asyncio.StreamReader()
        stdout.feed_data((
            '{"type":"system","subtype":"init","cwd":"' + str(CLAUDE_RUNTIME_ROOT / "scratch") + '","tools":[],"mcp_servers":[]}\n'
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}\n'
            '{"type":"result","subtype":"success","is_error":false,"result":"missing","usage":{"input_tokens":3,"output_tokens":1},"permission_denials":[]}\n'
        ).encode())
        stdout.feed_eof()
        stderr = asyncio.StreamReader()
        stderr.feed_eof()

        class FakeStdin:
            def write(self, _value): pass
            async def drain(self): pass
            def close(self): pass

        process = Mock(pid=12345, returncode=None, stdin=FakeStdin(), stdout=stdout, stderr=stderr)
        process.wait = AsyncMock(return_value=0)
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="claude-sonnet-4-6", candidate_index=0)
        with (
            patch.object(runtime, "verify_compatibility", new=AsyncMock(return_value="2.1.195 (Claude Code)")),
            patch("ai.runtime.claude_runtime.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)),
            patch("ai.runtime.claude_runtime.reap_process_group", new=AsyncMock()),
        ):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                async for _ in runtime.stream(request):
                    pass
        self.assertEqual(ctx.exception.code, ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION)

    async def test_claude_rejects_unpinned_model_before_starting_runtime(self):
        runtime = ClaudeCliRuntime()
        request = GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="sonnet", candidate_index=0)
        with patch.object(runtime, "verify_compatibility", new=AsyncMock()) as compatibility_check:
            with self.assertRaises(ProviderRuntimeError) as ctx:
                async for _ in runtime.stream(request):
                    pass
        self.assertEqual(ctx.exception.code, ProviderErrorCode.MODEL_UNAVAILABLE)
        compatibility_check.assert_not_awaited()

    async def test_claude_logout_race_raises_dedicated_active_error(self):
        mocked_runtime = Mock()
        mocked_runtime.auth_change_guard = _busy_async_gate
        session = claude_auth._ClaudeAuthSession(mocked_runtime)
        with self.assertRaises(ClaudeGenerationActiveError):
            await session.logout()

    async def test_claude_logout_failure_is_not_reported_as_disconnected(self):
        mocked_runtime = Mock()
        mocked_runtime.has_active_generations = False
        mocked_runtime.auth_change_guard = _no_op_async_gate
        session = claude_auth._ClaudeAuthSession(mocked_runtime)
        with patch("ai.auth.claude_auth._run_auth_command", new=AsyncMock(return_value=(1, ""))):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                await session.logout()
        self.assertEqual(ctx.exception.code, ProviderErrorCode.PROVIDER_BAD_GATEWAY)

    async def test_claude_pinned_models_are_listed_after_compatibility_check(self):
        provider = ClaudeCliProvider()
        with patch("ai.providers.claude_cli.runtime.verify_compatibility", new=AsyncMock()):
            self.assertEqual(await provider.list_models(), [
                "claude-sonnet-4-6",
                "claude-opus-4-8",
                "claude-haiku-4-5-20251001",
            ])

    async def test_process_group_is_reaped(self):
        process = await asyncio.create_subprocess_exec("sh", "-c", "sleep 30", start_new_session=True)
        await reap_process_group(process, 1)
        self.assertIsNotNone(process.returncode)

    async def test_process_group_escalates_to_sigkill_and_is_reaped(self):
        process = await asyncio.create_subprocess_exec(
            "sh", "-c", "trap '' TERM; echo ready; while :; do sleep 1; done",
            stdout=asyncio.subprocess.PIPE, start_new_session=True,
        )
        assert process.stdout
        self.assertEqual(await process.stdout.readline(), b"ready\n")
        await reap_process_group(process, 0.01)
        self.assertEqual(process.returncode, -9)

    async def test_runtime_stderr_never_logs_raw_content(self):
        stream = asyncio.StreamReader()
        stream.feed_data(b"prompt oauth-code sk-secret-token\n")
        stream.feed_eof()
        with self.assertLogs("ai.runtime.util", level="WARNING") as captured:
            await drain_stderr(stream, "claude")
        self.assertNotIn("oauth-code", "\n".join(captured.output))
        self.assertIn("[redacted]", "\n".join(captured.output))
