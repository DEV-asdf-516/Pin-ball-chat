import asyncio
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError
from ai.auth.codex_auth import CodexAuthSession, shutdown_codex
from ai.runtime.codex_runtime import CodexAppServer, _RUNTIME_ROOT
from ai.specs import GenerateRequest, Message


async def _hang(*_args, **_kwargs) -> dict:
    await asyncio.sleep(10)
    return {}


def _thread_start_response(**overrides) -> dict:
    response = {
        "thread": {"id": "thread-1", "ephemeral": True},
        "cwd": str(_RUNTIME_ROOT / "scratch"),
        "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
        "instructionSources": [], "model": "model-1",
    }
    response.update(overrides)
    return response


class CodexCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("PINBALLCHAT_RUNTIME_ROOT")
        os.environ["PINBALLCHAT_RUNTIME_ROOT"] = self.temp_dir.name

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("PINBALLCHAT_RUNTIME_ROOT", None)
        else:
            os.environ["PINBALLCHAT_RUNTIME_ROOT"] = self.old_root
        self.temp_dir.cleanup()

    @staticmethod
    def _request() -> GenerateRequest:
        return GenerateRequest(system="system", messages=[Message(role="user", content="hello")], model="model-1", candidate_index=0)

    # ------------------------------------------------------------------
    # 1. thread cleanup failure paths
    # ------------------------------------------------------------------

    async def test_thread_start_ephemeral_not_bool_schedules_cleanup_then_raises(self):
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return {"thread": {"id": "thread-1", "ephemeral": "not-a-bool"}}
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()) as cleanup,
        ):
            with self.assertRaisesRegex(ProviderRuntimeError, "no ephemeral state"):
                async for _ in app_server.stream(self._request()):
                    pass
        cleanup.assert_called_once_with("thread-1", True)

    async def test_thread_start_invalid_thread_id_skips_cleanup(self):
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return {"thread": {"ephemeral": True}}
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()) as cleanup,
        ):
            with self.assertRaisesRegex(ProviderRuntimeError, "no thread ID"):
                async for _ in app_server.stream(self._request()):
                    pass
        cleanup.assert_not_called()

    async def test_turn_start_exception_schedules_cleanup_with_correct_persisted(self):
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return _thread_start_response(thread={"id": "thread-1", "ephemeral": True})
            if method == "turn/start":
                raise ProviderRuntimeError(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "boom", provider="openai_codex")
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()) as cleanup,
        ):
            with self.assertRaisesRegex(ProviderRuntimeError, "boom"):
                async for _ in app_server.stream(self._request()):
                    pass
        # ephemeral True in thread/start response => persisted is False
        cleanup.assert_called_once_with("thread-1", False)

    async def test_turn_start_malformed_response_schedules_cleanup_with_correct_persisted(self):
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return _thread_start_response(thread={"id": "thread-1", "ephemeral": False})
            if method == "turn/start":
                return {"turn": {"id": None, "items": [], "status": "inProgress"}}
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()) as cleanup,
        ):
            with self.assertRaisesRegex(ProviderRuntimeError, "no turn ID"):
                async for _ in app_server.stream(self._request()):
                    pass
        # ephemeral False in thread/start response => persisted is True
        cleanup.assert_called_once_with("thread-1", True)

    # ------------------------------------------------------------------
    # 2. login completion race
    # ------------------------------------------------------------------

    async def test_login_completion_race_does_not_overwrite_arrived_state(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)

        async def request_rpc(method, params, *_args, **_kwargs):
            if method == "account/login/start":
                # 실제 reader가 account/login/completed를 먼저 처리한 상황을 흉내낸다.
                session._login_state = {"status": "connected", "verificationUrl": None, "userCode": None, "errorCode": None}
                return {"type": "chatgptDeviceCode", "loginId": "login-1", "verificationUrl": "https://example.com", "userCode": "ABCD"}
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
        ):
            result = await session._login()

        self.assertEqual(result, {"status": "connected", "verificationUrl": None, "userCode": None, "errorCode": None})
        self.assertIsNone(session._login_timeout_task)

    # ------------------------------------------------------------------
    # 3. logout cancel semantics
    # ------------------------------------------------------------------

    async def test_logout_timeout_terminates_runtime_with_interrupt_phase(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_request", new=AsyncMock(side_effect=_hang)),
            patch.object(app_server, "_terminate_runtime", new=AsyncMock()) as terminate,
            patch("ai.auth.codex_auth.RUNTIME_INTERRUPT_GRACE_SECONDS", 0.01),
        ):
            with self.assertRaises(ProviderTimeoutError) as ctx:
                await session._logout()

        self.assertEqual(ctx.exception.phase, "interrupt")
        terminate.assert_awaited()

    # ------------------------------------------------------------------
    # 4. shutdown order
    # ------------------------------------------------------------------

    async def test_shutdown_order_terminate_then_tasks_then_login_timeout(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)
        order: list[str] = []

        async def fake_terminate_runtime(error=None):
            order.append("terminate")

        async def sleep_forever(label: str):
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                order.append(label)
                raise

        app_server._reader_task = asyncio.create_task(sleep_forever("reader_cancelled"))
        app_server._stderr_task = asyncio.create_task(sleep_forever("stderr_cancelled"))
        session._login_timeout_task = asyncio.create_task(sleep_forever("login_timeout_cancelled"))
        # 태스크들이 asyncio.sleep(100)에 실제로 진입한 뒤에 cancel()해야 except 절이
        # 실행된다 — 스케줄되기 전에 cancel()하면 코루틴 본문이 아예 실행되지 않는다.
        await asyncio.sleep(0)

        with (
            patch.object(app_server, "_terminate_runtime", new=AsyncMock(side_effect=fake_terminate_runtime)),
            patch("ai.auth.codex_auth.codex_runtime", app_server),
            patch("ai.auth.codex_auth.session", session),
        ):
            await shutdown_codex()

        self.assertEqual(order[0], "terminate")
        self.assertEqual(set(order[1:3]), {"reader_cancelled", "stderr_cancelled"})
        self.assertEqual(order[3], "login_timeout_cancelled")

    # ------------------------------------------------------------------
    # 5. error surface snapshot
    # ------------------------------------------------------------------

    async def _drive_event_to_error(self, event: dict) -> ProviderRuntimeError:
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return _thread_start_response()
            if method == "turn/start":
                return {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}
            raise AssertionError(method)

        with ExitStack() as stack:
            stack.enter_context(patch.object(app_server, "_start", new=AsyncMock()))
            stack.enter_context(patch.object(app_server, "_timed_request", side_effect=request_rpc))
            stack.enter_context(patch.object(app_server, "_interrupt", new=AsyncMock()))
            stack.enter_context(patch.object(app_server, "_schedule_thread_cleanup", new=Mock()))

            stream = app_server.stream(self._request())
            task = asyncio.create_task(anext(stream))
            for _ in range(100):
                if "turn-1" in app_server._turn_routes:
                    break
                await asyncio.sleep(0)
            self.assertIn("turn-1", app_server._turn_routes)
            route = app_server._turn_routes["turn-1"]
            await route.queue.try_put(event)
            with self.assertRaises(ProviderRuntimeError) as ctx:
                await task
            await stream.aclose()
            return ctx.exception

    @staticmethod
    def _error_tuple(exc: ProviderRuntimeError) -> tuple:
        return (exc.code, str(exc), exc.retryable, exc.phase)

    async def test_error_surface_snapshot_malformed_agent_message_delta(self):
        exc = await self._drive_event_to_error(
            {"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1"}}
        )
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed agent message delta", False, None),
        )

    async def test_error_surface_snapshot_malformed_item_event(self):
        exc = await self._drive_event_to_error({"method": "item/started", "params": {"item": {"type": 1}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed item event", False, None),
        )

    async def test_error_surface_snapshot_prohibited_item_type(self):
        exc = await self._drive_event_to_error({"method": "item/started", "params": {"item": {"type": "commandExecution"}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex attempted a prohibited tool action", False, None),
        )

    async def test_error_surface_snapshot_unknown_item_type(self):
        exc = await self._drive_event_to_error({"method": "item/started", "params": {"item": {"type": "mysteryType"}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted an unknown item type", False, None),
        )

    async def test_error_surface_snapshot_prohibited_turn_method(self):
        exc = await self._drive_event_to_error({"method": "item/tool/call", "params": {}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex attempted a prohibited tool action", False, None),
        )

    async def test_error_surface_snapshot_malformed_turn_completion(self):
        exc = await self._drive_event_to_error({"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed turn completion", False, None),
        )

    async def test_error_surface_snapshot_interrupted_status(self):
        exc = await self._drive_event_to_error({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "interrupted"}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_BAD_GATEWAY, "Codex generation was interrupted", False, None),
        )

    async def test_error_surface_snapshot_failed_status_with_known_rule(self):
        exc = await self._drive_event_to_error({
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-1", "status": "failed", "error": {"code": "quota_exhausted"}}},
        })
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_QUOTA_EXHAUSTED, "ChatGPT usage limit has been reached", True, None),
        )

    async def test_error_surface_snapshot_failed_status_fallback(self):
        exc = await self._drive_event_to_error({
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-1", "status": "failed", "error": {"code": "something_unrecognized"}}},
        })
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_BAD_GATEWAY, "codex runtime rejected the request", True, None),
        )

    async def test_error_surface_snapshot_invalid_status(self):
        exc = await self._drive_event_to_error({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "weird"}}})
        self.assertEqual(
            self._error_tuple(exc),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "Codex turn completed with an invalid status", False, None),
        )

    async def test_error_surface_snapshot_secure_thread_contract_violation(self):
        app_server = CodexAppServer()

        async def request_rpc(method, params, *_args):
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            if method == "thread/start":
                return _thread_start_response(model="a-different-model")
            raise AssertionError(method)

        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", side_effect=request_rpc),
            patch.object(app_server, "_schedule_thread_cleanup", new=Mock()),
        ):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                async for _ in app_server.stream(self._request()):
                    pass
        self.assertEqual(
            self._error_tuple(ctx.exception),
            (ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex did not apply the required isolated runtime policy", False, None),
        )

    async def test_error_surface_snapshot_model_list_malformed_data(self):
        app_server = CodexAppServer()
        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", new=AsyncMock(return_value={"data": "not-a-list"})),
        ):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                await app_server.list_models()
        self.assertEqual(
            self._error_tuple(ctx.exception),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed model list", False, None),
        )

    async def test_error_surface_snapshot_model_list_malformed_cursor(self):
        app_server = CodexAppServer()
        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", new=AsyncMock(return_value={"data": [], "nextCursor": 123})),
        ):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                await app_server.list_models()
        self.assertEqual(
            self._error_tuple(ctx.exception),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed model cursor", False, None),
        )

    async def test_error_surface_snapshot_device_login_malformed(self):
        app_server = CodexAppServer()
        session = CodexAuthSession(app_server)
        with (
            patch.object(app_server, "_start", new=AsyncMock()),
            patch.object(app_server, "_timed_request", new=AsyncMock(return_value={"type": "chatgptDeviceCode"})),
        ):
            with self.assertRaises(ProviderRuntimeError) as ctx:
                await session._login()
        self.assertEqual(
            self._error_tuple(ctx.exception),
            (ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed device login response", False, None),
        )


if __name__ == "__main__":
    unittest.main()
