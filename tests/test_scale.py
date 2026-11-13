"""Testes TDD para redimensionamento uniforme e detector de perda de qualidade (Etapa 5)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.geometry_check import analyze_project_geometry
from maker_elegoo.project import inspect_project
from maker_elegoo.scale import ScaleError, analyze_scale_risk, rescale_3mf
from maker_elegoo.ui import MakerElegooApp, format_conversion_report
from maker_elegoo.converter import ConversionResult
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.profiles import Profile
from maker_elegoo.slicer import ExportResult, ValidationResult
import os
from unittest.mock import patch


def _write_box_3mf(
    path: Path,
    *,
    x1: float = 40.0,
    y1: float = 40.0,
    z1: float = 120.0,
    items: int = 1,
    include_var_layer: bool = False,
) -> Path:
    verts = [
        (0, 0, 0), (x1, 0, 0), (x1, y1, 0), (0, y1, 0),
        (0, 0, z1), (x1, 0, z1), (x1, y1, z1), (0, y1, z1),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ]
    v_xml = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
    t_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    build_xml = "".join(
        f'<item objectid="1" transform="1 0 0 0 1 0 0 0 1 {100 + idx * 50} 100 10"/>'
        for idx in range(items)
    )
    entries = {
        "3D/3dmodel.model": (
            '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
            f'<resources><object id="1" type="model"><mesh><vertices>{v_xml}</vertices><triangles>{t_xml}</triangles></mesh></object></resources>'
            f'<build>{build_xml}</build></model>'
        ),
        "Metadata/project_settings.config": json.dumps({"layer_height": "0.20", "filament_type": ["PLA"]}),
        "Metadata/model_settings.config": '<config><plate><model_instance><metadata key="object_id" value="1"/></model_instance></plate></config>',
    }
    if include_var_layer:
        entries["Metadata/layer_heights_profile.txt"] = "0.0|0.12\n120.0|0.12\n"
    with ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class ScaleTests(unittest.TestCase):
    def test_rescale_by_target_height_centers_on_bed_and_drops_stale_var_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _write_box_3mf(root / "statue.3mf", x1=60.0, y1=50.0, z1=160.0, include_var_layer=True)
            dst = root / "statue_80mm.3mf"
            res = rescale_3mf(src, dst, target_height_mm=80.0, nozzle_mm=0.4, purpose="decorativa")

            self.assertAlmostEqual(res.scale_factor, 0.5, places=4)
            self.assertEqual(res.original_size_mm, (60.0, 50.0, 160.0))
            self.assertAlmostEqual(res.new_size_mm[0], 30.0, places=2)
            self.assertAlmostEqual(res.new_size_mm[1], 25.0, places=2)
            self.assertAlmostEqual(res.new_size_mm[2], 80.0, places=2)
            self.assertTrue(res.removed_variable_layer)

            geom = analyze_project_geometry(dst)
            self.assertAlmostEqual(geom.size_z, 80.0, places=2)
            self.assertAlmostEqual(geom.bounds[4], 0.0, places=2)  # Z_min = 0
            self.assertAlmostEqual((geom.bounds[0] + geom.bounds[1]) / 2.0, 128.0, places=1)
            self.assertAlmostEqual((geom.bounds[2] + geom.bounds[3]) / 2.0, 128.0, places=1)

            with ZipFile(dst) as zf:
                self.assertNotIn("Metadata/layer_heights_profile.txt", zf.namelist())
                model_xml = zf.read("3D/3dmodel.model").decode("utf-8")
                self.assertIn('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"', model_xml)

    def test_rescale_by_percentage_and_rejects_oversized_or_multi_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _write_box_3mf(root / "box.3mf", x1=150.0, y1=150.0, z1=150.0)
            with self.assertRaises(ScaleError):
                rescale_3mf(src, root / "huge.3mf", scale_percent=200.0)

            multi = _write_box_3mf(root / "two.3mf", items=2)
            with self.assertRaises(ScaleError):
                rescale_3mf(multi, root / "two_scaled.3mf", scale_percent=80.0)

            pct_dst = root / "pct.3mf"
            res = rescale_3mf(src, pct_dst, scale_percent=50.0)
            self.assertAlmostEqual(res.new_size_mm[2], 75.0, places=2)

    def test_analyze_scale_risk_flags_quality_loss_nozzle_02_and_articulated_lock(self):
        risk_small = analyze_scale_risk(
            0.5, (72.0, 56.0, 160.0), nozzle_mm=0.4, purpose="decorativa",
        )
        self.assertEqual(risk_small.recommend_finer_layer, "0.12")
        self.assertTrue(risk_small.recommend_nozzle_02)
        joined = " | ".join(risk_small.warnings).lower()
        self.assertIn("0.2", joined)
        self.assertIn("50%", joined)

        risk_flexi = analyze_scale_risk(
            0.8, (50.0, 40.0, 8.0), nozzle_mm=0.4, purpose="chaveiro_articulado",
        )
        self.assertTrue(any("folga" in w.lower() or "travar" in w.lower() for w in risk_flexi.warnings))

    def test_ui_scale_controls_and_report_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _write_box_3mf(root / "statue.3mf", x1=60.0, y1=50.0, z1=160.0, include_var_layer=True)
            dst = root / "scaled.3mf"
            res = rescale_3mf(src, dst, target_height_mm=80.0, nozzle_mm=0.4, purpose="decorativa")

            plan = ConversionPlan(
                machine=Profile("ECC2", "machine", Path("m.json"), {}),
                process=Profile("0.12mm", "process", Path("p.json"), {}),
                filaments=(Profile("PLA", "filament", Path("f.json"), {}),),
                machine_settings={}, process_settings={}, filament_settings=({},),
                transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
            )
            conv_res = ConversionResult(
                True, Path("out.3mf"), "ok", ExportResult(True, Path("out.3mf"), "ok"),
                ValidationResult(True, 1, "ok", (), 1200, 10.0), None, None, {},
            )
            report = format_conversion_report(conv_res, plan, rescale_info=res)
            self.assertIn("50.0%", report)
            self.assertIn("160.0 mm → 30.0×25.0×80.0 mm", report)
            self.assertIn("Curva antiga de altura variável removida", report)

            data_dir = root / "AppData" / "ElegooSlicer"
            exe_dir = root / "ProgramFiles" / "ElegooSlicer"
            exe_dir.mkdir(parents=True)
            (exe_dir / "elegoo-slicer.exe").touch()
            with patch.dict(os.environ, {"APPDATA": str(root / "AppData"), "ProgramFiles": str(root / "ProgramFiles"), "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    self.assertEqual(app._parse_scale_request(), (None, None))
                    app.scale_mode_var.set("Altura Z (mm)")
                    app.scale_value_var.set("80")
                    self.assertEqual(app._parse_scale_request(), (None, 80.0))
                    app.scale_mode_var.set("Escala (%)")
                    app.scale_value_var.set("50")
                    self.assertEqual(app._parse_scale_request(), (50.0, None))
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
