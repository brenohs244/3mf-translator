import gc
import json
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ai_client import GeminiClient, advise_gemini
from maker_elegoo.professor import PrintGoal
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class AIClientTest(unittest.TestCase):
    def setUp(self):
        self.project = ProjectInfo(
            Path("cube.3mf"),
            {"printer_model": "Bambu Lab X1C", "layer_height": "0.20", "wall_loops": "2"},
            (FilamentInfo(1, "PLA", "#FFFFFF", ""),),
            (PlateInfo(1, 1),), ("Cube",), (), ()
        )
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard", "process", Path("p.json"), {})
        self.filament = Profile("Elegoo ABS @ECC2", "filament", Path("f.json"), {})

        self.plan = ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(self.filament,),
            machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]},
            process_settings={"wall_loops": "2", "sparse_infill_density": "15%"},
            filament_settings=({"filament_type": ["ABS"], "fan_max_speed": ["40"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=()
        )

    def test_advise_gemini_parses_valid_schema(self):
        fake_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "advices": [
                                {
                                    "scope": "process",
                                    "slot": None,
                                    "key": "wall_loops",
                                    "proposed": "4",
                                    "title": "Aumentar Paredes",
                                    "why": "Mais paredes para absorver esforço mecânico.",
                                    "default_on": True
                                },
                                {
                                    "scope": "filament",
                                    "slot": 1,
                                    "key": "fan_max_speed",
                                    "proposed": "25",
                                    "title": "Reduzir Ventoinha ABS",
                                    "why": "Evita delaminação e melhora a fusão.",
                                    "default_on": True
                                }
                            ]
                        })
                    }]
                }
            }]
        }

        mock_transport = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_transport.return_value.__enter__.return_value = mock_response

        client = GeminiClient(api_key="TEST_KEY", transport=mock_transport)
        goal = PrintGoal(purpose="esforco", priority="equilibrio")
        advices = advise_gemini(client, self.project, self.plan, goal)

        self.assertEqual(len(advices), 2)
        self.assertEqual(advices[0].key, "wall_loops")
        self.assertEqual(advices[0].proposed, "4")
        self.assertEqual(advices[1].key, "fan_max_speed")
        self.assertEqual(advices[1].proposed, "25")

    def test_gemini_test_connection_and_429_status_and_layer_limits(self):
        from urllib import error
        from maker_elegoo.ai_client import GeminiClientError

        mock_ok = MagicMock()
        ok_resp = MagicMock()
        ok_resp.read.return_value = json.dumps({"models": [{"name": "models/gemini-3.8-flash"}]}).encode("utf-8")
        mock_ok.return_value.__enter__.return_value = ok_resp
        client = GeminiClient(api_key="KEY", transport=mock_ok)
        self.assertTrue(client.test_connection())

        captured = {}
        def mock_gen(req, timeout=35):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            raise error.HTTPError(req.full_url, 429, "Quota", {}, None)

        client_429 = GeminiClient(api_key="KEY", transport=mock_gen)
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", ResourceWarning)
            with self.assertRaises(GeminiClientError) as ctx:
                advise_gemini(client_429, self.project, self.plan, PrintGoal("esforco", "qualidade"))
            self.assertEqual(ctx.exception.status_code, 429)
            del ctx
            gc.collect()
        resource_warnings = [w for w in caught_warnings if issubclass(w.category, ResourceWarning)]
        self.assertEqual(resource_warnings, [])
        prompt_text = captured["body"]["contents"][0]["parts"][0]["text"]
        self.assertIn("min_layer_height_mm", prompt_text)
        self.assertIn("max_layer_height_mm", prompt_text)
