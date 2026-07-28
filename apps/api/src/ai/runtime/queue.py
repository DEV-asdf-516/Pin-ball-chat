import asyncio
from collections import deque
from typing import Generic, TypeVar

_T = TypeVar("_T")
_NO_ITEM = object()


class RuntimeQueueBlockedError(Exception):
    # 큐가 가득 찬 채로 block_seconds가 지나도록 자리가 나지 않았다. 기존 item은
    # 밀어내지 않았다 — 호출자가 상위 타임아웃/에러로 번역할 책임을 진다.
    pass


class RuntimeQueueClosed(Exception):
    # 큐가 close() 또는 fail()로 전환됐다. fail()이 저장한 에러가 있으면 get()은
    # 이 예외 대신 그 에러를 raise한다 — 이 예외는 "정상 종료"만 의미한다.
    pass


class BoundedRuntimeQueue(Generic[_T]):
    # provider/process/turn/에러코드를 전혀 모르는 순수 자료구조.
    # OPEN → (close 또는 fail로) CLOSED 의 단방향 상태 전이만 가진다.
    def __init__(self, maxsize: int, block_seconds: float):
        if maxsize < 1:
            raise ValueError(f"BoundedRuntimeQueue maxsize must be >= 1, got {maxsize}")
        self._maxsize = maxsize
        self._block_seconds = block_seconds
        self._deque: deque[_T] = deque()
        self._condition = asyncio.Condition()
        self._closed = False
        self._error: BaseException | None = None

    async def put(self, item: _T) -> None:
        async with self._condition:
            if self._closed:
                raise RuntimeQueueClosed()
            if len(self._deque) >= self._maxsize:
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(lambda: self._closed or len(self._deque) < self._maxsize),
                        timeout=self._block_seconds,
                    )
                except TimeoutError:
                    raise RuntimeQueueBlockedError()
                if self._closed:
                    raise RuntimeQueueClosed()
            self._deque.append(item)
            self._condition.notify_all()

    async def try_put(self, item: _T) -> bool:
        async with self._condition:
            if self._closed:
                raise RuntimeQueueClosed()
            if len(self._deque) >= self._maxsize:
                return False
            self._deque.append(item)
            self._condition.notify_all()
            return True

    async def get(self, timeout: float) -> _T:
        async with self._condition:
            item = self._take_ready()
            if item is not _NO_ITEM:
                return item
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._error is not None or self._deque or self._closed),
                    timeout=timeout,
                )
            except TimeoutError:
                raise TimeoutError()
            item = self._take_ready()
            if item is not _NO_ITEM:
                return item
            raise RuntimeQueueClosed()

    def _take_ready(self):
        # 호출자가 이미 condition lock을 쥐고 있다고 가정한다. 
        # 우선순위:
        # ① error 있으면 즉시 raise 
        # ② item 있으면 FIFO 반환 
        # ③ 그 외 미해결 신호(_NO_ITEM).
        if self._error is not None:
            raise self._error
        if self._deque:
            item = self._deque.popleft()
            self._condition.notify_all()
            return item
        return _NO_ITEM

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def fail(self, error: BaseException) -> None:
        async with self._condition:
            self._error = error
            self._closed = True
            self._deque.clear()
            self._condition.notify_all()
