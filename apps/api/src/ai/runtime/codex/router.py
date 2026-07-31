import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

from ai.errors import ProviderErrorCode, ProviderRuntimeError, runtime_error_factory
from ai.runtime.queue import BoundedRuntimeQueue, RuntimeQueueClosed
from ai.settings import RUNTIME_QUEUE_BLOCK_SECONDS, RUNTIME_QUEUE_SIZE
from ai.specs import ProviderName
from util.safe_util import get_safe_dict


log = logging.getLogger(__name__)

_TURN_TOMBSTONE_MAXLEN = 256

_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)


def _queue_overflow_error() -> ProviderRuntimeError:
    return _runtime_error(
        ProviderErrorCode.PROVIDER_TIMEOUT, 
        "Codex event queue was blocked", 
        retryable=True, 
        phase="idle"
    )

"""
Codex event 도착
       │
       ├─ 활성 route 있음
       │      └─ 해당 queue에 전달
       │
       ├─ route 생성 전
       │      └─ early buffer에 임시 저장
       │
       ├─ 이미 끝난 turn
       │      └─ late event 무시
       │
       └─ turn ID 없음
              └─ 관련 없는 notification으로 무시
"""

@dataclass
class _TurnRoute:
    queue: BoundedRuntimeQueue
    terminal_seen: bool = False
    consumer_done: bool = False

    @property
    def is_finished(self) -> bool:
        return self.terminal_seen and self.consumer_done


class CodexTurnRouter:
    # turn queue, early event, tombstone, route 수명주기 전담. process도 connection도 모른다.
    def __init__(self):
        self._turn_routes: dict[str, _TurnRoute] = {}
        self._turn_tombstones: OrderedDict[str, None] = OrderedDict()
        self._early_turn_events: dict[str, list[dict]] = {}

    def _tombstone_turn(self, turn_id: str) -> None:
        self._turn_tombstones[turn_id] = None
        self._turn_tombstones.move_to_end(turn_id)

        while len(self._turn_tombstones) > _TURN_TOMBSTONE_MAXLEN:
            self._turn_tombstones.popitem(last=False)

    def _retire_route_if_finished(self, turn_id: str) -> None:
        route:_TurnRoute = self._turn_routes.get(turn_id)
        
        if route and route.is_finished:
            del self._turn_routes[turn_id]
            self._tombstone_turn(turn_id)

    async def attach_turn(self, turn_id: str) -> tuple[BoundedRuntimeQueue, ProviderRuntimeError | None]:
        queue: BoundedRuntimeQueue = BoundedRuntimeQueue(
            maxsize=RUNTIME_QUEUE_SIZE, 
            block_seconds=RUNTIME_QUEUE_BLOCK_SECONDS
        )
        route:_TurnRoute = _TurnRoute(queue=queue)

        self._turn_routes[turn_id] = route
        
        for event in self._early_turn_events.pop(turn_id, []):
            accepted: bool = await queue.try_put(event)
            if not accepted:
                return queue, _queue_overflow_error()
        
        return queue, None

    async def route_event(self, event: dict) -> None:
        method: str | None = event.get("method")
        params: dict = event.get("params", {})
        completed_turn: dict = get_safe_dict(params, "turn")
        turn_id: str | None = params.get("turnId") or completed_turn.get("id")

        if not isinstance(turn_id, str):
            log.debug("ignored Codex notification method=%s", str(method)[:120])
            return None

        route: _TurnRoute | None = self._turn_routes.get(turn_id)

        if route is None:
            if turn_id in self._turn_tombstones:
                # 이미 종료 처리된 turn의 late event 재버퍼링하지 않고 무시.
                log.debug(
                    "ignoring late Codex event for tombstoned turn=%s method=%s", 
                    turn_id, 
                    str(method)[:120]
                )
                return None

            buffered: list[dict] = self._early_turn_events.setdefault(turn_id, [])
            buffered_count: int = sum(len(events) for events in self._early_turn_events.values())
            
            if buffered_count >= RUNTIME_QUEUE_SIZE:
                raise _queue_overflow_error()

            buffered.append(event)
            return None

        try:
            accepted: bool = await route.queue.try_put(event)
        except RuntimeQueueClosed:
            # 이미 닫힌 route로 늦게 도착한 이벤트 — 무해하게 무시하고 라우팅 계속.
            return None

        if not accepted:
            # blocking put() 금지 정책상 overflow는 turn 격리로 못 막음. runtime 전체를 종료한다.
            error: ProviderRuntimeError = _queue_overflow_error()
            await route.queue.fail(error)
            raise error

        if method == "turn/completed":
            route.terminal_seen = True
            await route.queue.close()
            self._retire_route_if_finished(turn_id)

        return None

    def mark_consumer_finished(self, turn_id: str) -> None:
        route: _TurnRoute | None = self._turn_routes.get(turn_id)
        if route:
            route.consumer_done = True
        self._retire_route_if_finished(turn_id)

    async def abort_all(self, error: ProviderRuntimeError) -> None:
        # 크래시 후에는 consumer가 CONSUMER_DONE에 도달하길 기다릴 이유가 없어 route도 즉시 정리한다.
        for turn_id, route in list(self._turn_routes.items()):
            await route.queue.fail(error)
            del self._turn_routes[turn_id]
            self._tombstone_turn(turn_id)
        
        self._early_turn_events.clear()
