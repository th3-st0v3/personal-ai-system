from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import provider_capabilities


class ProviderCapabilitiesTests(unittest.TestCase):
    def test_capabilities_never_returns_secret_values(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "super-secret"}, clear=False):
            result = provider_capabilities.capabilities()
        text = str(result)
        self.assertNotIn("super-secret", text)
        openrouter = next(item for item in result["hosted"] if item["provider"] == "openrouter")
        self.assertTrue(openrouter["configured"])
        self.assertEqual(openrouter["credential_env"], "OPENROUTER_API_KEY")


if __name__ == "__main__":
    unittest.main()
