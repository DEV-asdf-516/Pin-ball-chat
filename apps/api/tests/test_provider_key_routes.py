import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from core import secrets
from server.errors import register_error_handlers
from server.routes.provider_connections import router


class ProviderKeyRouteTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._data_root_patch = patch.object(secrets, "DATA_ROOT", Path(self._temporary_directory.name))
        self._data_root_patch.start()
        self._environment_patch = patch.dict(os.environ, {}, clear=True)
        self._environment_patch.start()

        self._app = FastAPI()
        register_error_handlers(self._app)
        self._app.include_router(router)
        self._client = TestClient(self._app)

    def tearDown(self):
        self._client.close()
        self._environment_patch.stop()
        self._data_root_patch.stop()
        self._temporary_directory.cleanup()

    def test_put_key_returns_no_content_and_get_exposes_only_key_source(self):
        key = "sk-route-test"

        response = self._client.put("/api/provider-connections/openai/key", json={"key": f" {key} "})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertNotIn(key, response.text)

        connection = self._client.get("/api/provider-connections/openai")
        self.assertEqual(connection.status_code, 200)
        self.assertEqual(connection.json()["keySource"], "stored")
        self.assertNotIn(key, connection.text)

    def test_delete_key_returns_to_environment_or_none(self):
        self._client.put("/api/provider-connections/openai/key", json={"key": "stored-key"})

        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            response = self._client.delete("/api/provider-connections/openai/key")
            connection = self._client.get("/api/provider-connections/openai")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(connection.json()["keySource"], "env")
        self.assertNotIn("stored-key", response.text)
        self.assertNotIn("stored-key", connection.text)

        self._client.delete("/api/provider-connections/openai/key")
        self.assertIsNone(self._client.get("/api/provider-connections/openai").json()["keySource"])

    def test_empty_key_is_rejected(self):
        response = self._client.put("/api/provider-connections/openai/key", json={"key": " \n"})

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertNotIn("\n", response.text)

    def test_unsupported_provider_is_rejected(self):
        response = self._client.put("/api/provider-connections/claude-cli/key", json={"key": "dummy-key"})

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertNotIn("dummy-key", response.text)

    def test_unknown_provider_path_is_enum_validation_error(self):
        response = self._client.put("/api/provider-connections/unknown-provider/key", json={"key": "dummy-key"})

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("dummy-key", response.text)

    def test_invalid_key_types_do_not_echo_key_input(self):
        for body in (
            {"key": ["sk-leak-test"]},
            {"key": {"a": "sk-leak-test"}},
        ):
            response = self._client.put("/api/provider-connections/openai/key", json=body)

            self.assertEqual(response.status_code, 422)
            self.assertNotIn("sk-leak-test", response.text)
            self.assertNotIn('"input"', response.text)


if __name__ == "__main__":
    unittest.main()
