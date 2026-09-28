import io
import json
import os
import unittest
from unittest.mock import patch

from agent import IntentAgent


class GeminiIntentTests(unittest.TestCase):
    def test_local_parser_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            preferences, provider, warning = IntentAgent().understand("AI DEL with no midsem")
        self.assertEqual(provider, "deterministic")
        self.assertIsNone(warning)
        self.assertEqual(preferences["category"], "del")
        self.assertTrue(preferences["no_midsem"])

    def test_gemini_structured_response(self):
        preferences = {
            "category": "del", "keywords": ["artificial", "intelligence"],
            "no_attendance": False, "no_quiz": False, "no_midsem": True, "no_compre": False,
            "project_based": False, "open_book": False,
            "no_early_classes": False, "free_day": None, "makeup_requested": False,
        }
        response = {"candidates": [{"content": {"parts": [{"text": json.dumps(preferences)}]}}]}

        def fake_urlopen(request, timeout):
            self.assertIn("gemini-test:generateContent", request.full_url)
            self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
            payload = json.loads(request.data)
            self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
            self.assertEqual(payload["generationConfig"]["responseJsonSchema"],
                             __import__("agent").PREFERENCE_SCHEMA)
            return io.BytesIO(json.dumps(response).encode())

        env = {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-test"}
        with patch.dict(os.environ, env, clear=True), patch("urllib.request.urlopen", fake_urlopen):
            parsed, provider, warning = IntentAgent().understand("AI DEL with no midsem")
        self.assertEqual(parsed, preferences)
        self.assertEqual(provider, "gemini:gemini-test")
        self.assertIsNone(warning)

    def test_gemini_keywords_are_normalized(self):
        preferences = {
            "category": "del", "keywords": ["AI"], "no_attendance": False, "no_quiz": False,
            "no_midsem": False, "no_compre": False, "project_based": False,
            "open_book": False, "no_early_classes": False, "free_day": None,
            "makeup_requested": False,
        }
        response = {"candidates": [{"content": {"parts": [{"text": json.dumps(preferences)}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), \
                patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
            parsed, _, _ = IntentAgent().understand("AI DEL")
        self.assertEqual(parsed["keywords"], ["artificial", "intelligence"])


if __name__ == "__main__":
    unittest.main()
