"""Testes TDD para Etapas 2 e 3: Professor v2, chaveiros, estudo 3MFs e guia na UI."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ai_client import advise_gemini
from maker_elegoo.converter import ConversionResult
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import (
    PURPOSES,
    SAFE_PROCESS_KEYS,
    PrintGoal,
    advise_offline,
    apply_advice,
    validate_change,
)
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, ObjectOverride, PlateInfo, ProjectInfo
from maker_elegoo.slicer import ExportResult, ValidationResult
from maker_elegoo.ui import MakerElegooApp, format_conversion_report, format_project_summary


class ProfessorV2AndKeychainsTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.fil_pla = Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {})
        self.machine_settings = {
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
        }
        self.base_process = {
            "wall_loops": "2",
            "wall_generator": "classic",
            "top_shell_layers": "3",
            "bottom_shell_layers": "3",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "grid",
            "layer_height": "0.2",
            "brim_type": "auto_brim",
            "brim_width": "5",
            "outer_wall_speed": "160",
            "inner_wall_speed": "200",
            "top_surface_speed": "200",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
            "enable_support": "0",
            "support_type": "normal(auto)",
            "support_style": "default",
            "support_top_z_distance": "0.2",
            "elefant_foot_compensation": "0.1",
        }
        self.base_filament = {"filament_type": ["PLA"], "fan_max_speed": ["100"]}
        self.project = ProjectInfo(
            Path("sample.3mf"),
            {"layer_height": "0.2"},
            (FilamentInfo(1, "PLA", "#FFFFFF", ""),),
            (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            ("Model",),
            (),
            (),
            used_filament_slots=("1",),
        )

    def _plan(self, **proc_overrides) -> ConversionPlan:
        return ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(self.fil_pla,),
            machine_settings=self.machine_settings,
            process_settings={**self.base_process, **proc_overrides},
            filament_settings=(dict(self.base_filament),),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )

    def test_validate_change_supports_new_process_keys_and_bounds(self):
        plan = self._plan()
        for key in ("wall_generator", "support_style", "support_top_z_distance",
                    "inner_wall_speed", "top_surface_speed", "elefant_foot_compensation"):
            self.assertIn(key, SAFE_PROCESS_KEYS)
        self.assertTrue(validate_change("process", "wall_generator", "arachne", plan))
        self.assertFalse(validate_change("process", "wall_generator", "magic", plan))
        self.assertTrue(validate_change("process", "support_style", "tree_slim", plan))
        self.assertFalse(validate_change("process", "support_style", "floating", plan))
        self.assertTrue(validate_change("process", "support_top_z_distance", "0.16", plan))
        self.assertFalse(validate_change("process", "support_top_z_distance", "0.02", plan))
        self.assertFalse(validate_change("process", "support_top_z_distance", "0.35", plan))
        self.assertTrue(validate_change("process", "inner_wall_speed", "120", plan))
        self.assertFalse(validate_change("process", "inner_wall_speed", "350", plan))
        self.assertTrue(validate_change("process", "top_surface_speed", "100", plan))
        self.assertFalse(validate_change("process", "top_surface_speed", "15", plan))
        self.assertTrue(validate_change("process", "elefant_foot_compensation", "0.15", plan))
        self.assertFalse(validate_change("process", "elefant_foot_compensation", "0.8", plan))

    def test_decorative_quality_refines_layers_arachne_speeds_and_per_object_tree_support(self):
        plan = self._plan(enable_support="1", support_type="tree(auto)")
        advices = advise_offline(self.project, plan, PrintGoal("decorativa", "qualidade"))
        by_key = {a.key: a.proposed for a in advices if a.key}
        self.assertEqual(by_key.get("layer_height"), "0.12")
        self.assertEqual(by_key.get("wall_loops"), "3")
        self.assertEqual(by_key.get("wall_generator"), "arachne")
        self.assertEqual(by_key.get("outer_wall_speed"), "60")
        self.assertEqual(by_key.get("inner_wall_speed"), "120")
        self.assertEqual(by_key.get("top_surface_speed"), "100")
        self.assertEqual(by_key.get("support_style"), "tree_slim")
        self.assertEqual(by_key.get("support_top_z_distance"), "0.16")

        # Suporte via object_override quando global está desligado
        proj_obj_sup = ProjectInfo(
            Path("virgen.3mf"),
            {"layer_height": "0.2"},
            (FilamentInfo(1, "PLA", "#FFFFFF", ""),),
            (PlateInfo(1, 1, ("2",), ("1",), ("1",)),),
            ("virgen",),
            ("Metadata/layer_heights_profile.txt",),
            (),
            object_overrides=(ObjectOverride("2", "virgen", {"enable_support": "1", "support_type": "tree(auto)"}),),
        )
        plan_global_off = self._plan(enable_support="0")
        adv_obj = advise_offline(proj_obj_sup, plan_global_off, PrintGoal("decorativa", "qualidade"))
        obj_keys = {a.key: a.proposed for a in adv_obj if a.key}
        self.assertEqual(obj_keys.get("support_style"), "tree_slim")
        self.assertEqual(obj_keys.get("support_top_z_distance"), "0.16")
        self.assertTrue(any(a.scope == "alert" and "cli" in a.why.lower() and "detectada" in a.why.lower() for a in adv_obj))

        # Não-decorativa + qualidade mantém 0.16 e 80
        func_qual = advise_offline(self.project, self._plan(), PrintGoal("funcional_leve", "qualidade"))
        func_keys = {a.key: a.proposed for a in func_qual if a.key}
        self.assertEqual(func_keys.get("layer_height"), "0.16")
        self.assertEqual(func_keys.get("outer_wall_speed"), "80")

    def test_keychain_modes_rigid_and_articulated(self):
        self.assertIn("chaveiro_rigido", PURPOSES)
        self.assertIn("chaveiro_articulado", PURPOSES)

        # Rígido: melhora relevo/acabamento e preserva >=6 paredes
        plan_rigid = self._plan()
        adv_rigid = advise_offline(self.project, plan_rigid, PrintGoal("chaveiro_rigido", "equilibrio"))
        rigid_map = {a.key: a.proposed for a in adv_rigid if a.key}
        self.assertEqual(rigid_map.get("wall_generator"), "arachne")
        self.assertEqual(rigid_map.get("wall_loops"), "3")
        self.assertEqual(rigid_map.get("top_shell_layers"), "5")
        self.assertEqual(rigid_map.get("sparse_infill_density"), "25%")
        self.assertEqual(rigid_map.get("sparse_infill_pattern"), "gyroid")
        self.assertEqual(rigid_map.get("ironing_type"), "top")
        self.assertEqual(rigid_map.get("outer_wall_speed"), "60")
        self.assertTrue(any(a.scope == "alert" and "pausa" in a.why.lower() for a in adv_rigid))

        adv_preserve_walls = advise_offline(self.project, self._plan(wall_loops="6"), PrintGoal("chaveiro_rigido", "equilibrio"))
        self.assertNotIn("wall_loops", {a.key for a in adv_preserve_walls if a.key})

        # Articulado: anti-fusão e alertas de suporte/escala
        plan_art = self._plan(enable_support="1", ironing_type="top", brim_type="outer_only")
        adv_art = advise_offline(self.project, plan_art, PrintGoal("chaveiro_articulado", "equilibrio"))
        art_map = {a.key: a.proposed for a in adv_art if a.key}
        self.assertEqual(art_map.get("wall_generator"), "arachne")
        self.assertEqual(art_map.get("wall_loops"), "3")
        self.assertEqual(art_map.get("top_shell_layers"), "5")
        self.assertEqual(art_map.get("bottom_shell_layers"), "4")
        self.assertEqual(art_map.get("sparse_infill_density"), "20%")
        self.assertEqual(art_map.get("sparse_infill_pattern"), "gyroid")
        self.assertEqual(art_map.get("brim_type"), "no_brim")
        self.assertEqual(art_map.get("elefant_foot_compensation"), "0.15")
        self.assertEqual(art_map.get("ironing_type"), "no ironing")
        self.assertEqual(art_map.get("outer_wall_speed"), "70")
        self.assertTrue(any(a.scope == "alert" and "suporte" in a.title.lower() for a in adv_art))
        self.assertTrue(any(a.scope == "alert" and "100%" in a.why for a in adv_art))

    def test_study_alerts_low_infill_empty_manual_support_canvas_colors_and_elephant_foot(self):
        proj = ProjectInfo(
            Path("study.3mf"),
            {"layer_height": "0.2", "elefant_foot_compensation": "0", "enable_support": "1", "support_type": "normal(manual)"},
            tuple(FilamentInfo(i, "PLA", f"#{i}{i}{i}000", "") for i in range(1, 6)),
            (PlateInfo(1, 1, ("1",), ("1",), ("1", "2", "3", "4", "5"), has_paint_color=True),),
            ("Objeto A", "Objeto B"),
            (),
            (),
            advanced_features=("Suporte manual no arquivo sem pintagem/enforcers explícitos",),
            used_filament_slots=("1", "2", "3", "4", "5"),
        )
        plan = ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=tuple(self.fil_pla for _ in range(5)),
            machine_settings=self.machine_settings,
            process_settings={**self.base_process, "sparse_infill_density": "5%", "elefant_foot_compensation": "0.1"},
            filament_settings=tuple(dict(self.base_filament) for _ in range(5)),
            transferred={}, unmapped={}, replaced={"elefant_foot_compensation": "0"}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(proj, plan, PrintGoal("moveis", "equilibrio"))
        alert_text = " | ".join(f"{a.title} {a.why}".lower() for a in advices if a.scope == "alert")
        self.assertIn("5%", alert_text)
        self.assertIn("suporte manual", alert_text)
        self.assertIn("4 cores", alert_text)
        self.assertIn("pé de elefante", alert_text)

    def test_ui_summary_report_and_unused_slot_labels(self):
        proj = ProjectInfo(
            Path("canivete_plus.3mf"),
            {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
            (
                FilamentInfo(1, "PLA", "#111111", "PLA"),
                FilamentInfo(2, "PLA", "#222222", "PLA"),
                FilamentInfo(3, "PLA", "#333333", "PLA"),
                FilamentInfo(4, "PLA", "#444444", "PLA"),
                FilamentInfo(5, "PLA", "#555555", "PLA"),
            ),
            (
                PlateInfo(1, 2, ("1",), ("1",), ("1", "2", "3", "4", "5"), has_paint_color=True),
                PlateInfo(2, 1, ("2",), ("1",), ("1",)),
            ),
            ("Keychain", "Stand"),
            (),
            (),
            used_filament_slots=("1", "2", "3", "4", "5"),
        )
        summary = format_project_summary(proj)
        self.assertIn("Guia por Placa & Troca de Cores", summary)
        self.assertIn("Placa 1", summary)
        self.assertIn("5 cores", summary)

        #Unused slot label test in _render_filaments with unused slot 2
        proj_unused = ProjectInfo(
            Path("canivete.3mf"),
            {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
            (FilamentInfo(1, "PLA", "#111111", "PLA"), FilamentInfo(2, "PLA", "#222222", "PLA")),
            (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            ("Liner",),
            (),
            (),
            used_filament_slots=("1",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "AppData" / "ElegooSlicer"
            exe_dir = root / "ProgramFiles" / "ElegooSlicer"
            exe_dir.mkdir(parents=True)
            (exe_dir / "elegoo-slicer.exe").touch()
            for rel, payload in [
                ("system/Elegoo/machine/ECC2/m.json", {"type": "machine", "name": "Elegoo Centauri Carbon 2 0.4 nozzle", "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]}),
                ("system/Elegoo/process/ECC2/p.json", {"type": "process", "name": "0.20mm Standard", "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"]}),
                ("system/Elegoo/filament/Generic/f.json", {"type": "filament", "name": "Elegoo PLA @ECC2", "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"]}),
            ]:
                p = data_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                import json as _json
                p.write_text(_json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": str(root / "AppData"), "ProgramFiles": str(root / "ProgramFiles"), "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    app.project = proj_unused
                    app._render_filaments()
                    texts = [w.cget("text") for w in app.filament_frame.winfo_children() if w.winfo_class() == "TLabel"]
                    self.assertTrue(any("não usado" in t.lower() for t in texts))
                finally:
                    app.destroy()

        plan = ConversionPlan(
            machine=self.machine, process=self.process, filaments=(self.fil_pla,),
            machine_settings=self.machine_settings, process_settings=self.base_process,
            filament_settings=(self.base_filament,), transferred={}, unmapped={}, replaced={},
            source_repairs={}, material_findings=(),
        )
        result = ConversionResult(
            True, Path("out.3mf"), "ok", ExportResult(True, Path("out.3mf"), "ok"),
            ValidationResult(True, 1, "ok", (), 1200, 10.0), None, proj_unused, {}, proj_unused.plates,
        )
        report = format_conversion_report(result, plan)
        self.assertIn("Guia por Placa & Troca de Cores", report)

    def test_gemini_payload_includes_safe_new_process_keys(self):
        class FakeClient:
            def __init__(self):
                self.prompt = ""
            def generate_json(self, prompt: str):
                self.prompt = prompt
                return {"advices": [{"scope": "process", "key": "wall_generator", "proposed": "arachne", "title": "Arachne", "why": "Detalhes"}]}
        client = FakeClient()
        plan = self._plan()
        advices = advise_gemini(client, self.project, plan, PrintGoal("chaveiro_rigido", "qualidade"))
        self.assertIn("wall_generator", client.prompt)
        self.assertIn("chaveiro_rigido", client.prompt)
        self.assertEqual(len(advices), 1)
        self.assertEqual(advices[0].proposed, "arachne")


if __name__ == "__main__":
    unittest.main()
