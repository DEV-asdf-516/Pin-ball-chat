import unittest
from unittest.mock import AsyncMock, Mock, patch

from ai.connections import logout_provider
from ai.errors import ProviderConnectionBusyError
from ai.providers.base import LoginCapableProvider
from core.errors import Conflict


class LogoutProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_provider_logout_is_reported_as_conflict(self):
        busy_provider = Mock(spec=LoginCapableProvider)
        busy_provider.logout = AsyncMock(side_effect=ProviderConnectionBusyError("cannot log out while a Claude generation is running"))

        with patch("ai.connections.get_provider", return_value=busy_provider):
            with self.assertRaises(Conflict):
                await logout_provider("claude-cli")


if __name__ == "__main__":
    unittest.main()
