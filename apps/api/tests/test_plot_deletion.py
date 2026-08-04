import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from ai.specs import PromptTier
from core.db.sqlite import connect, init_db
from core.errors import Conflict
from domain.catalog.reader import is_catalog_exists
from domain.catalog.specs import CatalogKind
from domain.characters import delete_character
from domain.conversations.writer import create_conversation
from domain.prompts.system import reader as prompts_reader
from domain.plots import create_plot, delete_plot, list_plot_characters


class PlotDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data"
        self.conn = connect(Path(self.temp.name) / "test.sqlite")
        init_db(self.conn)
        create_plot(self.conn, {
            "id": "plot-1",
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "characters": [
                {"id": "char-1", "type": "character", "name": "첫째", "sourceText": "첫째 설명"},
                {"id": "char-2", "type": "character", "name": "둘째", "sourceText": "둘째 설명"},
            ],
        }, root=self.root)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_delete_plot_also_deletes_all_its_characters(self):
        (self.root / "plots" / "plot-1.json").write_text("{}", encoding="utf-8")
        (self.root / "characters" / "char-1.json").write_text("{}", encoding="utf-8")
        result = delete_plot(self.conn, "plot-1", root=self.root)

        self.assertEqual(result, {"id": "plot-1", "deleted": True})
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.PLOT, "plot-1"))
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.CHARACTER, "char-1"))
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.CHARACTER, "char-2"))
        self.assertFalse((self.root / "plots" / "plot-1.md").exists())
        self.assertFalse((self.root / "plots" / "plot-1.json").exists())
        self.assertFalse((self.root / "characters" / "char-1.md").exists())
        self.assertFalse((self.root / "characters" / "char-1.json").exists())
        self.assertFalse((self.root / "characters" / "char-2.md").exists())

    def test_delete_plot_with_conversation_deletes_conversation_first(self):
        conversation = create_conversation(self.conn, "plot-1")

        delete_plot(self.conn, "plot-1", root=self.root)

        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM conversations WHERE id=:id", {"id": conversation["conversationId"]}
        ).fetchone())

    def test_delete_last_character_is_rejected(self):
        delete_character(self.conn, "char-2", root=self.root)
        self.conn.commit()

        with self.assertRaises(Conflict):
            delete_character(self.conn, "char-1", root=self.root)

        self.assertEqual(len(list_plot_characters(self.conn, "plot-1")), 1)

    def test_prompt_contains_one_character_block_per_plot_character(self):
        self.conn.execute(
            "INSERT INTO user_profiles (id, name, profile_json, source_text, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("user-1", "사용자", json.dumps({"id": "user-1", "type": "user_profile", "name": "사용자", "sourceText": ""}), "", "t", "t"),
        )
        conversation = create_conversation(self.conn, "plot-1", user_profile_id="user-1")
        self.conn.commit()
        prompt_template = {
            "system": {"description": "system", "content": []},
            "story": {"description": "story", "observer_char": "observer"},
            "style": {"description": "style"},
            "mandatory_rules": {"description": "rules", "content": []},
            "output_format": {"description": "format", "content": []},
            "current_input_description": "input",
            "empty_input_directive": "empty",
            "summary_description": "summary",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "system.json"
            prompt_path.write_text(json.dumps(prompt_template), encoding="utf-8")
            with patch.object(
                prompts_reader,
                "_SYSTEM_PROMPT_PATHS",
                {PromptTier.EXTERNAL: prompt_path, PromptTier.LOCAL: prompt_path},
            ):
                built = prompts_reader.build_prompt(
                    self.conn,
                    conversation["conversationId"],
                    "",
                    tier=PromptTier.EXTERNAL,
                )

        self.assertEqual(built.system.count('<char name="'), 3)
        self.assertIn('<char name="첫째" role="assistant">', built.system)
        self.assertIn('<char name="둘째" role="assistant">', built.system)
        self.assertIn("첫째 설명", built.system)
        self.assertIn("둘째 설명", built.system)


class PlotCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data"
        self.conn = connect(Path(self.temp.name) / "test.sqlite")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _body(self, characters):
        return {
            "id": "plot-1",
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "characters": characters,
        }

    def test_empty_characters_are_rejected(self):
        with self.assertRaises(ValueError):
            create_plot(self.conn, self._body([]), root=self.root)
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.PLOT, "plot-1"))

    def test_more_than_ten_characters_are_rejected(self):
        characters = [
            {"id": f"char-{index}", "type": "character", "name": str(index), "sourceText": str(index)}
            for index in range(11)
        ]
        with self.assertRaises(ValueError):
            create_plot(self.conn, self._body(characters), root=self.root)
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.PLOT, "plot-1"))

    def test_character_failure_rolls_back_plot_and_previous_characters(self):
        characters = [
            {"id": "char-1", "type": "character", "name": "첫째", "sourceText": "첫째"},
            {"id": "char-1", "type": "character", "name": "중복", "sourceText": "중복"},
        ]
        with self.assertRaises(ValueError):
            create_plot(self.conn, self._body(characters), root=self.root)

        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.PLOT, "plot-1"))
        self.assertFalse(is_catalog_exists(self.conn, CatalogKind.CHARACTER, "char-1"))
        self.assertFalse((self.root / "plots" / "plot-1.md").exists())
        self.assertFalse((self.root / "characters" / "char-1.md").exists())


if __name__ == "__main__":
    unittest.main()
