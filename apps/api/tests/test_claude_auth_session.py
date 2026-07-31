import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from ai.auth import claude_auth
from ai.auth.claude_auth import ClaudeGenerationActiveError
from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError
from ai.runtime.util import GenerationGate, GenerationGateBusyError
from ai.specs import ProviderName


def _fake_process(returncode=None):
    stdout = asyncio.StreamReader()
    process = Mock(pid=1111, returncode=returncode, stdout=stdout)
    process.wait = AsyncMock(return_value=0)
    return process


def _no_op_status() -> claude_auth._CliAuthStatus:
    return claude_auth._CliAuthStatus(connected=False, account_label=None, plan=None)


@asynccontextmanager
async def _no_op_async_gate():
    yield


@asynccontextmanager
async def _busy_async_gate():
    raise GenerationGateBusyError("a generation is currently active")
    yield


def _mock_runtime(has_active_generations: bool) -> Mock:
    runtime = Mock(has_active_generations=has_active_generations)
    runtime.auth_change_guard = _busy_async_gate if has_active_generations else _no_op_async_gate
    return runtime


class ClaudeAuthSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_dict_mutation_does_not_affect_internal_state(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=_no_op_status())):
            first = await session.status()
            first["status"] = "connected"
            first["accountLabel"] = "hacked"
            second = await session.status()
        self.assertEqual(second["status"], "disconnected")
        self.assertIsNone(second["accountLabel"])

    async def test_concurrent_login_requests_reuse_one_attempt(self):
        mocked_runtime = Mock(has_active_generations=False)
        mocked_runtime.verify_compatibility = AsyncMock(return_value="v")
        session = claude_auth._ClaudeAuthSession(mocked_runtime)

        stdout = asyncio.StreamReader()
        stdout.feed_data(b"https://example.com/auth\n")
        process = Mock(pid=1111, returncode=None, stdout=stdout)

        async def _never_exits():
            await asyncio.sleep(3600)

        process.wait = AsyncMock(side_effect=_never_exits)

        with (
            patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=_no_op_status())),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as create_subprocess,
        ):
            payload1, payload2 = await asyncio.gather(session.login(), session.login())

        self.assertEqual(payload1, payload2)
        self.assertEqual(payload1["verificationUrl"], "https://example.com/auth")
        create_subprocess.assert_awaited_once()
        session._attempt.watcher.cancel()

    async def test_stale_waiter_timeout_reaps_only_its_own_attempt(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        old_process = _fake_process()
        new_process = _fake_process()
        old_attempt = claude_auth._LoginAttempt(process=old_process, started_at=0, deadline=0)
        new_attempt = claude_auth._LoginAttempt(process=new_process, started_at=0, deadline=0)
        session._attempt = new_attempt

        with patch("ai.auth.claude_auth.reap_process_group", new=AsyncMock()) as reap:
            with self.assertRaises(ProviderTimeoutError):
                await session._wait_for_verification_url(old_attempt, deadline=time.monotonic() - 1)

        self.assertEqual(reap.await_count, 1)
        self.assertIs(reap.await_args.args[0], old_process)
        self.assertIs(session._attempt, new_attempt)

    async def test_stale_watcher_finally_does_not_clear_newer_attempt(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        old_process = _fake_process()
        old_attempt = claude_auth._LoginAttempt(process=old_process, started_at=0, deadline=time.monotonic() + 10)
        new_process = _fake_process()
        new_attempt = claude_auth._LoginAttempt(process=new_process, started_at=0, deadline=time.monotonic() + 10)
        session._attempt = new_attempt

        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=_no_op_status())):
            await session._monitor_login_attempt(old_attempt)

        self.assertIs(session._attempt, new_attempt)
        self.assertIsNotNone(old_attempt.outcome)
        self.assertTrue(old_attempt.ready.is_set())

    async def test_stale_attempt_state_never_touches_session_state(self):
        # 진행 중인 attempt의 state 변경은 session._state에 전혀 반영되지 않아야 한다 —
        # 오직 _finish_attempt()가 identity를 확인하고 commit할 때만 반영된다.
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        session._state = claude_auth._ClaudeLoginState(status="disconnected")
        stale_process = _fake_process()
        stale_attempt = claude_auth._LoginAttempt(process=stale_process, started_at=0, deadline=time.monotonic() + 10)
        current_process = _fake_process()
        current_attempt = claude_auth._LoginAttempt(process=current_process, started_at=0, deadline=time.monotonic() + 10)
        session._attempt = current_attempt

        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=claude_auth._CliAuthStatus(connected=True, account_label="stale@x.com", plan="pro"))):
            await session._monitor_login_attempt(stale_attempt)

        # stale_attempt 자기 자신의 state는 connected로 바뀌어도 되지만,
        self.assertEqual(stale_attempt.state.status, "connected")
        # session의 상태/현재 attempt는 전혀 영향받지 않는다.
        self.assertEqual(session._state.status, "disconnected")
        self.assertIs(session._attempt, current_attempt)
        self.assertEqual(session._current_state, current_attempt.state)

    async def test_watcher_cancels_and_awaits_stdout_task(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        process = _fake_process()
        attempt = claude_auth._LoginAttempt(process=process, started_at=0, deadline=time.monotonic() + 10)
        session._attempt = attempt

        created_tasks = []
        real_create_task = asyncio.create_task

        def spy_create_task(coro, *args, **kwargs):
            task = real_create_task(coro, *args, **kwargs)
            created_tasks.append(task)
            return task

        with (
            patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=claude_auth._CliAuthStatus(connected=True, account_label="a@b.com", plan="pro"))),
            patch("asyncio.create_task", side_effect=spy_create_task),
        ):
            await session._monitor_login_attempt(attempt)

        stdout_task = created_tasks[0]
        self.assertTrue(stdout_task.done())

    async def test_watcher_provider_error_does_not_leak_as_unhandled_task_exception(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        process = _fake_process()
        attempt = claude_auth._LoginAttempt(process=process, started_at=0, deadline=time.monotonic() + 10)
        session._attempt = attempt

        error = ProviderRuntimeError(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "boom", ProviderName.CLAUDE_CLI)
        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(side_effect=error)):
            task = asyncio.create_task(session._monitor_login_attempt(attempt))
            await task

        self.assertIsNone(task.exception())
        self.assertEqual(session._state.status, "error")

    async def test_shutdown_is_safe_to_call_repeatedly(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        await session.shutdown()
        await session.shutdown()

        process = _fake_process()
        attempt = claude_auth._LoginAttempt(process=process, started_at=0, deadline=time.monotonic() + 10)
        attempt.watcher = asyncio.create_task(asyncio.sleep(3600))
        session._attempt = attempt
        with patch("ai.auth.claude_auth.reap_process_group", new=AsyncMock()):
            await session.shutdown()
            await session.shutdown()
        self.assertIsNone(session._attempt)

    async def test_logout_failure_does_not_change_state_to_disconnected(self):
        session = claude_auth._ClaudeAuthSession(_mock_runtime(has_active_generations=False))
        session._state = claude_auth._ClaudeLoginState(status="connected", account_label="a@b.com")
        with patch("ai.auth.claude_auth._run_auth_command", new=AsyncMock(return_value=(1, ""))):
            with self.assertRaises(ProviderRuntimeError):
                await session.logout()
        self.assertEqual(session._state.status, "connected")

    async def test_status_keys_are_camel_case(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=_no_op_status())):
            result = await session.status()
        self.assertEqual(set(result.keys()), {"status", "verificationUrl", "userCode", "accountLabel", "errorCode"})

    async def test_wait_for_verification_url_returns_own_attempts_outcome_not_session_state(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        old_process = _fake_process()
        old_attempt = claude_auth._LoginAttempt(process=old_process, started_at=0, deadline=time.monotonic() + 10)
        old_attempt.outcome = claude_auth._ClaudeLoginState(status="login_pending", verification_url="https://old.example/auth")
        old_attempt.ready.set()

        # 세션은 이미 다른(새) attempt를 거쳐 완전히 다른 상태로 넘어간 상태를 흉내낸다.
        session._state = claude_auth._ClaudeLoginState(status="connected", account_label="new@x.com")
        session._attempt = None

        result = await session._wait_for_verification_url(old_attempt, deadline=time.monotonic() + 10)

        self.assertEqual(result["verificationUrl"], "https://old.example/auth")
        self.assertEqual(result["status"], "login_pending")

    async def test_attempt_outcome_is_write_once_after_verification_url_found(self):
        session = claude_auth._ClaudeAuthSession(Mock(has_active_generations=False))
        process = _fake_process()
        attempt = claude_auth._LoginAttempt(process=process, started_at=0, deadline=time.monotonic() + 10)
        session._attempt = attempt
        attempt.outcome = claude_auth._ClaudeLoginState(status="login_pending", verification_url="https://x.example/auth")

        with patch("ai.auth.claude_auth._CliAuthStatus.query", new=AsyncMock(return_value=_no_op_status())):
            await session._monitor_login_attempt(attempt)

        self.assertEqual(attempt.outcome.verification_url, "https://x.example/auth")
        self.assertEqual(session._state.status, "error")

    async def test_logout_race_raises_dedicated_active_error(self):
        session = claude_auth._ClaudeAuthSession(_mock_runtime(has_active_generations=True))
        with self.assertRaises(ClaudeGenerationActiveError):
            await session.logout()

    async def test_logout_is_rejected_while_a_real_generation_is_running(self):
        gate = GenerationGate(limit=1)
        mocked_runtime = Mock(has_active_generations=False)
        mocked_runtime.auth_change_guard = gate.try_exclusive
        session = claude_auth._ClaudeAuthSession(mocked_runtime)

        async def fake_generation() -> None:
            async with gate.acquire():
                await asyncio.sleep(0.05)

        generation_task = asyncio.create_task(fake_generation())
        await asyncio.sleep(0)

        with self.assertRaises(ClaudeGenerationActiveError):
            await session.logout()

        await generation_task

    async def test_generation_waits_for_an_in_progress_logout(self):
        gate = GenerationGate(limit=1)
        mocked_runtime = Mock(has_active_generations=False)
        mocked_runtime.auth_change_guard = gate.try_exclusive
        session = claude_auth._ClaudeAuthSession(mocked_runtime)

        release_logout = asyncio.Event()

        async def slow_logout_command(*args, **kwargs) -> tuple[int, str]:
            await release_logout.wait()
            return (0, "")

        generation_acquired = asyncio.Event()

        async def fake_generation() -> None:
            async with gate.acquire():
                generation_acquired.set()

        with patch("ai.auth.claude_auth._run_auth_command", new=AsyncMock(side_effect=slow_logout_command)):
            logout_task = asyncio.create_task(session.logout())
            await asyncio.sleep(0)

            generation_task = asyncio.create_task(fake_generation())
            await asyncio.sleep(0.01)
            self.assertFalse(generation_acquired.is_set())

            release_logout.set()
            await logout_task
            await generation_task

        self.assertTrue(generation_acquired.is_set())

    async def test_try_exclusive_fails_immediately_when_generation_is_active(self):
        gate = GenerationGate(limit=1)

        async def fake_generation():
            async with gate.acquire():
                await asyncio.sleep(0.05)

        gen_task = asyncio.create_task(fake_generation())
        await asyncio.sleep(0)  # generation이 permit을 잡을 시간을 준다
        self.assertTrue(gate.has_active)

        with self.assertRaises(GenerationGateBusyError):
            async with gate.try_exclusive():
                pass

        # 실패했다고 진행 중이던 generation을 건드리면 안 된다 — 여전히 살아있어야 한다.
        self.assertTrue(gate.has_active)
        await gen_task
        self.assertFalse(gate.has_active)

    async def test_try_exclusive_succeeds_once_no_generation_is_active(self):
        gate = GenerationGate(limit=1)
        async with gate.try_exclusive():
            self.assertFalse(gate.has_active)

        # try_exclusive를 뜨면 permit을 반납해서 다음 generation이 다시 들어올 수 있어야 한다.
        async with gate.acquire():
            self.assertTrue(gate.has_active)


if __name__ == "__main__":
    unittest.main()
