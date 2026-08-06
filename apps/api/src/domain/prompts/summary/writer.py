import asyncio
import json
import logging
import sqlite3
import weakref

from ai.registry import stream_text
from ai.specs import GenerateRequest, Message
from core.db import DATA_ROOT, Bind, RawSQL, ReadQuery, WriteQuery, connect, fetch_all, fetch_one, find_one, init_db, session, update
from domain.conversations.reader import active_messages_sql
from domain.conversations.specs import CONVERSATIONS
from domain.prompts.context import RECENT_WINDOW, SUMMARY_TRIGGER, PromptContext, build_ctx, described, render_value, resolve_prompt_context
from domain.prompts.summary.chunks import drop_ooc_only_turns, render_summary_dialogue, smaller_summary_chunk_char_limit, summary_chunk_char_limit, take_summary_chunk
from domain.specs import GenerationParams
from util.safe_util import get_safe_str, parse_json_dict
from util.time_util import utc_now_string

log = logging.getLogger(__name__)

# num_ctx는 Ollama 요청에만 적용된다. Claude/Codex를 포함한 모든 provider의 실제 입력 분할은
# summary.chunks의 애플리케이션 문자량 정책으로 별도 보장한다.
_SUMMARY_NUM_PREDICT = 1300
_SUMMARY_NUM_CTX = 16384

_SUMMARY_SYSTEM_PROMPT_PATH = DATA_ROOT / "rules" / "summary_system_prompt.json"

_summary_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

# 채팅 스트리밍 응답 전송이 끝난 뒤 백그라운드로 호출된다
# build_prompt()가 최근 RECENT_WINDOW개 메시지는 항상 원문으로 넣으므로, 그보다 오래돼 밀려난 메시지가
# SUMMARY_TRIGGER개 이상 쌓였을 때만 이전 요약과 합쳐 새 요약을 만든다.
async def maybe_update_summary(conversation_id: str) -> None:
    def _load_summary_job() -> dict | None:
        with session(connect) as conn:
            init_db(conn)

            conv: dict | None = find_one(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
            if not conv:
                return None

            active: list[sqlite3.Row] = fetch_all(
                conn,
                RawSQL(active_messages_sql(("m.rowid", "m.role", "m.content", "m.turn_id"), order="ASC")),
                {"conversation_id": conversation_id},
            )
            older: list[sqlite3.Row] = active[:-RECENT_WINDOW] if len(active) > RECENT_WINDOW else []
            through_rowid: int = conv["summary_through_rowid"] or 0

            pending: list[sqlite3.Row] = drop_ooc_only_turns([message for message in older if message["rowid"] > through_rowid])

            if len(pending) < SUMMARY_TRIGGER:
                return None

            last_gen: sqlite3.Row | None = fetch_one(
                conn,
                RawSQL("""
                SELECT
                    model_id,
                    params_json
                FROM generations
                WHERE conversation_id=:conversation_id
                ORDER BY rowid DESC
                LIMIT 1
                """),
                {"conversation_id": conversation_id},
            )

            params = GenerationParams()
            
            if last_gen:
                params_json: dict = parse_json_dict(last_gen["params_json"]) or {}
                provider_name: str = get_safe_str(params_json, "provider")
                params = GenerationParams(model=last_gen["model_id"], provider_name=provider_name)
         
    
            prompt_ctx: PromptContext = resolve_prompt_context(conn, conversation_id)
            ctx: dict = build_ctx(prompt_ctx.plot, prompt_ctx.chars[0], prompt_ctx.user)
            relationship_target_line_values: list[str] = []
            
            for character in prompt_ctx.chars:
                character_ctx: dict = build_ctx(prompt_ctx.plot, character, prompt_ctx.user)
                character_name: str = character_ctx["char"]
                relationship_target_line: str = (
                    f"- {character_name}→{ctx['user']}: "
                    "현재 태도 한 줄 (변화: 이전→현재)."
                )
                relationship_target_line_values.append(relationship_target_line)
            
            relationship_target_lines: str = "\n".join(relationship_target_line_values)
            
            ctx = {**ctx, "relationship_targets": relationship_target_lines}

        summary_system_prompt: dict = json.loads(_SUMMARY_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))
        warnings: list = []
        instruction: str = "\n\n".join(
            described(
                summary_system_prompt[key]["description"],
                key,
                render_value("\n".join(summary_system_prompt[key]["content"]), ctx, warnings),
            )
            for key in ("role", "format", "output_rules")
        )
        return {
            "instruction": instruction,
            "params": params,
            "pending": pending,
            "summary_text": conv["summary_text"] or "",
            "through_rowid": through_rowid,
            "user_name": ctx["user"],
        }

    lock: asyncio.Lock = _summary_locks.setdefault(conversation_id, asyncio.Lock())
    
    try:
        async with lock:
            job: dict | None = _load_summary_job()
            if not job:
                return

            params: GenerationParams = job["params"]
            pending: list = job["pending"]
            summary_text: str = job["summary_text"]
            through_rowid: int = job["through_rowid"]
            user_name: str = job["user_name"]
            instruction: str = job["instruction"]
            char_limit: int = summary_chunk_char_limit(params.provider_name)

            while pending:
                chunk: list = take_summary_chunk(pending, user_name, char_limit)
                new_dialogue: str = render_summary_dialogue(chunk, user_name)
                prompt_body: str = "\n\n".join([
                    "[이전 요약]",
                    summary_text or "(없음)",
                    "",
                    "[새 대화]",
                    new_dialogue,
                ])
                req: GenerateRequest = GenerateRequest(
                    system=instruction,
                    messages=[Message(role="user", content=prompt_body)],
                    model=params.model,
                    candidate_index=0,
                    num_predict=_SUMMARY_NUM_PREDICT,
                    num_ctx=_SUMMARY_NUM_CTX,
                )
                chunk_through_rowid: int = chunk[-1]["rowid"]
                try:
                    next_summary: str = "".join([token async for token in stream_text(req, params.provider_name)]).strip()
                except Exception:
                    reduced_limit: int = smaller_summary_chunk_char_limit(char_limit, len(new_dialogue))
                    if len(chunk) > 1 and reduced_limit < char_limit:
                        log.warning(
                            "conversation summary chunk retrying with smaller input: conversation_id=%s through_rowid=%s chunk_through_rowid=%s chunk_messages=%s chunk_chars=%s next_char_limit=%s",
                            conversation_id,
                            through_rowid,
                            chunk_through_rowid,
                            len(chunk),
                            len(new_dialogue),
                            reduced_limit,
                            exc_info=True,
                        )
                        char_limit = reduced_limit
                        continue
                    log.exception(
                        "conversation summary chunk failed: conversation_id=%s through_rowid=%s chunk_through_rowid=%s chunk_messages=%s chunk_chars=%s",
                        conversation_id,
                        through_rowid,
                        chunk_through_rowid,
                        len(chunk),
                        len(new_dialogue),
                    )
                    return

                if not next_summary:
                    return

                with session(connect) as conn:
                    init_db(conn)
                    cursor = update(conn, WriteQuery(
                        CONVERSATIONS,
                        Bind({
                            "summary_text": next_summary,
                            "summary_through_rowid": chunk_through_rowid,
                            "updated_at": utc_now_string(),
                        }),
                        Bind({"id": conversation_id, "summary_through_rowid": through_rowid}),
                    ))
                    
                    if cursor.rowcount != 1:
                        log.info("conversation summary progress changed during update: conversation_id=%s", conversation_id)
                        return

                log.info(
                    "conversation summary chunk updated: conversation_id=%s through_rowid=%s chunk_messages=%s chunk_chars=%s",
                    conversation_id,
                    chunk_through_rowid,
                    len(chunk),
                    len(new_dialogue),
                )
                summary_text = next_summary
                through_rowid = chunk_through_rowid
                pending = pending[len(chunk):]
    except Exception:
        log.exception("conversation summary update failed: conversation_id=%s", conversation_id)
