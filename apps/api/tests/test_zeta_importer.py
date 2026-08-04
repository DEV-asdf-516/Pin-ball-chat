import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.db.sqlite import connect, init_db
from core.errors import BadRequest, Conflict
from core.db import insert as db_insert
from domain.conversations.importer.importer import commit_import_session, get_import_session, upload_import_part, start_import_session


def _seed(conn, conversation_id="conv-1"):
    conn.execute(
        "INSERT INTO plots (id,title,plot_json,created_at,updated_at) VALUES (:id,:title,:plot,:ts,:ts)",
        {"id": "plot-1", "title": "플롯", "plot": "{}", "ts": "t"},
    )
    conn.execute(
        "INSERT INTO characters (id,name,plot_id,sort_order,profile_json,created_at,updated_at) VALUES (:id,:name,:plot_id,0,:profile,:ts,:ts)",
        {"id": "char-1", "name": "캐릭터", "plot_id": "plot-1", "profile": "{}", "ts": "t"},
    )
    conn.execute(
        "INSERT INTO user_profiles (id,name,profile_json,created_at,updated_at) VALUES (:id,:name,:profile,:ts,:ts)",
        {"id": "user-1", "name": "유저", "profile": "{}", "ts": "t"},
    )
    conn.execute(
        "INSERT INTO conversations (id,plot_id,user_profile_id,created_at,updated_at) VALUES (:id,:plot,:user,:ts,:ts)",
        {"id": conversation_id, "plot": "plot-1", "user": "user-1", "ts": "t"},
    )
    conn.execute(
        "INSERT INTO messages (id,conversation_id,role,content,created_at) VALUES (:id,:conversation,'assistant','intro',:ts)",
        {"id": f"intro_{conversation_id}_0", "conversation": conversation_id, "ts": "t"},
    )
    conn.commit()


def _message(message_id, sender, time, text, speaker="캐릭터", position="LEFT"):
    return {
        "id": message_id,
        "roomId": "room-1",
        "sender": {"type": sender},
        "messageTime": time,
        "contents": [{"type": "TEXT", "speakerName": speaker, "position": position, "text": text}],
    }


class ZetaImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp.name) / "test.sqlite")
        init_db(self.conn)
        _seed(self.conn)
        self.sessions = Path(self.temp.name) / "sessions"
        self.root_patch = patch("domain.conversations.importer.session_store.IMPORT_SESSIONS_ROOT", self.sessions)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.conn.close()
        self.temp.cleanup()

    def _start(self, expected_messages, expected_parts=1):
        return start_import_session(self.conn, "conv-1", {
            "roomId": "room-1",
            "expectedParts": expected_parts,
            "expectedMessages": expected_messages,
        })

    def test_import_maps_leading_bot_users_and_merged_bots(self):
        session = self._start(5)
        part = {"messages": [
            _message("bot-0", "BOT", "2025-01-01T00:00:00.000000001Z", "도입", "나레이터", "NARRATOR"),
            _message("user-1", "USER", "2025-01-01T00:00:01Z", "안녕", "사용자", "RIGHT"),
            _message("bot-1", "BOT", "2025-01-01T00:00:02.000000002Z", "첫째"),
            _message("bot-2", "BOT", "2025-01-01T00:00:02.000000001Z", "둘째"),
            _message("user-2", "USER", "2025-01-01T00:00:03Z", "계속", "사용자", "RIGHT"),
        ]}
        upload_import_part(session["sessionId"], 1, part)

        result = commit_import_session(self.conn, session["sessionId"])

        self.assertEqual(result["turnCount"], 2)
        self.assertEqual(result["messageCount"], 4)
        rows = self.conn.execute("SELECT * FROM messages ORDER BY rowid").fetchall()
        self.assertEqual([row["role"] for row in rows], ["assistant", "user", "assistant", "user"])
        self.assertEqual(rows[0]["id"], "zimp_conv-1_bot-0")
        self.assertEqual(rows[0]["content"], "@관찰자: 도입")
        self.assertEqual(rows[2]["content"], "@캐릭터: 둘째\n\n@캐릭터: 첫째")
        generation = self.conn.execute("SELECT * FROM generations").fetchone()
        self.assertIsNone(generation["prompt_messages_json"])
        self.assertEqual(json.loads(generation["params_json"])["originalMessageIds"], ["bot-2", "bot-1"])
        self.assertEqual(generation["created_at"], "2025-01-01T00:00:02Z")
        self.assertIsNone(get_import_session("conv-1"))
        self.assertEqual(self.conn.execute("SELECT action_type FROM user_actions").fetchone()[0], "import_committed")

    def test_user_content_with_narrator_position_is_stored_as_narration(self):
        session = self._start(1)
        message = _message("m1", "USER", "2025-01-01T00:00:00Z", "새벽 세 시.", "내레이터", "NARRATOR")
        upload_import_part(session["sessionId"], 1, {"messages": [message]})

        result = commit_import_session(self.conn, session["sessionId"])

        row = self.conn.execute("SELECT role, content FROM messages ORDER BY rowid").fetchone()
        self.assertEqual(row["role"], "user")
        self.assertEqual(row["content"], "@관찰자: 새벽 세 시.")

    def test_idempotent_part_replace_recalculates_counters(self):
        session = self._start(1)
        upload_import_part(session["sessionId"], 1, {"messages": [
            _message("one", "USER", "2025-01-01T00:00:00Z", "one"),
            _message("two", "USER", "2025-01-01T00:00:01Z", "two"),
        ]})
        result = upload_import_part(session["sessionId"], 1, {"messages": [
            _message("replacement", "USER", "2025-01-01T00:00:02Z", "replacement"),
        ]})
        self.assertEqual(result["receivedMessages"], 1)
        self.assertEqual(result["receivedParts"], [1])

    def test_conflicting_duplicate_rejects_commit_and_preserves_intro(self):
        session = self._start(2, 2)
        upload_import_part(session["sessionId"], 1, {"messages": [_message("same", "USER", "2025-01-01T00:00:00Z", "one")]})
        upload_import_part(session["sessionId"], 2, {"messages": [_message("same", "USER", "2025-01-01T00:00:00Z", "two")]})
        with self.assertRaises(BadRequest):
            commit_import_session(self.conn, session["sessionId"])
        self.assertEqual(self.conn.execute("SELECT content FROM messages").fetchone()[0], "intro")
        self.assertEqual(get_import_session("conv-1")["state"], "uploading")

    def test_bot_only_import_is_not_empty(self):
        session = self._start(1)
        upload_import_part(session["sessionId"], 1, {"messages": [_message("bot", "BOT", "2025-01-01T00:00:00Z", "hello")]})
        commit_import_session(self.conn, session["sessionId"])
        with self.assertRaises(Conflict):
            self._start(1)

    def test_invalid_room_and_zero_valid_messages_are_rejected(self):
        session = self._start(1)
        wrong = _message("one", "USER", "2025-01-01T00:00:00Z", "one")
        wrong["roomId"] = "other"
        with self.assertRaises(BadRequest):
            upload_import_part(session["sessionId"], 1, {"messages": [wrong]})
        empty = _message("empty", "BOT", "2025-01-01T00:00:00Z", "ignored")
        empty["contents"] = []
        upload_import_part(session["sessionId"], 1, {"messages": [empty]})
        with self.assertRaises(BadRequest):
            commit_import_session(self.conn, session["sessionId"])
        self.assertEqual(self.conn.execute("SELECT content FROM messages").fetchone()[0], "intro")

    def test_identical_duplicate_is_deduplicated_and_speaker_warnings_are_returned(self):
        session = self._start(2, 2)
        message = _message("same", "BOT", "2025-01-01T00:00:00.123456789Z", "@이미: 있음", ":\n")
        upload_import_part(session["sessionId"], 1, {"messages": [message]})
        upload_import_part(session["sessionId"], 2, {"messages": [message]})

        result = commit_import_session(self.conn, session["sessionId"])

        self.assertEqual(result["messageCount"], 1)
        self.assertTrue(any("@speaker" in warning for warning in result["warnings"]))
        self.assertTrue(any("관찰자" in warning for warning in result["warnings"]))
        imported = self.conn.execute("SELECT content FROM messages").fetchone()[0]
        self.assertEqual(imported, "@관찰자: @이미: 있음")

    def test_database_failure_rolls_back_intro_and_partial_rows(self):
        session = self._start(2)
        upload_import_part(session["sessionId"], 1, {"messages": [
            _message("user", "USER", "2025-01-01T00:00:00Z", "hello"),
            _message("bot", "BOT", "2025-01-01T00:00:01Z", "reply"),
        ]})
        calls = 0

        def fail_after_first_insert(conn, spec, values):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated insert failure")
            return db_insert(conn, spec, values)

        with patch("domain.conversations.writer.insert", side_effect=fail_after_first_insert):
            with self.assertRaises(RuntimeError):
                commit_import_session(self.conn, session["sessionId"])

        rows = self.conn.execute("SELECT id, content FROM messages").fetchall()
        self.assertEqual([(row["id"], row["content"]) for row in rows], [("intro_conv-1_0", "intro")])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
