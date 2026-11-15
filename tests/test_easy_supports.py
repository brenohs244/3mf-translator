"""Testes TDD para fórmula de suportes fáceis de remover e ativação padrão em decorativas."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.labels import LABELS
from maker_elegoo.mapping import ConversionPlan, TRANSFERABLE, build_conversion
from maker_elegoo.professor import (
    SAFE_PROCESS_KEYS,
    PrintGoal,
    advise_offline,
    apply_advice,
    build_print_summary,
    validate_change,
)
from maker_elegoo.profiles import Profile, SlicerInstall
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.supports import compute_easy_support_settings


class EasySupportFormulaTests(unittest.TestCase):
    def test_formula_scales_by_layer_height_nozzle_and_material(self):
        pla_012 = compute_easy_support_settings(0.12, 0.4, "PLA", support_type="tree(auto)")
        self.assertEqual(pla_012["support_top_z_distance"], "0.24")
        self.assertEqual(pla_012["support_bottom_z_distance"], "0.24")
        self.assertEqual(pla_012["support_object_xy_distance"], "0.5")
        self.assertEqual(pla_012["support_interface_top_layers"], "3")
        self.assertEqual(pla_012["support_interface_bottom_layers"], "2")
        self.assertEqual(pla_012["support_interface_spacing"], "0.3")
        self.assertEqual(pla_012["support_style"], "tree_slim")

        # Em 0.20 mm com independent_support_layer_height=0, acima de 0.20 o fatiador salta para 0.40 mm.
        pla_020 = compute_easy_support_settings(0.20, 0.4, "PLA", support_type="tree(auto)")
        self.assertEqual(pla_020["support_top_z_distance"], "0.2")
        self.assertEqual(pla_020["support_bottom_z_distance"], "0.2")
        self.assertEqual(pla_020["support_object_xy_distance"], "0.5")

        # Polímero pegajoso (ABS/PETG) amplia folga XY e espaçamento da interface; em 0.16 mm salta para 0.32 mm.
        abs_016 = compute_easy_support_settings(0.16, 0.4, "ABS", support_type="tree(auto)")
        self.assertEqual(abs_016["support_top_z_distance"], "0.32")
        self.assertEqual(abs_016["support_object_xy_distance"], "0.6")
        self.assertEqual(abs_016["support_interface_spacing"], "0.35")

        # Suporte normal adota estilo snug.
        norm_020 = compute_easy_support_settings(0.20, 0.4, "PETG", support_type="normal(auto)")
        self.assertEqual(norm_020["support_style"], "snug")
        self.assertEqual(norm_020["support_object_xy_distance"], "0.6")

        # Bico 0.2 mm e bico 0.8 mm respeitam limites proporcionais.
        nozzle_02 = compute_easy_support_settings(0.08, 0.2, "PLA", support_type="normal(auto)")
        self.assertEqual(nozzle_02["support_top_z_distance"], "0.16")
        self.assertEqual(nozzle_02["support_object_xy_distance"], "0.35")
        nozzle_08 = compute_easy_support_settings(0.40, 0.8, "ABS", support_type="normal(auto)")
        self.assertEqual(nozzle_08["support_top_z_distance"], "0.4")
        self.assertEqual(nozzle_08["support_object_xy_distance"], "1.2")

    def test_labels_and_transferable_include_easy_support_keys(self):
        for key in (
            "enable_support",
            "support_type",
            "support_style",
            "support_top_z_distance",
            "support_bottom_z_distance",
            "support_object_xy_distance",
            "support_interface_top_layers",
            "support_interface_bottom_layers",
            "support_interface_spacing",
        ):
            self.assertIn(key, LABELS)
            self.assertIn(key, SAFE_PROCESS_KEYS)
        for key in ("support_bottom_z_distance", "support_object_xy_distance", "support_interface_spacing"):
            self.assertIn(key, TRANSFERABLE)


class EasySupportMappingAndProfessorTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.fil_pla = Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {})
        self.fil_abs = Profile("Elegoo ABS @ECC2", "filament", Path("abs.json"), {})
        self.machine_settings = {
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
        }
        self.base_process = {
            "layer_height": "0.2",
            "wall_loops": "2",
            "top_shell_layers": "3",
            "bottom_shell_layers": "3",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "grid",
            "wall_generator": "classic",
            "outer_wall_speed": "160",
            "inner_wall_speed": "200",
            "top_surface_speed": "200",
            "brim_type": "no_brim",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
            "enable_support": "0",
            "support_type": "tree(auto)",
            "support_style": "default",
            "support_top_z_distance": "0.2",
            "support_bottom_z_distance": "0.2",
            "support_object_xy_distance": "0.35",
            "support_interface_top_layers": "2",
            "support_interface_bottom_layers": "2",
            "support_interface_spacing": "0.5",
        }
        self.project = ProjectInfo(
            Path("estudo.3mf"),
            {"layer_height": "0.2"},
            (FilamentInfo(1, "PLA", "#FFFFFF", "PLA"),),
            (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            ("Model",),
            (),
            (),
            used_filament_slots=("1",),
        )

    def _plan(self, *, material: str = "PLA", **proc_overrides) -> ConversionPlan:
        fil = self.fil_pla if material == "PLA" else self.fil_abs
        return ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(fil,),
            machine_settings=self.machine_settings,
            process_settings={**self.base_process, **proc_overrides},
            filament_settings=({"filament_type": [material], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )

    def test_build_conversion_embeds_easy_support_even_when_support_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            for rel, payload in [
                ("system/Elegoo/machine/ECC2/m.json", {
                    "type": "machine",
                    "name": "Elegoo Centauri Carbon 2 0.4 nozzle",
                    "printer_model": "Elegoo Centauri Carbon 2",
                    "nozzle_diameter": ["0.4"],
                }),
                ("system/Elegoo/process/ECC2/p.json", {
                    "type": "process",
                    "name": "0.12mm Fine @Elegoo CC2 0.4 nozzle",
                    "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                    "layer_height": "0.12",
                    "enable_support": "0",
                    "support_type": "tree(auto)",
                    "support_style": "default",
                    "support_top_z_distance": "0.2",
                    "support_bottom_z_distance": "0.2",
                    "support_object_xy_distance": "0.35",
                    "support_interface_top_layers": "2",
                    "support_interface_bottom_layers": "2",
                    "support_interface_spacing": "0.5",
                }),
                ("system/Elegoo/filament/Generic/f.json", {
                    "type": "filament",
                    "name": "Elegoo ABS @ECC2",
                    "filament_type": ["ABS"],
                    "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                }),
            ]:
                p = data_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(payload), encoding="utf-8")

            install = SlicerInstall(root / "elegoo-slicer.exe", data_dir)
            machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", data_dir / "system/Elegoo/machine/ECC2/m.json", {})
            process = Profile("0.12mm Fine @Elegoo CC2 0.4 nozzle", "process", data_dir / "system/Elegoo/process/ECC2/p.json", {})
            filament = Profile("Elegoo ABS @ECC2", "filament", data_dir / "system/Elegoo/filament/Generic/f.json", {})

            plan = build_conversion(self.project, install, machine, process, [filament])

        # Mesmo com enable_support='0', as distâncias já ficam gravadas no projeto conforme camada/bico/material.
        self.assertEqual(plan.process_settings["enable_support"], "0")
        self.assertEqual(plan.process_settings["support_top_z_distance"], "0.24")
        self.assertEqual(plan.process_settings["support_bottom_z_distance"], "0.24")
        self.assertEqual(plan.process_settings["support_object_xy_distance"], "0.6")
        self.assertEqual(plan.process_settings["support_interface_top_layers"], "3")
        self.assertEqual(plan.process_settings["support_interface_spacing"], "0.35")
        self.assertEqual(plan.process_settings["support_style"], "tree_slim")

    def test_decorative_enables_support_by_default_and_syncs_after_layer_height_change(self):
        plan = self._plan(enable_support="0", support_type="normal(auto)")
        advices = advise_offline(self.project, plan, PrintGoal("decorativa", "qualidade"))
        default_approved = [a for a in advices if a.default_on]
        applied = apply_advice(plan, default_approved)

        self.assertEqual(applied.process_settings["enable_support"], "1")
        self.assertEqual(applied.process_settings["support_type"], "tree(auto)")
        self.assertEqual(applied.process_settings["support_style"], "tree_slim")
        self.assertEqual(applied.process_settings["layer_height"], "0.12")
        # Recalculado para a camada final 0.12 mm (2x 0.12 = 0.24 mm), não 0.20 nem 0.16!
        self.assertEqual(applied.process_settings["support_top_z_distance"], "0.24")
        self.assertEqual(applied.process_settings["support_bottom_z_distance"], "0.24")
        self.assertEqual(applied.process_settings["support_object_xy_distance"], "0.5")
        self.assertEqual(applied.process_settings["support_interface_top_layers"], "3")
        self.assertEqual(applied.process_settings["support_interface_spacing"], "0.3")

        summary = build_print_summary(self.project, plan, PrintGoal("decorativa", "qualidade"), advices)
        self.assertIn("0.24", summary)
        self.assertIn("0.5", summary)

    def test_functional_keeps_support_off_but_updates_preconfigured_gaps(self):
        plan = self._plan(material="ABS", enable_support="0")
        advices = advise_offline(self.project, plan, PrintGoal("esforco", "qualidade"))
        applied = apply_advice(plan, [a for a in advices if a.default_on])

        self.assertEqual(applied.process_settings["enable_support"], "0")
        # Qualidade em funcional reduz camada para 0.16 mm; em ABS, folga Z sobe para 0.32 mm (2x 0.16) e XY para 0.6 mm.
        self.assertEqual(applied.process_settings["layer_height"], "0.16")
        self.assertEqual(applied.process_settings["support_top_z_distance"], "0.32")
        self.assertEqual(applied.process_settings["support_object_xy_distance"], "0.6")
        self.assertTrue(validate_change("process", "support_object_xy_distance", "0.6", plan))
        self.assertFalse(validate_change("process", "support_object_xy_distance", "2.5", plan))
        self.assertTrue(validate_change("process", "support_interface_spacing", "0.3", plan))
        self.assertFalse(validate_change("process", "support_interface_spacing", "1.5", plan))


if __name__ == "__main__":
    unittest.main()
