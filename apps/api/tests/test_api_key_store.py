import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.auth.api_key_store import delete_api_key, resolve_api_key, save_api_key, stored_key_source
from ai.providers.anthropic import AnthropicProvider
from ai.providers.gemini import GeminiProvider
from ai.providers.openai import OpenAIProvider
from ai.specs import ProviderName
from core import secrets


class ApiKeyStoreTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._data_root_patch = patch.object(secrets, "DATA_ROOT", Path(self._temporary_directory.name))
        self._data_root_patch.start()
        self._environment_patch = patch.dict(os.environ, {}, clear=True)
        self._environment_patch.start()

    def tearDown(self):
        self._environment_patch.stop()
        self._data_root_patch.stop()
        self._temporary_directory.cleanup()

    def _secrets_directory(self) -> Path:
        return Path(self._temporary_directory.name) / "secrets"

    def _secrets_path(self) -> Path:
        return self._secrets_directory() / "provider_keys.json"

    def test_saved_key_is_returned(self):
        save_api_key(ProviderName.OPENAI, "stored-key")

        self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "stored-key")

    def test_environment_key_is_returned_and_whitespace_is_missing(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": " env-key "}, clear=True):
            self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "env-key")

        with patch.dict(os.environ, {"OPENAI_API_KEY": " \n\t"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is missing"):
                resolve_api_key("OPENAI_API_KEY")

    def test_saved_key_overrides_environment_key(self):
        save_api_key(ProviderName.OPENAI, "stored-key")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "stored-key")

    def test_missing_saved_and_environment_keys_raise(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is missing"):
            resolve_api_key("OPENAI_API_KEY")

    def test_invalid_keys_and_provider_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "api key must not be empty"):
            save_api_key(ProviderName.OPENAI, " \n")
        with self.assertRaisesRegex(ValueError, "api key is too long"):
            save_api_key(ProviderName.OPENAI, "x" * 4097)
        with self.assertRaisesRegex(ValueError, "api key is not supported for provider"):
            save_api_key(ProviderName.OLLAMA, "ollama-key")
        with self.assertRaisesRegex(ValueError, "api key is not supported for provider"):
            delete_api_key(ProviderName.OLLAMA)

    def test_saved_key_is_trimmed(self):
        save_api_key(ProviderName.OPENAI, " sk-x\n")

        self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "sk-x")
        self.assertEqual(json.loads(self._secrets_path().read_text()), {"OPENAI_API_KEY": "sk-x"})

    def test_keys_for_multiple_providers_are_preserved(self):
        save_api_key(ProviderName.OPENAI, "openai-key")
        save_api_key(ProviderName.ANTHROPIC, "anthropic-key")

        self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "openai-key")
        self.assertEqual(resolve_api_key("ANTHROPIC_API_KEY"), "anthropic-key")

    def test_delete_returns_to_environment_and_is_idempotent(self):
        save_api_key(ProviderName.OPENAI, "stored-key")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            delete_api_key(ProviderName.OPENAI)
            self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "env-key")
            delete_api_key(ProviderName.OPENAI)
            self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "env-key")

    def test_invalid_json_and_non_object_json_use_environment_fallback(self):
        self._secrets_directory().mkdir(parents=True)
        for payload in ("{", "[]", "null"):
            self._secrets_path().write_text(payload, encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
                with self.assertLogs("core.secrets", level="WARNING") as logs:
                    self.assertEqual(resolve_api_key("OPENAI_API_KEY"), "env-key")
            self.assertEqual(len(logs.output), 1)

    def test_stored_key_source_has_three_states(self):
        self.assertIsNone(stored_key_source("OPENAI_API_KEY"))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            self.assertEqual(stored_key_source("OPENAI_API_KEY"), "env")
        save_api_key(ProviderName.OPENAI, "stored-key")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            self.assertEqual(stored_key_source("OPENAI_API_KEY"), "stored")

    def test_secret_file_and_directory_permissions_are_private(self):
        save_api_key(ProviderName.OPENAI, "stored-key")

        self.assertEqual(stat.S_IMODE(self._secrets_directory().stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self._secrets_path().stat().st_mode), 0o600)

    def test_temporary_files_are_removed_after_success_and_failure(self):
        save_api_key(ProviderName.OPENAI, "stored-key")
        self.assertEqual(list(self._secrets_directory().iterdir()), [self._secrets_path()])

        with patch.object(secrets.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                save_api_key(ProviderName.OPENAI, "next-key")
        self.assertEqual(list(self._secrets_directory().iterdir()), [self._secrets_path()])


class ApiKeyProviderConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._data_root_patch = patch.object(secrets, "DATA_ROOT", Path(self._temporary_directory.name))
        self._data_root_patch.start()
        self._environment_patch = patch.dict(os.environ, {}, clear=True)
        self._environment_patch.start()

    def tearDown(self):
        self._environment_patch.stop()
        self._data_root_patch.stop()
        self._temporary_directory.cleanup()

    async def test_api_key_provider_connections_report_stored_source(self):
        providers = (
            (ProviderName.OPENAI, OpenAIProvider),
            (ProviderName.ANTHROPIC, AnthropicProvider),
            (ProviderName.GEMINI, GeminiProvider),
        )
        for provider, provider_class in providers:
            save_api_key(provider, f"{provider.value}-key")
            connection = await provider_class().connection()
            self.assertEqual(connection.status, "connected")
            self.assertEqual(connection.key_source, "stored")
            delete_api_key(provider)

    async def test_api_key_provider_connections_report_environment_source(self):
        env_names = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
        providers = (OpenAIProvider, AnthropicProvider, GeminiProvider)
        for env_name, provider_class in zip(env_names, providers):
            with patch.dict(os.environ, {env_name: "env-key"}, clear=True):
                connection = await provider_class().connection()
            self.assertEqual(connection.status, "connected")
            self.assertEqual(connection.key_source, "env")

    async def test_api_key_provider_connections_require_a_key(self):
        providers = (OpenAIProvider, AnthropicProvider, GeminiProvider)
        for provider_class in providers:
            connection = await provider_class().connection()
            self.assertEqual(connection.status, "disconnected")
            self.assertEqual(connection.action_required, "api_key_required")
            self.assertIsNone(connection.key_source)


if __name__ == "__main__":
    unittest.main()
