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
from domain.content.importer import import_content_catalog
from domain.conversations.writer import create_conversation
from domain.generation_params import GenerationParams
from domain.generations.writer import chat, edit_generation, regenerate, select_generation


async def main():
    with connect() as conn:
        init_db(conn)
        errors = import_content_catalog(conn, ROOT / "examples")
        if errors:
            raise SystemExit("\n".join(errors))
        conv = create_conversation(conn, "first_meeting", "v0.1 smoke")
        params = GenerationParams()
        first = await chat(conn, conv["conversationId"], "문 앞에 섰어.", params)
        second = await regenerate(conn, first["turnId"], params)
        select_generation(conn, second["generationId"])
        edit_generation(conn, second["generationId"], "문은 열려 있어. 네가 원하면, 나는 여기서 기다릴게.")
        prompt = conn.execute("SELECT prompt_snapshot FROM generations WHERE id=?", (second["generationId"],)).fetchone()[0]

        # 템플릿 변수가 모두 치환됐는지
        for var in ["{{char}}", "{{user}}", "{{plot}}"]:
            assert var not in prompt, f"미치환 변수: {var}"

        # 필수 섹션이 모두 존재하는지
        for section in ["[역할]", "[캐릭터 프로필]", "[사용자 프로필]", "[플롯 프로필]", "[입력 표기]", "[현재 입력]", "[생성 규칙]", "[최근 대화]", "[사용자 원문]"]:
            assert section in prompt, f"섹션 누락: {section}"

        # 제거된 섹션이 남아 있지 않은지
        assert "[병합된 선호]" not in prompt

        # [생성 규칙] 내용 — global.json에서 온 규칙, 선호:/금지: 레이블
        assert "AI라고 말하지 않는다" in prompt
        assert "선호:" in prompt
        assert "금지:" in prompt

        # [입력 표기] 내용 — global.json inputMarkup
        assert "OOC:" in prompt

        print(json.dumps({"ok": True, "db": "temporary", "turnId": first["turnId"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
