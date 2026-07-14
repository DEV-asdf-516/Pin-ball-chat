import json
import logging
import sqlite3

from ai.registry import stream_text
from ai.specs import GenerateRequest, Message
from core.db import ROOT, Bind, RawSQL, ReadQuery, WriteQuery, connect, fetch_all, fetch_one, find_one, init_db, update
from domain.conversations.reader import active_messages_sql
from domain.conversations.specs import CONVERSATIONS, RECENT_WINDOW, SUMMARY_TRIGGER
from domain.prompts.context import build_ctx, described, render_value, resolve_prompt_context
from domain.specs import GenerationParams
from util.time_util import utc_now_string

log = logging.getLogger(__name__)

# ai.settings.DEFAULT_NUM_PREDICT(160)는 짧은 채팅 응답 기준이라 800자 요약 포맷을 다 못 채우고 잘린다.
# 요약 호출은 그거 말고 이 값을 쓴다.
_SUMMARY_NUM_PREDICT = 1300
_SUMMARY_NUM_CTX = 16384

_SUMMARY_SYSTEM_PROMPT_PATH = ROOT / "rules" / "summary_system_prompt.json"

# 채팅 스트리밍 응답 전송이 끝난 뒤 백그라운드로 호출된다 
# build_prompt()가 최근 RECENT_WINDOW개 메시지는 항상 원문으로 넣으므로, 그보다 오래돼 밀려난 메시지가 
# SUMMARY_TRIGGER개 이상 쌓였을 때만 이전 요약과 합쳐 새 요약을 만든다.
async def maybe_update_summary(conversation_id: str) -> None:
    try:
        with connect() as conn:
            init_db(conn)

            conv: dict | None = find_one(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
            if not conv:
                return

            active: list[sqlite3.Row] = fetch_all(
                conn,
                RawSQL(active_messages_sql(("m.rowid", "m.role", "m.content"), order="ASC")),
                {"conversation_id": conversation_id},
            )
            
            older: list[sqlite3.Row] = active[:-RECENT_WINDOW] if len(active) > RECENT_WINDOW else []
            
            through_rowid: int = conv["summary_through_rowid"] or 0
            
            pending: list[sqlite3.Row] = [m for m in older if m["rowid"] > through_rowid]
            
            if len(pending) < SUMMARY_TRIGGER:
                return

            # 실제로 마지막에 채팅을 생성할 때 쓴 provider/model을 그대로 요약에도 쓴다.
            # conversation_settings는 유저가 설정 시트에서 명시적으로 저장해야만 채워지는 별개의 테이블이라 신뢰할 수 없다.
            last_gen: sqlite3.Row | None = fetch_one(
                conn,
                RawSQL("""
                SELECT model_id, params_json
                FROM generations
                WHERE conversation_id=:conversation_id
                ORDER BY rowid DESC
                LIMIT 1
                """),
                {"conversation_id": conversation_id},
            )
            
            if last_gen:
                provider_name: str | None = json.loads(last_gen["params_json"]).get("provider") if last_gen["params_json"] else None
                params = GenerationParams(model=last_gen["model_id"], provider_name=provider_name)
            else:
                params = GenerationParams()

            _, plot, char, user = resolve_prompt_context(conn, conversation_id)
            ctx: dict = build_ctx(plot, char, user)

            # assistant 메시지는 output_format 규칙상 '@이름:'을 이미 본문에 포함하고 있어 그대로 쓰고,
            # user 메시지만 화자 구분을 위해 실제 유저 이름을 붙인다 — 나머지 프롬프트가 쓰는 것과 같은 표기.
            new_dialogue: str = "\n".join(
                (f"{ctx['user']}: " + m["content"]) if m["role"] == "user" else m["content"]
                for m in pending
            )
            prompt_body: str = "\n\n".join([
                "[이전 요약]",
                conv["summary_text"] or "(없음)",
                "",
                "[새 대화]",
                new_dialogue,
            ])

            # summary_system_prompt.json의 {{char}}/{{user}}를 실제 이름으로 치환한다.
            # 파일은 매 호출마다 다시 읽는다 — system_prompt와 같은 이유(재시작 없이 수정 반영).
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

            req = GenerateRequest(
                system=instruction,
                messages=[Message(role="user", content=prompt_body)],
                model=params.model,
                candidate_index=0,
                num_predict=_SUMMARY_NUM_PREDICT,
                num_ctx=_SUMMARY_NUM_CTX,
            )

            summary_text: str = "".join([token async for token in stream_text(req, params.provider_name)]).strip()
            if not summary_text:
                return

            update(conn, WriteQuery(
                CONVERSATIONS,
                Bind({
                    "summary_text": summary_text,
                    "summary_through_rowid": pending[-1]["rowid"],
                    "updated_at": utc_now_string(),
                }),
                Bind({"id": conversation_id}),
            ))
    except Exception:
        log.exception("conversation summary update failed: conversation_id=%s", conversation_id)
