import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.registry import prompt_tier
from ai.specs import PromptTier
from core.db.sqlite import connect as _sqlite_connect, init_db
from domain.prompts.system import reader as prompts_reader


def _seed_conversation(conn) -> None:
    conn.execute(
        "INSERT INTO plots (id, title, plot_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        (
            "plot-1",
            "plot",
            json.dumps({"id": "plot-1", "type": "plot", "sourceText": "", "title": "plot"}),
            "t",
            "t",
        ),
    )
    conn.execute(
        "INSERT INTO characters (id, name, plot_id, sort_order, profile_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            "char-1",
            "char",
            "plot-1",
            0,
            json.dumps({"id": "char-1", "type": "character", "sourceText": "", "name": "char"}),
            "t",
            "t",
        ),
    )
    conn.execute(
        "INSERT INTO user_profiles (id, name, profile_json, created_at, updated_at) VALUES (?,?,?,?,?)",
        (
            "user-1",
            "user",
            json.dumps({"id": "user-1", "type": "user_profile", "sourceText": "", "name": "user"}),
            "t",
            "t",
        ),
    )
    conn.execute(
        "INSERT INTO conversations (id, plot_id, user_profile_id, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("conv-1", "plot-1", "user-1", "t", "t"),
    )
    conn.commit()


class PromptTierTests(unittest.TestCase):
    def test_local_providers_use_local_tier(self):
        for provider in ("ollama", "local-stub"):
            with self.subTest(provider=provider):
                self.assertIs(prompt_tier(provider, "model"), PromptTier.LOCAL)

    def test_external_providers_use_external_tier(self):
        for provider in ("anthropic", "claude-cli", "openai", "openai-codex", "gemini"):
            with self.subTest(provider=provider):
                self.assertIs(prompt_tier(provider, "model"), PromptTier.EXTERNAL)

    def test_missing_provider_uses_registry_default(self):
        with patch("ai.registry.DEFAULT_AI_PROVIDER", "ollama"):
            self.assertIs(prompt_tier(None, "model"), PromptTier.LOCAL)
        with patch("ai.registry.DEFAULT_AI_PROVIDER", "anthropic"):
            self.assertIs(prompt_tier(None, "model"), PromptTier.EXTERNAL)

    def test_local_stub_model_overrides_explicit_provider(self):
        self.assertIs(prompt_tier("anthropic", "local-stub"), PromptTier.LOCAL)

    def test_build_prompt_selects_prompt_file_for_tier(self):
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
            tmp_path = Path(tmpdir)
            external_path = tmp_path / "external.json"
            local_path = tmp_path / "local.json"
            external = prompt_template | {"system": {"description": "system", "content": ["external marker"]}}
            local = prompt_template | {"system": {"description": "system", "content": ["local marker"]}}
            external_path.write_text(json.dumps(external), encoding="utf-8")
            local_path.write_text(json.dumps(local), encoding="utf-8")

            conn = _sqlite_connect(tmp_path / "test.sqlite")
            try:
                init_db(conn)
                _seed_conversation(conn)
                with patch.object(
                    prompts_reader,
                    "_SYSTEM_PROMPT_PATHS",
                    {PromptTier.EXTERNAL: external_path, PromptTier.LOCAL: local_path},
                ):
                    external_prompt = prompts_reader.build_prompt(conn, "conv-1", "", tier=PromptTier.EXTERNAL)
                    local_prompt = prompts_reader.build_prompt(conn, "conv-1", "", tier=PromptTier.LOCAL)
            finally:
                conn.close()

        self.assertIn("external marker", external_prompt.system)
        self.assertNotIn("local marker", external_prompt.system)
        self.assertIn("local marker", local_prompt.system)
        self.assertNotIn("external marker", local_prompt.system)

    def test_unknown_provider_keeps_resolve_provider_error(self):
        with self.assertRaisesRegex(ValueError, "unknown ai provider"):
            prompt_tier("unknown-provider", "model")


if __name__ == "__main__":
    unittest.main()
