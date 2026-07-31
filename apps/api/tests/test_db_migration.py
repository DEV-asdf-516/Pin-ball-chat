import os
import tempfile
import unittest

from core.db.sqlite import connect as _sqlite_connect, init_db


class PromptMessagesJsonMigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmpdir.name, "test.sqlite")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _columns(self, conn) -> set[str]:
        return {row["name"] for row in conn.execute("PRAGMA table_info(generations)")}

    def test_new_db_has_prompt_messages_json_column(self):
        conn = _sqlite_connect(self._db_path)
        init_db(conn)
        self.assertIn("prompt_messages_json", self._columns(conn))
        conn.close()

    def test_pre_existing_db_without_column_is_migrated_without_data_loss(self):
        conn = _sqlite_connect(self._db_path)
        conn.executescript("""
            CREATE TABLE generations (
              id TEXT PRIMARY KEY,
              turn_id TEXT NOT NULL,
              conversation_id TEXT NOT NULL,
              plot_id TEXT NOT NULL,
              character_id TEXT NOT NULL,
              user_profile_id TEXT,
              model_id TEXT NOT NULL,
              adapter_id TEXT,
              candidate_index INTEGER NOT NULL,
              prompt_snapshot TEXT NOT NULL,
              prompt_hash TEXT NOT NULL,
              output_text TEXT NOT NULL,
              params_json TEXT NOT NULL,
              output_token_count INTEGER,
              selected INTEGER NOT NULL DEFAULT 0,
              rejected INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO generations (id, turn_id, conversation_id, plot_id, character_id, model_id, "
            "candidate_index, prompt_snapshot, prompt_hash, output_text, params_json, created_at) "
            "VALUES ('gen-legacy','turn-1','conv-1','plot-1','char-1','local-stub',0,'snap','hash','out','{}','t')"
        )
        conn.commit()
        conn.close()

        conn = _sqlite_connect(self._db_path)
        init_db(conn)
        self.assertIn("prompt_messages_json", self._columns(conn))

        row = conn.execute("SELECT * FROM generations WHERE id='gen-legacy'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["output_text"], "out")
        self.assertIsNone(row["prompt_messages_json"])
        conn.close()

    def test_repeated_init_is_idempotent(self):
        conn = _sqlite_connect(self._db_path)
        init_db(conn)
        init_db(conn)
        self.assertIn("prompt_messages_json", self._columns(conn))
        conn.close()


if __name__ == "__main__":
    unittest.main()
