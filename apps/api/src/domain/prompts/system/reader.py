import json
import re
import sqlite3
from dataclasses import dataclass

from ai.specs import Message
from core.db import DATA_ROOT, RawSQL, fetch_all
from domain.conversations.reader import active_messages_sql
from domain.prompts.context import RECENT_WINDOW, build_ctx, described, render_value, resolve_prompt_context, row_json, tag


_OOC_PATTERN = re.compile(
    r"[\[\{\*]+\s*OOC:\s*(?P<wrapped>.*?)\s*[\]\}\*]+"
    r"|OOC:\s*(?P<bare>.*)$",
    re.IGNORECASE,
)

_SYSTEM_PROMPT_PATH = DATA_ROOT / "rules" / "system_prompt.json"


def _system_prompt() -> dict:
    # 매 호출마다 파일을 다시 읽는다 — 모듈 임포트 시점에 캐싱하면 파일을 고쳐도 프로세스 재시작 전까진 반영이 안 된다.
    # 이 파일은 몇 KB짜리라 매번 읽어도 비용이 무시할 만하다.
    return json.loads(_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))


@dataclass
class BuiltPrompt:
    system: str
    messages: list[Message]
    warnings: list
    plot: dict
    char: dict
    user: dict


def extract_ooc(text: str) -> tuple[str, list[str]]:
    # OOC 지시문을 `[OOC: ...]`/`*OOC: ...*`/줄 안 아무 데서나 나오는 맨 `OOC:` 세 형태 모두 인식해 분리한다.
    # OOC만 있던 줄은 통째로 빠지고, 다른 내용과 같은 줄에 있던 OOC는 그 부분만 잘라낸다.
    ooc: list[str] = []

    def replace(match: re.Match) -> str:
        ooc.append((match.group("wrapped") or match.group("bare") or "").strip())
        return ""

    body_lines: list[str] = []

    for line in text.splitlines():
        remainder: str = _OOC_PATTERN.sub(replace, line).strip()
        if remainder:
            body_lines.append(remainder)
        elif not _OOC_PATTERN.search(line):
            body_lines.append(line)

    return "\n".join(body_lines), ooc


def parse_roleplay_input(text: str, ctx: dict) -> dict:
    body, ooc_lines = extract_ooc(text)
    ooc: list[str] = [substitute_npc_pc(line, ctx) for line in ooc_lines]
    narrations: list[str] = [match.group(1).strip()
                             for match in re.finditer(r"\*([^*]+)\*", body)
                             if match.group(1).strip()]
    dialogue: str = re.sub(r"\*[^*]+\*", "", body)
    dialogue = re.sub(r"[ \t]+", " ", dialogue).strip()

    return {
        "dialogue": dialogue,
        "narration": "\n".join(narrations),
        "ooc": "\n".join(ooc)
        }


def user_input_interpretation(text: str, ctx: dict, system_prompt: dict) -> str:
    if not text.strip():
        return system_prompt["empty_input_directive"]

    parsed: dict = parse_roleplay_input(text, ctx)
    return "\n".join([
        "사용자 대사:",
        parsed["dialogue"] or "(없음)",
        "",
        "사용자가 직접 확정한 자기 캐릭터 서술:",
        parsed["narration"] or "(없음)",
        "",
        "사용자 생성 요청:",
        parsed["ooc"] or "(없음)",
    ])


def substitute_npc_pc(text: str, ctx: dict) -> str:
    # OOC 등 사용자 원문에 평문으로 등장하는 NPC/PC 표기를 실제 캐릭터명으로 치환한다.
    # (NPC)/{NPC}/(PC)/{PC}처럼 괄호로 감싼 표기는 괄호까지 통째로, 맨 단어는 단어 경계로 치환한다.
    text = re.sub(r"[(\{]NPC[)\}]|(?<![A-Za-z0-9])NPC(?![A-Za-z0-9])", ctx["char"], text)
    text = re.sub(r"[(\{]PC[)\}]|(?<![A-Za-z0-9])PC(?![A-Za-z0-9])", ctx["user"], text)
    return text


def render_json_source(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def source_for(payload: dict, source_text: str | None) -> str:
    return source_text if source_text else render_json_source(payload)


def _section_text(system_prompt: dict, key: str) -> str:
    return "\n".join(system_prompt[key].get("content", []))


def snapshot_text(system: str, messages: list[Message]) -> str:
    return system + "\n\n" + "\n".join(f"{m.role}: {m.content}" for m in messages)


def build_prompt(conn: sqlite3.Connection, conversation_id: str, user_message: str, exclude_turn_id: str | None = None) -> BuiltPrompt:
    # system_prompt.json에 정의된 관찰자 프롬프트 골격 위에, 이 conversation의 캐릭터/유저/플롯 데이터를 채워 넣는다.
    # TODO: preferences.json을 로어북처럼 쓰는 방식으로 나중에 다시 연결한다.

    system_prompt: dict = _system_prompt()
    conv, plot, char, user = resolve_prompt_context(conn, conversation_id)
    char_json: dict = row_json(char, "profile_json")
    user_json: dict = row_json(user, "profile_json")
    plot_json: dict = row_json(plot, "plot_json")
    ctx: dict = build_ctx(plot, char, user)
    warnings: list = []

    char_source: str = source_for(char_json, char["source_text"])
    user_source: str = source_for(user_json, user["source_text"])
    plot_source: str = source_for(plot_json, plot["source_text"])

    char_body, _ = extract_ooc(render_value(char_source, ctx, warnings))
    user_body, _ = extract_ooc(render_value(user_source, ctx, warnings))
    plot_body, _ = extract_ooc(render_value(plot_source, ctx, warnings))

    # regenerate 중엔 이 turn의 기존 candidate가 아직 rejected=1로 안 바뀐 상태라 active_messages_sql만으로는
    # 안 걸러진다 — exclude_turn_id로 이 turn의 유저 메시지·이전 candidate를 recent에서 직접 빼고,
    # 유저 메시지는 아래 current_input으로 다시 채운다.
    recent: list[sqlite3.Row] = fetch_all(
        conn,
        RawSQL(active_messages_sql(
            ("m.role", "m.content"),
            extra_where="AND (:exclude_turn_id IS NULL OR m.turn_id IS NULL OR m.turn_id != :exclude_turn_id)",
            tail=f"LIMIT {RECENT_WINDOW}",
        )),
        params={"conversation_id": conversation_id, "exclude_turn_id": exclude_turn_id},
    )

    story_body: str = "\n\n".join([
        tag("title", ctx["plot"]),
        tag("information", plot_body),
        f'<char name="{ctx["char"]}" role="assistant">\n{char_body}\n</char>',
        f'<char name="관찰자" role="assistant">\n{system_prompt["story"]["observer_char"]}\n</char>',
        f'<user name="{ctx["user"]}" role="user">\n{user_body}\n</user>',
    ])

    system_text: str = render_value(_section_text(system_prompt, "system"), ctx, warnings)
    sections: list[str] = [
        described(system_prompt["system"]["description"], "system", system_text),
        described(system_prompt["story"]["description"], "story", story_body),
    ]

    if conv["summary_text"]:
        sections.append(described(system_prompt["summary_description"], "summary", conv["summary_text"]))

    mandatory_rules_text: str = render_value(_section_text(system_prompt, "mandatory_rules"), ctx, warnings)
    output_format_text: str = render_value(_section_text(system_prompt, "output_format"), ctx, warnings)
    sections += [
        described(system_prompt["style"]["description"], "style", ""),
        described(system_prompt["mandatory_rules"]["description"], "mandatory_rules", mandatory_rules_text),
        described(system_prompt["output_format"]["description"], "output_format", output_format_text),
    ]

    system: str = "\n\n".join(sections)

    messages: list[Message] = [
        *[Message(role=r["role"], content=r["content"]) for r in reversed(recent)],
        Message(role="user", content=described(system_prompt["current_input_description"], "current_input", user_input_interpretation(user_message, ctx, system_prompt))),
    ]
    return BuiltPrompt(system=system, messages=messages, warnings=warnings, plot=plot, char=char, user=user)
