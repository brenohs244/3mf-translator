import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.settings import (
    load_material_memory,
    load_settings,
    save_material_memory,
    save_settings,
    settings_path,
)


class SettingsTests(unittest.TestCase):
    def test_configuration_directory_can_be_overridden_for_portable_use(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": directory}):
            self.assertEqual(settings_path(), Path(directory) / "settings.json")

    def test_saves_preferences_but_never_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            save_settings({"nozzle": "0.8", "last_dir": "C:/models", "api_key": "SECRET"}, path)
            raw = path.read_text(encoding="utf-8")
            settings = load_settings(path)
        self.assertNotIn("SECRET", raw)
        self.assertEqual(settings["nozzle"], "0.8")
        self.assertEqual(settings["last_dir"], "C:/models")

    def test_persists_locally_available_nozzle_and_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            save_settings({"nozzle": "0.6", "machine": "My CC2"}, path)
            settings = load_settings(path)
        self.assertEqual(settings["nozzle"], "0.6")
        self.assertEqual(settings["machine"], "My CC2")

    def test_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            path.write_text("broken", encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings["nozzle"], "0.4")

    def test_includes_professor_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            settings = load_settings(path)
            self.assertEqual(settings.get("mode"), "offline")
            self.assertEqual(settings.get("purpose"), "decorativa")
            self.assertEqual(settings.get("priority"), "equilibrio")
            self.assertEqual(settings.get("ai_model"), "gemini-3.8-flash")

            save_settings({
                "mode": "ai",
                "purpose": "esforco",
                "priority": "economia",
                "ai_model": "gemini-3.5-flash-lite",
            }, path)
            updated = load_settings(path)
            self.assertEqual(updated.get("mode"), "ai")
            self.assertEqual(updated.get("purpose"), "esforco")
            self.assertEqual(updated.get("priority"), "economia")
            self.assertEqual(updated.get("ai_model"), "gemini-3.5-flash-lite")

    def test_section2_material_memory_defaults_roundtrip_and_resilience(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            initial = load_settings(path)
            self.assertEqual(initial.get("last_physical_material"), "")
            self.assertEqual(initial.get("last_material_readiness"), "carregado")
            self.assertEqual(load_material_memory(initial), {})

            encoded = save_material_memory({"PLA": "ENDER PLA", "ABS": "Elegoo ABS @ECC2"})
            save_settings({
                "nozzle": "0.4",
                "last_physical_material": "PLA",
                "last_material_readiness": "planejado",
                "last_profile_by_material": encoded,
            }, path)
            reloaded = load_settings(path)
            self.assertEqual(reloaded.get("last_physical_material"), "PLA")
            self.assertEqual(reloaded.get("last_material_readiness"), "planejado")
            self.assertEqual(load_material_memory(reloaded), {"PLA": "ENDER PLA", "ABS": "Elegoo ABS @ECC2"})

            # Valores inválidos caem nos defaults seguros
            save_settings({
                "last_material_readiness": "invalido",
                "last_profile_by_material": "[1, 2, 3]",
            }, path)
            sanitized = load_settings(path)
            self.assertEqual(sanitized.get("last_material_readiness"), "carregado")
            self.assertEqual(load_material_memory(sanitized), {})
