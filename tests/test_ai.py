import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ai import (AIError, Suggestion, apply_suggestions, build_manual_prompt,
                             parse_manual_response, suggest_equivalences, validate_suggestion)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class AITests(unittest.TestCase):
    def test_manual_prompt_and_response_keep_only_approved_process_fields(self):
        options = {"wall_loops": "2", "machine_start_gcode": "G28"}
        prompt = build_manual_prompt({"unknown_wall": "3", "machine_start_gcode": "SECRET"},
                                     options, {"printer_model": "Bambu Lab P1S", "mesh": "GEOMETRY"},
                                     "Resistência", "Funcional", "encaixe justo")
        self.assertIn("Resistência", prompt)
        self.assertNotIn("SECRET", prompt)
        self.assertNotIn("GEOMETRY", prompt)
        response = json.dumps({"suggestions": [
            {"kind": "mapping", "source_key": "unknown_wall", "target_key": "wall_loops",
             "value": "4", "reason": "Mais paredes", "confidence": "medium"},
            {"kind": "feature", "source_key": "", "target_key": "machine_start_gcode",
             "value": "M500", "reason": "Inseguro", "confidence": "high"},
            {"kind": "mapping", "source_key": "invented", "target_key": "wall_loops",
             "value": "5", "reason": "Campo ausente", "confidence": "high"}]})
        suggestions = parse_manual_response(f"```json\n{response}\n```", {"unknown_wall": "3"}, options)
        self.assertEqual([(s.target_key, s.value) for s in suggestions], [("wall_loops", "4")])

    def test_request_sends_only_short_text_settings_and_parses_json(self):
        captured = {}

        def transport(request, timeout):
            captured["body"] = request.data.decode()
            captured["url"] = request.full_url
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": json.dumps({"suggestions": [
                {"kind": "mapping", "source_key": "bambu_unknown", "target_key": "wall_loops",
                 "value": "3", "reason": "Mantém paredes", "confidence": "medium"}
            ]})}]}}]})

        suggestions = suggest_equivalences(
            {"bambu_unknown": "3", "machine_start_gcode": "SECRET_GCODE", "huge": "X" * 500},
            {"wall_loops": "2", "enable_support": "0"},
            {"printer_model": "Bambu Lab P1S", "mesh": "SECRET_GEOMETRY"},
            "fake-key", transport=transport)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target_key, "wall_loops")
        self.assertNotIn("SECRET_GCODE", captured["body"])
        self.assertNotIn("SECRET_GEOMETRY", captured["body"])
        self.assertNotIn("X" * 500, captured["body"])
        self.assertIn("gemini", captured["url"])

    def test_rejects_unknown_key_and_unsafe_value(self):
        allowed = {"wall_loops": "2", "machine_start_gcode": "G28"}
        self.assertFalse(validate_suggestion(Suggestion("mapping", "x", "invented", "3", "", "high"), allowed))
        self.assertFalse(validate_suggestion(Suggestion("feature", "", "machine_start_gcode", "M500", "", "high"), allowed))
        self.assertFalse(validate_suggestion(Suggestion("mapping", "x", "wall_loops", "500", "", "high"), allowed))
        self.assertTrue(validate_suggestion(Suggestion("mapping", "x", "wall_loops", "3", "", "high"), allowed))

    def test_network_failure_is_explained(self):
        def transport(*_args, **_kwargs):
            raise OSError("offline")

        with self.assertRaisesRegex(AIError, "rede"):
            suggest_equivalences({"x": "1"}, {"wall_loops": "2"}, {}, "key", transport=transport)

    def test_applies_only_valid_approved_suggestions(self):
        original = {"wall_loops": "2", "machine_start_gcode": "G28"}
        approved = [Suggestion("mapping", "x", "wall_loops", "3", "", "high")]
        result = apply_suggestions(original, approved)
        self.assertEqual(result["wall_loops"], "3")
        self.assertEqual(original["wall_loops"], "2")
        with self.assertRaises(AIError):
            apply_suggestions(original, [Suggestion("feature", "", "machine_start_gcode", "M500", "", "high")])
