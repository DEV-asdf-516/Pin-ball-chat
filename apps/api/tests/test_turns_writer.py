import json
import os
import tempfile
import unittest

from ai.specs import GenerateRequest, Message
from core.db.sqlite import connect as _sqlite_connect, init_db
from domain.prompts.system.reader import BuiltPrompt
from domain.specs import GenerationParams
from domain.turns.specs import ActionType, PreparedGeneration
from domain.turns.writer import create_user_turn, record_generation_output


def _seed_conversation(conn) -> None:
    conn.execute(
        "INSERT INTO plots (id, title, plot_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("plot-1", "plot", "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO characters (id, name, plot_id, sort_order, profile_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("char-1", "char", "plot-1", 0, "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO user_profiles (id, name, profile_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("user-1", "user", "{}", "t", "t"),
    )
    conn.execute(
        "INSERT INTO conversations (id, plot_id, user_profile_id, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("conv-1", "plot-1", "user-1", "t", "t"),
    )
    conn.commit()


def _built_prompt() -> BuiltPrompt:
    return BuiltPrompt(
        system="시스템 프롬프트",
        messages=[
            Message(role="user", content="이전 사용자 입력"),
            Message(role="assistant", content="이전 응답"),
            Message(role="user", content="현재 사용자 입력"),
        ],
        warnings=[],
        plot={"id": "plot-1"},
        char={"id": "char-1"},
        user={"id": "user-1"},
    )


def _prepared(built: BuiltPrompt) -> PreparedGeneration:
    return PreparedGeneration(
        conversation_id="conv-1",
        turn_id="turn-1",
        user_message="현재 사용자 입력",
        built=built,
        action_type=ActionType.GENERATION_SHOWN,
        message_id="msg-user-1",
        created_at="t",
    )


class RecordGenerationOutputTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test.sqlite")
        self._conn = _sqlite_connect(db_path)
        init_db(self._conn)
        _seed_conversation(self._conn)

    def tearDown(self):
        self._conn.close()
        self._tmpdir.cleanup()

    def test_stores_prompt_messages_json_matching_built_prompt(self):
        built = _built_prompt()
        prepared = _prepared(built)
        create_user_turn(self._conn, prepared)
        req = GenerateRequest(system=built.system, messages=built.messages, model="local-stub", candidate_index=0)
        params = GenerationParams(model="local-stub")

        record_generation_output(self._conn, prepared, params, req, "승인된 응답")

        row = self._conn.execute("SELECT * FROM generations WHERE turn_id='turn-1'").fetchone()
        stored = json.loads(row["prompt_messages_json"])

        self.assertEqual(stored["system"], built.system)
        self.assertEqual(
            stored["messages"],
            [{"role": m.role, "content": m.content} for m in built.messages],
        )

    def test_prompt_snapshot_and_prompt_hash_still_behave_as_before(self):
        built = _built_prompt()
        prepared = _prepared(built)
        create_user_turn(self._conn, prepared)
        req = GenerateRequest(system=built.system, messages=built.messages, model="local-stub", candidate_index=0)
        params = GenerationParams(model="local-stub")

        record_generation_output(self._conn, prepared, params, req, "승인된 응답")

        row = self._conn.execute("SELECT * FROM generations WHERE turn_id='turn-1'").fetchone()
        expected_snapshot = built.system + "\n\n" + "\n".join(f"{m.role}: {m.content}" for m in built.messages)

        self.assertEqual(row["prompt_snapshot"], expected_snapshot)
        self.assertIsNotNone(row["prompt_hash"])


if __name__ == "__main__":
    unittest.main()
