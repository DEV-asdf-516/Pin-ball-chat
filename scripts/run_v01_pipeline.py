import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

_tmp = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = str(Path(_tmp.name) / "pinballchat.sqlite")

from core.db import connect, init_db
from domain.catalog.importer import import_catalog
from domain.conversations.writer import create_conversation
from domain.specs import GenerationParams
from domain.turns.writer import choose_generation, edit_generation, prepare_chat_stream, prepare_regenerate_stream
from domain.turns.streaming import stream_response
from domain.prompts.system.reader import build_prompt


async def _drain_stream(prepared: dict, params: GenerationParams) -> dict:
    """SSE 스트림을 끝까지 소비하고 done 이벤트의 payload를 반환한다. stream_response가 쓰기용으로
    별도 커넥션을 새로 열기 때문에, 이 함수를 부르기 전 단계의 쓰기는 전부 커밋돼 있어야 한다."""
    done: dict | None = None
    async for chunk in stream_response(prepared, params):
        event_line, data_line = chunk.strip("\n").split("\n")
        event: str = event_line.removeprefix("event:").strip()
        data: dict = json.loads(data_line.removeprefix("data:").strip())
        if event == "error":
            raise RuntimeError(f"stream error: {data}")
        if event == "done":
            done = data
    if done is None:
        raise RuntimeError("stream did not complete")
    return done


async def main():
    with connect() as conn:
        init_db(conn)
        errors = import_catalog(conn, ROOT / "examples")
        if errors:
            raise SystemExit("\n".join(errors))

    with connect() as conn:
        conv = create_conversation(conn, "first_meeting", "visitor", "v0.1 smoke")

    params = GenerationParams()

    with connect() as conn:
        prepared = prepare_chat_stream(conn, conv["conversationId"], "문 앞에 섰어.")
    first = await _drain_stream(prepared, params)

    with connect() as conn:
        prepared = prepare_regenerate_stream(conn, first["turnId"])
    second = await _drain_stream(prepared, params)

    with connect() as conn:
        choose_generation(conn, second["generationId"])
        edit_generation(conn, second["generationId"], "문은 열려 있어. 네가 원하면, 나는 여기서 기다릴게.")

    with connect() as conn:
        # regenerate로 rejected된 assistant 메시지가 messages 배열에 안 섞이는지
        built_check = build_prompt(conn, conv["conversationId"], "확인용")
        roles = [m.role for m in built_check.messages]
        for a, b in zip(roles, roles[1:]):
            assert not (a == "assistant" and b == "assistant"), f"연속된 assistant 메시지 발견 (rejected 필터 실패): {roles}"

    with connect() as conn:
        prompt = conn.execute("SELECT prompt_snapshot FROM generations WHERE id=?", (second["generationId"],)).fetchone()[0]

        # 템플릿 변수가 모두 치환됐는지
        for var in ["{{char}}", "{{user}}", "{{plot}}"]:
            assert var not in prompt, f"미치환 변수: {var}"

        # 필수 섹션이 모두 존재하는지
        for tag in ["system", "story", "title", "information", "char ", "user ", "style", "mandatory_rules", "output_format", "current_input"]:
            assert f"<{tag.strip()}" in prompt, f"섹션 누락: {tag}"

        # system_prompt.json에서 온 고정 규칙이 반영됐는지
        assert "관찰자" in prompt
        assert "Character agency" in prompt
        assert "NSFW" in prompt
        assert "@이름:" in prompt

    print(json.dumps({"ok": True, "db": "temporary", "turnId": first["turnId"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
