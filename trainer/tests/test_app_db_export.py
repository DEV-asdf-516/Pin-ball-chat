import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainer.core.db.app_db import export_application_rows


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE turns (
          id TEXT PRIMARY KEY,
          selected_generation_id TEXT
        );
        CREATE TABLE generations (
          id TEXT PRIMARY KEY,
          turn_id TEXT NOT NULL,
          prompt_messages_json TEXT,
          prompt_hash TEXT,
          model_id TEXT,
          adapter_id TEXT,
          output_text TEXT NOT NULL,
          selected INTEGER NOT NULL DEFAULT 0,
          rejected INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE generation_edits (
          id TEXT PRIMARY KEY,
          generation_id TEXT NOT NULL,
          original_text TEXT NOT NULL,
          edited_text TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
    """)
    return conn


_PROMPT_MESSAGES = {
    "system": "시스템 프롬프트",
    "messages": [
        {"role": "user", "content": "이전 사용자 입력"},
        {"role": "assistant", "content": "이전 응답"},
        {"role": "user", "content": "현재 사용자 입력"},
    ],
}


class ChatExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = _connect()

    def tearDown(self):
        self.conn.close()

    def test_exports_structured_messages_with_single_current_input_and_latest_edit(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-1')"
        )
        self.conn.execute(
            "INSERT INTO generations (id, turn_id, prompt_messages_json, output_text) VALUES "
            "('gen-1', 'turn-1', ?, 'raw output')",
            (json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),),
        )
        self.conn.execute(
            "INSERT INTO generation_edits (id, generation_id, original_text, edited_text, created_at) VALUES "
            "('edit-1', 'gen-1', 'raw output', '오래된 수정', '2026-01-01T00:00:00Z')"
        )
        self.conn.execute(
            "INSERT INTO generation_edits (id, generation_id, original_text, edited_text, created_at) VALUES "
            "('edit-2', 'gen-1', 'raw output', '최신 수정', '2026-01-02T00:00:00Z')"
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "chat")

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["messages"],
            [
                {"role": "system", "content": "시스템 프롬프트"},
                {"role": "user", "content": "이전 사용자 입력"},
                {"role": "assistant", "content": "이전 응답"},
                {"role": "user", "content": "현재 사용자 입력"},
                {"role": "assistant", "content": "최신 수정"},
            ],
        )

    def test_excludes_legacy_rows_missing_prompt_messages_json(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-1')"
        )
        self.conn.execute(
            "INSERT INTO generations (id, turn_id, prompt_messages_json, output_text) VALUES "
            "('gen-1', 'turn-1', NULL, 'raw output')"
        )
        self.conn.execute(
            "INSERT INTO generation_edits (id, generation_id, original_text, edited_text, created_at) VALUES "
            "('edit-1', 'gen-1', 'raw output', '수정', '2026-01-01T00:00:00Z')"
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "chat")

        self.assertEqual(rows, [])

    def test_unedited_generation_is_not_included(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-1')"
        )
        self.conn.execute(
            "INSERT INTO generations (id, turn_id, prompt_messages_json, output_text) VALUES "
            "('gen-1', 'turn-1', ?, 'raw output')",
            (json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),),
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "chat")

        self.assertEqual(rows, [])


class PreferenceExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = _connect()

    def tearDown(self):
        self.conn.close()

    def _insert_generation(self, generation_id: str, turn_id: str, *, prompt_messages_json: str | None,
                            prompt_hash: str | None, model_id: str | None, adapter_id: str | None,
                            output_text: str, selected: int, rejected: int) -> None:
        self.conn.execute(
            "INSERT INTO generations (id, turn_id, prompt_messages_json, prompt_hash, model_id, adapter_id, "
            "output_text, selected, rejected) VALUES (?,?,?,?,?,?,?,?,?)",
            (generation_id, turn_id, prompt_messages_json, prompt_hash, model_id, adapter_id, output_text, selected, rejected),
        )

    def test_exports_structured_messages_with_chosen_and_rejected(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-selected')"
        )
        self._insert_generation(
            "gen-selected", "turn-1",
            prompt_messages_json=json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),
            prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="선택된 응답", selected=1, rejected=0,
        )
        self._insert_generation(
            "gen-rejected", "turn-1",
            prompt_messages_json=None,
            prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="거절된 응답", selected=0, rejected=1,
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "preference")

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["messages"],
            [
                {"role": "system", "content": "시스템 프롬프트"},
                {"role": "user", "content": "이전 사용자 입력"},
                {"role": "assistant", "content": "이전 응답"},
                {"role": "user", "content": "현재 사용자 입력"},
            ],
        )
        self.assertEqual(rows[0]["chosen"], "선택된 응답")
        self.assertEqual(rows[0]["rejected"], "거절된 응답")

    def test_excludes_legacy_rows_missing_prompt_messages_json_on_selected(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-selected')"
        )
        self._insert_generation(
            "gen-selected", "turn-1",
            prompt_messages_json=None, prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="선택된 응답", selected=1, rejected=0,
        )
        self._insert_generation(
            "gen-rejected", "turn-1",
            prompt_messages_json=None, prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="거절된 응답", selected=0, rejected=1,
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "preference")

        self.assertEqual(rows, [])

    def test_excludes_pair_when_rejected_prompt_hash_differs(self):
        # regenerate 사이에 캐릭터 설정/시스템 프롬프트가 바뀌면 같은 turn이라도 실제 입력 prompt가 달라질 수 있다.
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-selected')"
        )
        self._insert_generation(
            "gen-selected", "turn-1",
            prompt_messages_json=json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),
            prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="선택된 응답", selected=1, rejected=0,
        )
        self._insert_generation(
            "gen-rejected", "turn-1",
            prompt_messages_json=None,
            prompt_hash="hash-b", model_id="model-a", adapter_id="adapter-a",
            output_text="거절된 응답", selected=0, rejected=1,
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "preference")

        self.assertEqual(rows, [])

    def test_excludes_pair_when_model_id_differs(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-selected')"
        )
        self._insert_generation(
            "gen-selected", "turn-1",
            prompt_messages_json=json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),
            prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="선택된 응답", selected=1, rejected=0,
        )
        self._insert_generation(
            "gen-rejected", "turn-1",
            prompt_messages_json=None,
            prompt_hash="hash-a", model_id="model-b", adapter_id="adapter-a",
            output_text="거절된 응답", selected=0, rejected=1,
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "preference")

        self.assertEqual(rows, [])

    def test_excludes_pair_when_adapter_id_differs(self):
        self.conn.execute(
            "INSERT INTO turns (id, selected_generation_id) VALUES ('turn-1', 'gen-selected')"
        )
        self._insert_generation(
            "gen-selected", "turn-1",
            prompt_messages_json=json.dumps(_PROMPT_MESSAGES, ensure_ascii=False),
            prompt_hash="hash-a", model_id="model-a", adapter_id="adapter-a",
            output_text="선택된 응답", selected=1, rejected=0,
        )
        self._insert_generation(
            "gen-rejected", "turn-1",
            prompt_messages_json=None,
            prompt_hash="hash-a", model_id="model-a", adapter_id=None,
            output_text="거절된 응답", selected=0, rejected=1,
        )
        self.conn.commit()

        rows = export_application_rows(self.conn, "preference")

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
