"""Testes TDD para pré-análise geométrica em streaming (Etapa 4)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ai_client import advise_gemini
from maker_elegoo.geometry_check import GeometrySummary, analyze_project_geometry
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import PrintGoal, advise_offline
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo, inspect_project
from maker_elegoo.ui import format_project_summary


def _cube_xml(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> str:
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    v_str = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
    t_str = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return f"<mesh><vertices>{v_str}</vertices><triangles>{t_str}</triangles></mesh>"


class GeometryCheckTests(unittest.TestCase):
    def test_analyze_project_geometry_reads_split_3d_objects_and_transforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "split.3mf"
            with ZipFile(p, "w") as zf:
                zf.writestr(
                    "3D/3dmodel.model",
                    """<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
 xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">
<resources>
  <object id="1" type="model"><components><component p:path="/3D/Objects/base.model" objectid="10"/></components></object>
  <object id="2" type="model"><components><component p:path="/3D/Objects/pin.model" objectid="20" transform="1 0 0 0 1 0 0 0 1 30 0 0"/></components></object>
</resources>
<build>
  <item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/>
  <item objectid="2" transform="1 0 0 0 1 0 0 0 1 10 10 0"/>
</build>
</model>""",
                )
                zf.writestr(
                    "3D/Objects/base.model",
                    f'<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="10">{_cube_xml(0, 20, 0, 20, 0, 5)}</object></resources></model>',
                )
                zf.writestr(
                    "3D/Objects/pin.model",
                    f'<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="20">{_cube_xml(0, 4, 0, 4, 0, 40)}</object></resources></model>',
                )
                zf.writestr("Metadata/project_settings.config", json.dumps({"layer_height": "0.2", "filament_type": ["PLA"]}))
                zf.writestr("Metadata/model_settings.config", '<config><plate><model_instance><metadata key="object_id" value="1"/></model_instance></plate></config>')

            summary = analyze_project_geometry(p)
            self.assertEqual(summary.triangle_count, 24)
            self.assertEqual(summary.object_count, 2)
            self.assertAlmostEqual(summary.size_z, 40.0, places=2)
            self.assertAlmostEqual(summary.contact_mm2, 416.0, places=1)
            self.assertTrue(summary.has_slender_parts)

            info = inspect_project(p)
            self.assertIsNotNone(info.geometry_summary)
            self.assertEqual(info.geometry_summary.triangle_count, 24)

            text = format_project_summary(info)
            self.assertIn("24 triângulos", text)
            self.assertIn("40.0", text)

    def test_professor_and_gemini_use_numeric_geometry_summary_safely(self):
        geom = GeometrySummary(
            triangle_count=1_200_000,
            object_count=2,
            bounds=(10.0, 60.0, 10.0, 60.0, 0.0, 120.0),
            size_x=50.0,
            size_y=50.0,
            size_z=120.0,
            contact_mm2=16.0,
            overhang_mm2=650.0,
            has_slender_parts=True,
        )
        proj = ProjectInfo(
            Path("secret_dragon_mesh.3mf"),
            {"layer_height": "0.2", "printer_model": "Bambu A1"},
            (FilamentInfo(1, "PLA", "#FFFFFF", ""),),
            (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            ("Dragon",),
            (),
            (),
            geometry_summary=geom,
        )
        plan = ConversionPlan(
            machine=Profile("ECC2", "machine", Path("m.json"), {}),
            process=Profile("0.20", "process", Path("p.json"), {}),
            filaments=(Profile("PLA", "filament", Path("f.json"), {}),),
            machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"], "min_layer_height": ["0.08"], "max_layer_height": ["0.28"]},
            process_settings={
                "wall_loops": "2", "sparse_infill_density": "15%", "layer_height": "0.2",
                "brim_type": "no_brim", "enable_support": "0", "outer_wall_speed": "160",
            },
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(proj, plan, PrintGoal("decorativa", "equilibrio"))
        alerts = " | ".join(f"{a.title} {a.why}".lower() for a in advices if a.scope == "alert")
        self.assertIn("simplificar", alerts)
        self.assertIn("esguia", alerts)
        self.assertIn("saliências", alerts)

        class CaptureClient:
            def __init__(self):
                self.prompt = ""
            def generate_json(self, prompt: str):
                self.prompt = prompt
                return {"advices": []}

        client = CaptureClient()
        advise_gemini(client, proj, plan, PrintGoal("decorativa", "equilibrio"))
        self.assertIn("1200000", client.prompt)
        self.assertIn("650", client.prompt)
        self.assertNotIn("secret_dragon_mesh", client.prompt)


if __name__ == "__main__":
    unittest.main()
