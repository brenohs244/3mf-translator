"""Testes para Tasks 10, 11 e 14: diálogo do Professor, rótulos de IA e resumo para impressão."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import Advice, PrintGoal, advise_offline, build_print_summary
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.settings import load_settings
from maker_elegoo.ui import MakerElegooApp


class UIProfessorTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.fil_pla = Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {})
        self.fil_abs = Profile("Elegoo ABS @ECC2", "filament", Path("abs.json"), {})
        self.project = ProjectInfo(
            Path("sample.3mf"),
            {"printer_model": "Bambu Lab X1C", "layer_height": "0.20"},
            (FilamentInfo(1, "PLA", "#FFFFFF", "PLA"),),
            (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            ("Bracket",),
            (),
            (),
            used_filament_slots=("1",),
        )
        self.plan_abs = ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(self.fil_abs,),
            machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]},
            process_settings={
                "wall_loops": "2",
                "top_shell_layers": "3",
                "bottom_shell_layers": "3",
                "sparse_infill_density": "15%",
                "sparse_infill_pattern": "grid",
                "layer_height": "0.2",
                "outer_wall_speed": "160",
                "inner_wall_speed": "200",
                "brim_type": "no_brim",
                "brim_width": "5",
            },
            filament_settings=({
                "filament_type": ["ABS"],
                "fan_max_speed": ["40"],
                "overhang_fan_speed": ["80"],
                "additional_cooling_fan_speed": ["0"],
                "during_print_exhaust_fan_speed": ["70"],
            },),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        self.plan_pla = ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(self.fil_pla,),
            machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]},
            process_settings=dict(self.plan_abs.process_settings),
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )

    def test_build_print_summary_for_abs_and_pla(self):
        abs_advices = advise_offline(self.project, self.plan_abs, PrintGoal("esforco", "equilibrio"))
        summary_abs = build_print_summary(self.project, self.plan_abs, PrintGoal("esforco", "equilibrio"), abs_advices)
        self.assertIn("PLA → ABS", summary_abs)
        self.assertNotIn("garant", summary_abs.lower())
        for heading in (
            "verificado no 3mf",
            "verificado pelo fatiamento",
            "estimado por regra/ia",
            "depende de teste físico",
            "fatiar não prova acabamento",
        ):
            self.assertIn(heading, summary_abs.lower())
        self.assertIn("4 paredes", summary_abs.lower())
        self.assertIn("30%", summary_abs)
        self.assertIn("conferir no elegoo slicer", summary_abs.lower())

        pla_advices = advise_offline(self.project, self.plan_pla, PrintGoal("decorativa", "qualidade"))
        summary_pla = build_print_summary(self.project, self.plan_pla, PrintGoal("decorativa", "qualidade"), pla_advices)
        self.assertIn("PLA → PLA", summary_pla)
        self.assertIn("decorativa", summary_pla.lower())
        self.assertIn("0.12", summary_pla)

    def test_professor_dialog_separates_adjustments_from_alerts_and_shows_summary(self):
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
                p.write_text(json.dumps(payload), encoding="utf-8")

            with patch.dict(os.environ, {
                "APPDATA": str(root / "AppData"),
                "ProgramFiles": str(root / "ProgramFiles"),
                "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs"),
            }):
                app = MakerElegooApp()
                try:
                    app.project = self.project
                    # Task 11: verificar clareza dos rótulos de IA e persistência de preferências
                    self.assertIn("Codex", app.ai_button.cget("text"))
                    app.mode_var.set("ai")
                    saved = load_settings()
                    self.assertEqual(saved["mode"], "ai")

                    advices = [
                        Advice("process", None, "wall_loops", "2", "4", "Reforço de Paredes", "Mais força", True),
                        Advice("alert", None, "", "", "", "Câmara e Ambiente para ABS", "Feche a tampa", False),
                    ]
                    dialog = app._show_professor_dialog(self.plan_abs, str(root / "out.3mf"), advices)
                    try:
                        section_titles = []
                        def collect_labelframes(widget):
                            for child in widget.winfo_children():
                                if child.winfo_class() == "TLabelframe":
                                    section_titles.append(child.cget("text"))
                                collect_labelframes(child)
                        collect_labelframes(dialog)
                        self.assertIn("Resumo para impressão", section_titles)
                        self.assertIn("Ajustes recomendados", section_titles)
                        self.assertIn("Avisos e dicas", section_titles)
                    finally:
                        if dialog and dialog.winfo_exists():
                            dialog.destroy()
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
