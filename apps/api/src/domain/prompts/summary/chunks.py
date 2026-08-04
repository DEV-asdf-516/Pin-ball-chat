from collections.abc import Sequence

from ai.specs import ProviderName
from domain.prompts.system.reader import extract_ooc


DEFAULT_SUMMARY_CHUNK_CHAR_LIMIT = 70_000
OLLAMA_SUMMARY_CHUNK_CHAR_LIMIT = 10_000
MIN_SUMMARY_CHUNK_CHAR_LIMIT = 2_000


def summary_chunk_char_limit(provider_name: str | None) -> int:
    if provider_name == ProviderName.OLLAMA:
        return OLLAMA_SUMMARY_CHUNK_CHAR_LIMIT
    return DEFAULT_SUMMARY_CHUNK_CHAR_LIMIT


def smaller_summary_chunk_char_limit(current_limit: int, failed_chars: int) -> int:
    if current_limit <= MIN_SUMMARY_CHUNK_CHAR_LIMIT:
        return current_limit
    reduced: int = max(MIN_SUMMARY_CHUNK_CHAR_LIMIT, failed_chars // 2)
    return min(current_limit - 1, reduced)


def render_summary_message(message, user_name: str) -> str:
    content: str = str(message["content"] or "")
    return f"{user_name}: {content}" if message["role"] == "user" else content


def drop_ooc_only_turns(messages: Sequence) -> list:
    # OOC 내용만 있는 user 턴은 스토리 진행이 아니라 생성 제어 요청이므로, 그 요청과
    # 그에 대한 assistant 응답(같은 turn_id)을 통째로 요약 대상에서 제외한다.
    ooc_only_turn_ids: set = set()
    for message in messages:
        if message["role"] != "user" or message["turn_id"] is None:
            continue
        body, ooc = extract_ooc(str(message["content"] or ""))
        if ooc and not body.strip():
            ooc_only_turn_ids.add(message["turn_id"])
    return [message for message in messages if message["turn_id"] not in ooc_only_turn_ids]


def take_summary_chunk(messages: Sequence, user_name: str, char_limit: int) -> list:
    if char_limit < 1:
        raise ValueError("summary chunk char limit must be positive")

    chunk: list = []
    used_chars = 0
    for message in messages:
        rendered: str = render_summary_message(message, user_name)
        added_chars: int = len(rendered) + (1 if chunk else 0)
        if chunk and used_chars + added_chars > char_limit:
            break
        chunk.append(message)
        used_chars += added_chars
    return chunk


def render_summary_dialogue(messages: Sequence, user_name: str) -> str:
    return "\n".join(render_summary_message(message, user_name) for message in messages)
