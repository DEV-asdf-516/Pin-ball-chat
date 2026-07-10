import json
from typing import AsyncIterator

import httpx

_SSE_DATA_PREFIX = "data:"
_SSE_DONE_MARKER = "[DONE]"


async def aiter_sse_events(response: httpx.Response) -> AsyncIterator[dict]:
    # text/event-stream 응답에서 data: 블록을 파싱해 JSON 이벤트로 yield한다.
    lines: list[str] = []
    async for line in response.aiter_lines():
        if line.strip():
            lines.append(line)
            continue
        event: dict | None = _parse_block(lines)
        lines = []
        if event is not None:
            yield event

    event: dict | None = _parse_block(lines)
    if event is not None:
        yield event


def _parse_block(lines: list[str]) -> dict | None:
    data_lines: list[str] = [line[len(_SSE_DATA_PREFIX):].lstrip() for line in lines if line.startswith(_SSE_DATA_PREFIX)]
    if not data_lines:
        return None
    data: str = "\n".join(data_lines)
    if not data or data == _SSE_DONE_MARKER:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None
