import os
import unittest

import chat_service


class TestChatProvider(unittest.TestCase):
    def test_known_profile_resolves(self):
        self.assertEqual(chat_service.validate_provider_config("profile:auto"), "openrouter/auto")

    def test_unknown_profile_fails_fast(self):
        with self.assertRaises(chat_service.ProviderConfigurationError):
            chat_service.validate_provider_config("profile:not-a-real-profile")

    def test_missing_key_fails_when_model_backed_chat_is_required(self):
        original = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with self.assertRaises(chat_service.ProviderConfigurationError):
                chat_service.validate_provider_config("openrouter/auto", require_key=True)
        finally:
            if original is not None:
                os.environ["OPENROUTER_API_KEY"] = original

    def test_invalid_model_identifier_is_rejected(self):
        with self.assertRaises(chat_service.ProviderConfigurationError):
            chat_service.validate_provider_config("bad\nmodel")


if __name__ == "__main__":
    unittest.main()
