import asyncio
import logging
import os
import signal
import stat
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Awaitable, Callable, Generic, TypeVar

from ai.settings import PINBALLCHAT_RUNTIME_ROOT

log = logging.getLogger(__name__)

_T = TypeVar("_T")

# runtime 자식 프로세스가 만드는 파일이 group/world에 노출되지 않게 하는 제한적 umask.
RUNTIME_UMASK = 0o077
RUNTIME_DIR_MODE = 0o700

def redacted(value: str) -> str:
    # 런타임 stderr에는 프롬프트, OAuth URL, 인증 코드, 자격증명 등이 미리 알 수 없는
    # 형식으로 섞여 나올 수 있다. 부분적인 패턴 매칭으로 걸러내려 하지 말 것.
    return "[redacted]" if value else ""


def runtime_env(home_name: str) -> dict[str, str]:
    # env var를 매번 다시 읽는다 — PINBALLCHAT_RUNTIME_ROOT는 import 시점에 고정돼 테스트의 임시 경로 지정을 못 따라간다.
    root = Path(os.environ.get("PINBALLCHAT_RUNTIME_ROOT") or PINBALLCHAT_RUNTIME_ROOT)
    home = root / home_name
    scratch = root / "scratch"
    
    for directory in (root, home, scratch):
        directory.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(directory.stat().st_mode)
        # 컨테이너 루트는 read-only다. 런타임 루트는 이미지에 0700으로 생성돼 있고,
        # credential/scratch 하위 마운트만 쓰기 가능하다.
        if mode != RUNTIME_DIR_MODE:
            directory.chmod(RUNTIME_DIR_MODE)
            mode = stat.S_IMODE(directory.stat().st_mode)
        
        if mode & RUNTIME_UMASK:
            raise PermissionError(f"runtime directory is not private: {directory.name}")
    
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR") if os.environ.get(key)}
    env["HOME"] = str(home)
    
    return env

# 고아 정리
async def reap_process_group(process: asyncio.subprocess.Process, grace_seconds: float) -> None:
    if process.returncode is not None:
        await process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def drain_stderr(stream: asyncio.StreamReader | None, provider: str) -> None:
    if not stream:
        return
    while line := await stream.readline():
        log.warning("%s runtime stderr: %s", provider, redacted(line.decode(errors="replace").strip()))


class GenerationGateBusyError(Exception):
    pass


class GenerationGate:
    # 동시성 제한용 세마포어와 active 카운터를 한 객체로 묶는다. 세마포어를 쥐고 있는
    # 구간과 active 카운터가 항상 정확히 일치하도록 보장하므로, `has_active`가
    # 세마포어 내부 카운터를 몰래 들여다볼 필요가 없다.
    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError(f"GenerationGate limit must be >= 1, got {limit}")
        self._limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._active = 0

    @property
    def has_active(self) -> bool:
        return self._active > 0

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[None, None]:
        async with self._semaphore:
            self._active += 1
            try:
                yield
            finally:
                self._active -= 1

    @asynccontextmanager
    async def try_exclusive(self) -> AsyncGenerator[None, None]:
        # busy면 기다리지 않고 바로 실패 — locked() 체크와 acquire() 사이엔 await가 없어 원자적이다.
        acquired = 0
        try:
            for _ in range(self._limit):
                if self._semaphore.locked():
                    raise GenerationGateBusyError("a generation is currently active")
                await self._semaphore.acquire()
                acquired += 1
            yield
        finally:
            for _ in range(acquired):
                self._semaphore.release()


class AsyncOnce(Generic[_T]):
    # 한 번 계산하면 그 뒤로는 계속 재사용해도 안전한 값 위한 double-checked-locking 캐시.
    def __init__(self):
        self._lock = asyncio.Lock()
        self._value: _T | None = None

    async def get(self, load: Callable[[], Awaitable[_T]]) -> _T:
        if self._value is not None:
            return self._value
        async with self._lock:
            if self._value is None:
                self._value = await load()
        return self._value


@dataclass(frozen=True)
class ProcessOutput:
    returncode: int
    stdout: bytes
    stderr: bytes


async def run_subprocess_capture(*command: str, env: dict[str, str], timeout: float, grace_seconds: float, cwd: str | None = None) -> ProcessOutput:
    # 소유권·종료 규칙이 provider마다 다른 장수/요청 단위 생성 프로세스는 여기서 다루지 않는다.
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
        umask=RUNTIME_UMASK,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (asyncio.CancelledError, TimeoutError):
        await reap_process_group(process, grace_seconds)
        raise
    assert process.returncode is not None
    return ProcessOutput(returncode=process.returncode, stdout=stdout, stderr=stderr)
