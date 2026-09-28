from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from recommender import CourseRecommender, parse_query


PREFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": ["string", "null"], "enum": ["cdc", "del", "huel", "opel", None]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "no_attendance": {"type": "boolean"}, "no_quiz": {"type": "boolean"},
        "no_midsem": {"type": "boolean"},
        "no_compre": {"type": "boolean"}, "project_based": {"type": "boolean"},
        "open_book": {"type": "boolean"}, "no_early_classes": {"type": "boolean"},
        "free_day": {"type": ["string", "null"], "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", None]},
        "makeup_requested": {"type": "boolean"},
    },
    "required": ["category", "keywords", "no_attendance", "no_quiz", "no_midsem", "no_compre",
                 "project_based", "open_book", "no_early_classes", "free_day", "makeup_requested"],
    "additionalProperties": False,
}


class IntentAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    def understand(self, query: str) -> tuple[dict[str, Any], str, str | None]:
        if not self.api_key:
            return parse_query(query), "deterministic", None
        payload = {
            "systemInstruction": {"parts": [{"text": (
                "Extract course-selection preferences. Do not infer academic eligibility, "
                "course categories, or facts absent from the query."
            )}]},
            "contents": [{"role": "user", "parts": [{"text": query}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": PREFERENCE_SCHEMA,
            },
        }
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps(payload).encode(), method="POST",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = json.load(response)
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            parsed["keywords"] = parse_query(" ".join(parsed.get("keywords", [])))["keywords"]
            local = parse_query(query)
            for field in ("no_attendance", "no_quiz", "no_midsem", "no_compre", "project_based",
                          "open_book", "no_early_classes", "makeup_requested"):
                parsed[field] = bool(parsed.get(field) or local[field])
            parsed["category"] = parsed.get("category") or local["category"]
            parsed["free_day"] = parsed.get("free_day") or local["free_day"]
            return parsed, f"gemini:{self.model}", None
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode()).get("error", {}).get("message", str(exc))
            except (ValueError, UnicodeDecodeError):
                detail = str(exc)
            return parse_query(query), "deterministic", f"Query parser unavailable: {detail}"
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, StopIteration) as exc:
            return parse_query(query), "deterministic", f"Query parser unavailable: {exc}"


class RecommendationAgent:
    def __init__(self, engine: CourseRecommender):
        self.engine = engine
        self.intent = IntentAgent()

    def run(self, profile: dict[str, Any], query: str, limit: int = 8) -> dict[str, Any]:
        preferences, provider, warning = self.intent.understand(query)
        result = self.engine.recommend(profile, query, limit, preferences)
        result["agent"] = {
            "intent_provider": provider,
            "warning": warning,
            "steps": [
                {"name": "understand_query", "status": "complete"},
                {"name": "calculate_requirements", "status": "complete"},
                {"name": "retrieve_current_offerings", "status": "complete"},
                {"name": "validate_categories_and_policy", "status": "complete"},
                {"name": "rank_supported_preferences", "status": "complete"},
                {"name": "attach_claim_evidence", "status": "complete"},
            ],
        }
        return result
