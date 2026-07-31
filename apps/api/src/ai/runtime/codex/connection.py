import asyncio
import json
import logging
from typing import Awaitable, Callable

from ai.errors import ProviderErrorCode, ProviderRuntimeError, runtime_error_factory
from ai.protocol.codex_protocol import classify_event_error, is_prohibited_server_request
from ai.runtime.util import decode_runtime_message
from ai.specs import ProviderName


log = logging.getLogger(__name__)

_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)

FailureHandler = Callable[["asyncio.subprocess.Process", int, ProviderRuntimeError], Awaitable[None]]
NotificationHandler = Callable[["asyncio.subprocess.Process", int, dict], Awaitable[bool]]


class CodexRpcConnection:

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._epoch: int = 0
        self._next_id: int = 1
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._ignored_response_ids: set[int] = set()
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._reader_tasks: set[asyncio.Task] = set()
        self._on_notification: NotificationHandler | None = None
        self._on_failure: FailureHandler | None = None

    @property
    def is_bound(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _is_current(self, process: "asyncio.subprocess.Process", epoch: int) -> bool:
        return self._process is process and self._epoch == epoch

    def bind(
        self, 
        process: "asyncio.subprocess.Process", 
        on_notification: NotificationHandler, 
        on_failure: FailureHandler
    ) -> int:
        self._process = process
        self._epoch += 1
        epoch: int = self._epoch
        self._on_notification = on_notification
        self._on_failure = on_failure
        task: asyncio.Task = asyncio.create_task(self._read_events(process, epoch))
        self._reader_tasks.add(task)
        task.add_done_callback(self._reader_tasks.discard)
        return epoch

    async def _report_failure(self, process: "asyncio.subprocess.Process", epoch: int, error: ProviderRuntimeError) -> None:
        if not self._is_current(process, epoch):
            return
        if self._on_failure:
            await self._on_failure(process, epoch, error)

    async def _read_events(self, process: "asyncio.subprocess.Process", epoch: int) -> None:
        reached_eof: bool = False
        try:
            assert process.stdout
            
            while line := await process.stdout.readline():
                if not self._is_current(process, epoch):
                    return
                try:
                    event: dict = decode_runtime_message(
                        line,
                        runtime_name="codex",
                        non_dict_message="codex runtime emitted a malformed message",
                        make_error=_runtime_error,
                    )
                except ProviderRuntimeError as decode_error:
                    await self._report_failure(process, epoch, decode_error)
                    return

                match event:
                    case {"id": _, "method": method}:
                        is_prohibited: bool = is_prohibited_server_request(method)
                        
                        code: ProviderErrorCode = ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION \
                            if is_prohibited else ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE
                        
                        message: str = "Codex attempted a prohibited tool action" \
                            if is_prohibited else "codex runtime emitted an unsupported server request"
                        
                        await self._report_failure(process, epoch, _runtime_error(code, message))
                        
                        return

                    case {"id": request_id}:
                        if request_id in self._ignored_response_ids:
                            self._ignored_response_ids.discard(request_id)
                            continue
                        
                        future: asyncio.Future | None = self._pending_requests.pop(request_id, None)
                        
                        if future is None:
                            await self._report_failure(process, epoch, 
                                _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                                "codex runtime returned an unknown response ID")
                            )
                            return

                        if future.cancelled():
                            continue
                        
                        if event.get("error"):
                            future.set_exception(classify_event_error(event))
                        elif isinstance(event.get("result"), dict):
                            future.set_result(event["result"])
                        else:
                            future.set_exception(_runtime_error(
                                ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                                "codex runtime returned malformed response"))

                    case {"method": str(), "params": dict()}:
                        if not self._on_notification:
                            continue
                        if not await self._on_notification(process, epoch, event):
                            return

                  
                    case _:
                        await self._report_failure(
                            process, epoch, _runtime_error(
                                ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                                "codex runtime emitted malformed notification"
                                )
                            )
                        return
            reached_eof = True
        except asyncio.CancelledError:
            raise
        finally:
            if self._is_current(process, epoch) and (reached_eof or process.returncode is not None):
                await self._report_failure(
                 process, epoch,
                 _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, 
                    "codex runtime exited unexpectedly", 
                    retryable=True
                   )
                )

    async def call(self, method: str, params: dict) -> dict:
        request_id: int | None = None
        try:
            async with self._write_lock:
                process: asyncio.subprocess.Process | None = self._process
                epoch: int = self._epoch
                
                is_usable: bool = (
                    self._is_current(process, epoch)
                    and process is not None
                    and process.returncode is None
                    and process.stdin is not None
                )
                if not is_usable:
                    raise _runtime_error(
                        ProviderErrorCode.PROVIDER_RUNTIME_CRASHED,
                        "codex runtime is not running",
                        retryable=True
                    )
                
                request_id = self._next_id
                self._next_id += 1
                loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
                future: asyncio.Future = loop.create_future()
                self._pending_requests[request_id] = future

                try:
                    process.stdin.write((
                    json.dumps({
                        "jsonrpc": "2.0", 
                        "id": request_id, 
                        "method": method, 
                        "params": params
                    }) + "\n").encode())
                    
                    await process.stdin.drain()
                
                except (BrokenPipeError, ConnectionResetError) as exc:
                    self._pending_requests.pop(request_id, None)
                    error: ProviderRuntimeError = _runtime_error(
                        ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, 
                        "codex runtime pipe closed", 
                        retryable=True
                    )
                    await self._report_failure(process, epoch, error)
                    raise error from exc

            # write lock은 여기서 이미 해제: response 대기는 concurrent request를 막지 않는다.
            return await future
        except asyncio.CancelledError:
            # drain 중 취소든 response 대기 중 취소든 같은 cleanup을 거친다
            if request_id is not None and self._pending_requests.pop(request_id, None) is not None:
                self._ignored_response_ids.add(request_id)
            raise

    def fail_pending(self, error: ProviderRuntimeError) -> None:
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(error)
        
        self._pending_requests.clear()

    async def close(self) -> None:
        # request ID는 epoch에 무관하게 단조 증가하므로 _ignored_response_ids는 여기서
        # 비우지 않아도 안전하다 — 재사용되지 않는 ID라 다음 세대와 충돌하지 않는다.
        tasks: list[asyncio.Task] = [task for task in self._reader_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
