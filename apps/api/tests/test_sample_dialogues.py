import functools
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Callable, Generator
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from httpx import Response
from starlette.testclient import TestClient

from ai.specs import PromptTier
from core.db.sqlite import connect, init_db
from domain import plots as plots_domain
from domain.catalog.importer import import_catalog
from domain.conversations.writer import create_conversation
from domain.plots import create_plot, update_plot
from domain.prompts.system import reader as prompts_reader
from domain.prompts.system.reader import BuiltPrompt
from server.dependencies import get_db_conn
from server.errors import register_error_handlers
from server.routes.plots import router
from util.catalog_util import LoadedCatalog, load_catalog_file


INVALID_SAMPLE_DIALOGUE_CASES: tuple[tuple[str, object], ...] = (
    ("top-level string", "bad"),
    ("top-level list", ["bad"]),
    ("top-level number", 7),
    ("truthy blocks dict", {"blocks": {"nested": True}}),
    ("truthy blocks string", {"blocks": "bad"}),
    ("falsy blocks empty string", {"blocks": ""}),
    ("falsy blocks empty dict", {"blocks": {}}),
    ("falsy blocks zero", {"blocks": 0}),
    ("falsy blocks null", {"blocks": None}),
    ("non-object block", {"blocks": ["bad"]}),
    ("invalid block type", {"blocks": [{"type": "system", "content": "내용"}]}),
    ("empty block content", {"blocks": [{"type": "user", "content": ""}]}),
    ("non-string block content", {"blocks": [{"type": "user", "content": 7}]}),
)


class SampleDialoguesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory: tempfile.TemporaryDirectory = tempfile.TemporaryDirectory()
        self.root: Path = Path(self.temporary_directory.name) / "data"
        self.connection: sqlite3.Connection = connect(Path(self.temporary_directory.name) / "test.sqlite")
        init_db(self.connection)

        fixture_plot_body: dict = {
            "id": "plot-1",
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "characters": [
                {"id": "char-1", "type": "character", "name": "주인공", "sourceText": "캐릭터 설명"},
            ],
        }
        create_plot(self.connection, fixture_plot_body, root=self.root)
        self.connection.execute(
            "INSERT INTO user_profiles (id, name, profile_json, created_at, updated_at) VALUES (?,?,?,?,?)",
            (
                "user-1",
                "유저",
                json.dumps({"id": "user-1", "type": "user_profile", "sourceText": "", "name": "유저"}),
                "t",
                "t",
            ),
        )
        self.connection.commit()
        self.conversation: dict = create_conversation(self.connection, "plot-1", user_profile_id="user-1")
        self.connection.commit()

        self.application: FastAPI = FastAPI()
        register_error_handlers(self.application)
        self.application.include_router(router)

        def provide_fixture_connection() -> Generator[sqlite3.Connection, None, None]:
            yield self.connection

        self.application.dependency_overrides[get_db_conn] = provide_fixture_connection

        create_plot_handler: Callable[..., dict] = functools.partial(plots_domain.create_plot, root=self.root)
        update_plot_handler: Callable[..., dict] = functools.partial(plots_domain.update_plot, root=self.root)
        self._create_plot_patch: object = patch("server.routes.plots.create_plot", new=create_plot_handler)
        self._update_plot_patch: object = patch("server.routes.plots.update_plot", new=update_plot_handler)
        self._create_plot_patch.start()
        self._update_plot_patch.start()
        self.client: TestClient = TestClient(self.application)

    def tearDown(self) -> None:
        self.client.close()
        self.application.dependency_overrides.clear()
        self._update_plot_patch.stop()
        self._create_plot_patch.stop()
        self.connection.close()
        self.temporary_directory.cleanup()

    def _valid_sample_dialogues(self) -> dict:
        return {
            "blocks": [
                {"type": "user", "content": "{{user}}는 {{char}}에게 손을 뻗었다."},
                {"type": "assistant", "content": "{{char}}가 {{user}}를 바라봤다."},
            ],
        }

    def _stored_plot_json(self, plot_id: str) -> dict:
        row: sqlite3.Row | None = self.connection.execute(
            "SELECT plot_json FROM plots WHERE id=:id",
            {"id": plot_id},
        ).fetchone()
        if row is None:
            raise AssertionError(f"plot {plot_id} was not stored")
        plot_json: dict = json.loads(row["plot_json"])
        return plot_json

    def _build_prompt(self) -> BuiltPrompt:
        prompt_template: dict = {
            "system": {"description": "system", "content": []},
            "story": {"description": "story", "observer_char": "observer"},
            "style": {"description": "style"},
            "mandatory_rules": {"description": "rules", "content": []},
            "output_format": {"description": "format", "content": []},
            "current_input_description": "input",
            "empty_input_directive": "empty",
            "summary_description": "summary",
            "sample_dialogues_description": "samples",
        }
        conversation_id: str = self.conversation["conversationId"]

        with tempfile.TemporaryDirectory() as prompt_directory_name:
            prompt_path: Path = Path(prompt_directory_name) / "system.json"
            prompt_path.write_text(json.dumps(prompt_template), encoding="utf-8")
            prompt_paths: dict[PromptTier, Path] = {
                PromptTier.EXTERNAL: prompt_path,
                PromptTier.LOCAL: prompt_path,
            }
            with patch.object(prompts_reader, "_SYSTEM_PROMPT_PATHS", prompt_paths):
                built_prompt: BuiltPrompt = prompts_reader.build_prompt(
                    self.connection,
                    conversation_id,
                    "",
                    tier=PromptTier.EXTERNAL,
                )
        return built_prompt

    def test_create_and_update_roundtrip(self) -> None:
        sample_dialogues: dict = self._valid_sample_dialogues()
        plot_id: str = "plot-roundtrip"
        plot_body: dict = {
            "id": plot_id,
            "type": "plot",
            "title": "라운드트립",
            "sourceText": "플롯 설명",
            "characters": [
                {"id": "char-roundtrip", "type": "character", "name": "주인공", "sourceText": "캐릭터 설명"},
            ],
            "sampleDialogues": sample_dialogues,
        }

        create_plot(self.connection, plot_body, root=self.root)

        stored_plot_json: dict = self._stored_plot_json(plot_id)
        self.assertEqual(stored_plot_json["sampleDialogues"], sample_dialogues)
        plot_path: Path = self.root / "plots" / f"{plot_id}.md"
        loaded_catalog: LoadedCatalog = load_catalog_file(plot_path)
        self.assertEqual(loaded_catalog.data["sampleDialogues"], sample_dialogues)

        updated_sample_dialogues: dict = {
            "blocks": [
                {"type": "assistant", "content": "수정된 {{char}}의 말투"},
            ],
        }
        update_plot(
            self.connection,
            plot_id,
            {
                "type": "plot",
                "title": "라운드트립 수정",
                "sourceText": "수정된 플롯 설명",
                "genre": [],
                "sampleDialogues": updated_sample_dialogues,
            },
            root=self.root,
        )

        updated_plot_json: dict = self._stored_plot_json(plot_id)
        self.assertEqual(updated_plot_json["sampleDialogues"], updated_sample_dialogues)
        updated_catalog: LoadedCatalog = load_catalog_file(plot_path)
        self.assertEqual(updated_catalog.data["sampleDialogues"], updated_sample_dialogues)

    def test_invalid_shapes_rejected(self) -> None:
        case_number: int
        case_entry: tuple[str, object]
        for case_number, case_entry in enumerate(INVALID_SAMPLE_DIALOGUE_CASES):
            case_name: str
            sample_dialogues: object
            case_name, sample_dialogues = case_entry
            with self.subTest(operation="create", case=case_name):
                plot_body: dict = {
                    "id": f"plot-invalid-{case_number}",
                    "type": "plot",
                    "title": "잘못된 샘플",
                    "sourceText": "플롯 설명",
                    "characters": [
                        {
                            "id": f"char-invalid-{case_number}",
                            "type": "character",
                            "name": "주인공",
                            "sourceText": "캐릭터 설명",
                        },
                    ],
                    "sampleDialogues": sample_dialogues,
                }
                with self.assertRaises(ValueError):
                    create_plot(self.connection, plot_body, root=self.root)

            with self.subTest(operation="update", case=case_name):
                update_body: dict = {
                    "type": "plot",
                    "title": "플롯",
                    "sourceText": "플롯 설명",
                    "genre": [],
                    "sampleDialogues": sample_dialogues,
                }
                with self.assertRaises(ValueError):
                    update_plot(self.connection, "plot-1", update_body, root=self.root)

        missing_blocks_create_body: dict = {
            "id": "plot-valid-missing-blocks",
            "type": "plot",
            "title": "유효한 샘플",
            "sourceText": "플롯 설명",
            "characters": [
                {"id": "char-valid-missing-blocks", "type": "character", "name": "주인공", "sourceText": "캐릭터 설명"},
            ],
            "sampleDialogues": {},
        }
        create_plot(self.connection, missing_blocks_create_body, root=self.root)

        empty_blocks_create_body: dict = {
            "id": "plot-valid-empty-blocks",
            "type": "plot",
            "title": "유효한 샘플",
            "sourceText": "플롯 설명",
            "characters": [
                {"id": "char-valid-empty-blocks", "type": "character", "name": "주인공", "sourceText": "캐릭터 설명"},
            ],
            "sampleDialogues": {"blocks": []},
        }
        create_plot(self.connection, empty_blocks_create_body, root=self.root)

        update_without_blocks_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": {},
        }
        update_plot(self.connection, "plot-1", update_without_blocks_body, root=self.root)
        update_with_empty_blocks_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": {"blocks": []},
        }
        update_plot(self.connection, "plot-1", update_with_empty_blocks_body, root=self.root)

    def test_api_status_contract(self) -> None:
        case_number: int
        case_entry: tuple[str, object]
        for case_number, case_entry in enumerate(INVALID_SAMPLE_DIALOGUE_CASES):
            case_name: str
            sample_dialogues: object
            case_name, sample_dialogues = case_entry
            with self.subTest(operation="POST", case=case_name):
                create_body: dict = {
                    "id": f"plot-api-invalid-{case_number}",
                    "type": "plot",
                    "title": "API 샘플",
                    "sourceText": "플롯 설명",
                    "characters": [
                        {
                            "id": f"char-api-invalid-{case_number}",
                            "type": "character",
                            "name": "주인공",
                            "sourceText": "캐릭터 설명",
                        },
                    ],
                    "sampleDialogues": sample_dialogues,
                }
                create_response: Response = self.client.post("/api/plots", json=create_body)
                self.assertEqual(create_response.status_code, 400, create_response.text)

            with self.subTest(operation="PUT", case=case_name):
                update_body: dict = {
                    "type": "plot",
                    "title": "플롯",
                    "sourceText": "플롯 설명",
                    "genre": [],
                    "sampleDialogues": sample_dialogues,
                }
                update_response: Response = self.client.put("/api/plots/plot-1", json=update_body)
                self.assertEqual(update_response.status_code, 400, update_response.text)

        valid_create_bodies: tuple[tuple[str, dict], ...] = (
            ("valid", self._valid_sample_dialogues()),
            ("missing blocks", {}),
            ("empty blocks", {"blocks": []}),
        )
        case_number: int
        case_entry: tuple[str, dict]
        for case_number, case_entry in enumerate(valid_create_bodies):
            case_name: str
            sample_dialogues: dict
            case_name, sample_dialogues = case_entry
            with self.subTest(operation="POST", case=case_name):
                create_body: dict = {
                    "id": f"plot-api-valid-{case_number}",
                    "type": "plot",
                    "title": "API 샘플",
                    "sourceText": "플롯 설명",
                    "characters": [
                        {
                            "id": f"char-api-valid-{case_number}",
                            "type": "character",
                            "name": "주인공",
                            "sourceText": "캐릭터 설명",
                        },
                    ],
                    "sampleDialogues": sample_dialogues,
                }
                create_response: Response = self.client.post("/api/plots", json=create_body)
                self.assertEqual(create_response.status_code, 200, create_response.text)

        valid_case_entry: tuple[str, dict]
        for valid_case_entry in valid_create_bodies:
            case_name: str
            sample_dialogues: dict
            case_name, sample_dialogues = valid_case_entry
            with self.subTest(operation="PUT", case=case_name):
                update_body: dict = {
                    "type": "plot",
                    "title": "플롯",
                    "sourceText": "플롯 설명",
                    "genre": [],
                    "sampleDialogues": sample_dialogues,
                }
                update_response: Response = self.client.put("/api/plots/plot-1", json=update_body)
                self.assertEqual(update_response.status_code, 200, update_response.text)

    def test_prompt_includes_section(self) -> None:
        sample_dialogues: dict = self._valid_sample_dialogues()
        update_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": sample_dialogues,
        }
        update_plot(self.connection, "plot-1", update_body, root=self.root)

        built_prompt: BuiltPrompt = self._build_prompt()

        self.assertIn("<sample_dialogues>", built_prompt.system)
        self.assertIn('<sample role="user">', built_prompt.system)
        self.assertIn('<sample role="assistant">', built_prompt.system)
        self.assertIn("주인공", built_prompt.system)
        self.assertIn("유저", built_prompt.system)
        self.assertNotIn("{{char}}", built_prompt.system)
        self.assertNotIn("{{user}}", built_prompt.system)

    def test_prompt_omits_section_when_absent_or_empty(self) -> None:
        absent_prompt: BuiltPrompt = self._build_prompt()
        self.assertNotIn("<sample_dialogues>", absent_prompt.system)

        empty_sample_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": {"blocks": []},
        }
        update_plot(self.connection, "plot-1", empty_sample_body, root=self.root)
        empty_prompt: BuiltPrompt = self._build_prompt()
        self.assertNotIn("<sample_dialogues>", empty_prompt.system)

    def test_prompt_tolerates_unvalidated_import_data(self) -> None:
        imported_cases: tuple[tuple[str, object], ...] = (
            ("top-level string", "bad"),
            ("non-list blocks", {"blocks": "bad"}),
            ("non-object block", {"blocks": ["bad"]}),
        )
        plot_path: Path = self.root / "plots" / "plot-1.md"

        imported_case: tuple[str, object]
        for imported_case in imported_cases:
            case_name: str
            sample_dialogues: object
            case_name, sample_dialogues = imported_case
            with self.subTest(case=case_name):
                serialized_sample_dialogues: str = json.dumps(sample_dialogues, ensure_ascii=False)
                frontmatter_text: str = (
                    "---\n"
                    "id: plot-1\n"
                    "type: plot\n"
                    "title: 플롯\n"
                    f"sampleDialogues: {serialized_sample_dialogues}\n"
                    "---\n"
                    "플롯 설명\n"
                )
                plot_path.write_text(frontmatter_text, encoding="utf-8")

                import_errors: list[str] = import_catalog(self.connection, self.root)
                self.assertEqual(import_errors, [])
                built_prompt: BuiltPrompt = self._build_prompt()
                self.assertNotIn("<sample_dialogues>", built_prompt.system)

    def test_update_without_field_clears_it(self) -> None:
        sample_dialogues: dict = self._valid_sample_dialogues()
        with_sample_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": sample_dialogues,
        }
        update_plot(self.connection, "plot-1", with_sample_body, root=self.root)

        without_sample_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
        }
        update_plot(self.connection, "plot-1", without_sample_body, root=self.root)

        stored_plot_json: dict = self._stored_plot_json("plot-1")
        self.assertNotIn("sampleDialogues", stored_plot_json)
        loaded_catalog: LoadedCatalog = load_catalog_file(self.root / "plots" / "plot-1.md")
        self.assertNotIn("sampleDialogues", loaded_catalog.data)

    def test_api_put_omission_clears_field(self) -> None:
        sample_dialogues: dict = self._valid_sample_dialogues()
        seed_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
            "sampleDialogues": sample_dialogues,
        }
        seed_response: Response = self.client.put("/api/plots/plot-1", json=seed_body)
        self.assertEqual(seed_response.status_code, 200, seed_response.text)

        seed_response_plot_json: dict = json.loads(seed_response.json()["plot_json"])
        self.assertEqual(seed_response_plot_json["sampleDialogues"], sample_dialogues)

        omission_body: dict = {
            "type": "plot",
            "title": "플롯",
            "sourceText": "플롯 설명",
            "genre": [],
        }
        clear_response: Response = self.client.put("/api/plots/plot-1", json=omission_body)
        self.assertEqual(clear_response.status_code, 200, clear_response.text)

        response_plot_json: dict = json.loads(clear_response.json()["plot_json"])
        self.assertNotIn("sampleDialogues", response_plot_json)
        stored_plot_json: dict = self._stored_plot_json("plot-1")
        self.assertNotIn("sampleDialogues", stored_plot_json)
        loaded_catalog: LoadedCatalog = load_catalog_file(self.root / "plots" / "plot-1.md")
        self.assertNotIn("sampleDialogues", loaded_catalog.data)


if __name__ == "__main__":
    unittest.main()
