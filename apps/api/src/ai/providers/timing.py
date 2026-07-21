import functools
import logging
import os
import time
from typing import AsyncIterator, Callable, TypeVar

from ai.specs import GenerateRequest

_F = TypeVar("_F", bound=Callable[..., AsyncIterator[str]])


def log_stream_timing(fn: _F) -> _F:
    # 모든 provider의 stream()에 공통으로 붙는 타이밍 로거. 청크가 순수 str이라는 계약만으로
    # TTFT/총소요시간을 재기 때문에 provider 종류를 안 가린다. ollama의 prompt_eval/eval처럼
    # provider가 응답 안에 얹어 보내는 상세 통계는 이 데코레이터로는 볼 수 없으니 각자 내부에서 잰다.
    log = logging.getLogger(fn.__module__)
    if os.environ.get("AI_STREAM_DEBUG_TIMING"):
        log.setLevel(logging.DEBUG)

    @functools.wraps(fn)
    async def wrapper(self, req: GenerateRequest, *args, **kwargs):
        started: float = time.monotonic()
        first_token_at: float | None = None
        chars: int = 0
        completed: bool = False

        try:
            async for chunk in fn(self, req, *args, **kwargs):
                if first_token_at is None:
                    first_token_at = time.monotonic()
                    log.debug("%s ttft: model=%s ttft=%.2fs", self.name, req.model, first_token_at - started)
                chars += len(chunk)
                yield chunk
            completed = True
        finally:
            total: float = time.monotonic() - started
            log.debug(
                "%s stream %s: model=%s total=%.2fs chars=%d (~%.1f chars/s)",
                self.name, "done" if completed else "aborted", req.model, total, chars,
                (chars / total) if total else 0.0,
            )

    return wrapper
