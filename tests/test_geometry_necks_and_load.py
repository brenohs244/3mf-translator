import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.geometry_check import GeometrySummary, NeckFinding, analyze_project_geometry
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.orientation import load_scene, rank_orientations
from maker_elegoo.professor import PrintGoal, advise_offline
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


def _write_stepped_prism_3mf(path: Path, rings: list[tuple[float, float, float]]) -> None:
    """Escreve um 3MF minimalista fechado a partir de anéis retangulares (half_x, half_y, z)."""
    verts: list[tuple[float, float, float]] = []
    tris: list[tuple[int, int, int]] = []
    for hx, hy, z in rings:
        verts.extend([(-hx, -hy, z), (hx, -hy, z), (hx, hy, z), (-hx, hy, z)])
    # Bottom cap
    tris.extend([(0, 2, 1), (0, 3, 2)])
    # Side quads between consecutive rings
    for idx in range(len(rings) - 1):
        b = idx * 4
        t = (idx + 1) * 4
        for corner in range(4):
            nxt = (corner + 1) % 4
            tris.append((b + corner, b + nxt, t + nxt))
            tris.append((b + corner, t + nxt, t + corner))
    # Top cap
    top = (len(rings) - 1) * 4
    tris.extend([(top + 0, top + 1, top + 2), (top + 0, top + 2, top + 3)])

    v_xml = "\n".join(f'          <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    t_xml = "\n".join(f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        '  <resources>\n'
        '    <object id="1" type="model">\n'
        '      <mesh>\n'
        '        <vertices>\n'
        f"{v_xml}\n"
        '        </vertices>\n'
        '        <triangles>\n'
        f"{t_xml}\n"
        '        </triangles>\n'
        '      </mesh>\n'
        '    </object>\n'
        '  </resources>\n'
        '  <build>\n'
        '    <item objectid="1"/>\n'
        '  </build>\n'
        '</model>\n'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n'
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '</Types>\n'
    )
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<config>\n'
        '  <object id="1">\n'
        '    <metadata key="name" value="TestPart"/>\n'
        '    <metadata key="extruder" value="1"/>\n'
        '  </object>\n'
        '  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n'
        '    <metadata key="plater_name" value="Plate 1"/>\n'
        '    <model_instance>\n'
        '      <metadata key="object_id" value="1"/>\n'
        '      <metadata key="instance_id" value="0"/>\n'
        '    </model_instance>\n'
        '  </plate>\n'
        '</config>\n'
    )
    proj_cfg = '{"filament_type": ["PLA"], "layer_height": "0.2"}'
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", ct)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/project_settings.config", proj_cfg)
        archive.writestr("Metadata/model_settings.config", model_settings)


class GeometryNecksAndLoadTests(unittest.TestCase):
    def test_uniform_cube_has_no_false_positive_neck(self):
        with tempfile.TemporaryDirectory() as directory:
            cube = Path(directory) / "cube.3mf"
            _write_stepped_prism_3mf(cube, [(10.0, 10.0, 0.0), (10.0, 10.0, 20.0)])
            summary = analyze_project_geometry(cube)
        self.assertIsInstance(summary, GeometrySummary)
        self.assertFalse(summary.has_thin_neck)
        self.assertEqual(summary.neck_findings, ())
        self.assertGreater(summary.min_cross_section_ratio, 0.9)

    def test_hourglass_mesh_detects_narrow_neck_and_triggers_professor_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            hourglass = Path(directory) / "hourglass.3mf"
            # Base 24x24 (area 576), pescoco 4x4 (area 16 -> ~2.8%), topo 24x24
            _write_stepped_prism_3mf(
                hourglass,
                [
                    (12.0, 12.0, 0.0),
                    (12.0, 12.0, 10.0),
                    (2.0, 2.0, 14.0),
                    (2.0, 2.0, 18.0),
                    (12.0, 12.0, 22.0),
                    (12.0, 12.0, 32.0),
                ],
            )
            summary = analyze_project_geometry(hourglass)

        self.assertTrue(summary.has_thin_neck)
        self.assertLess(summary.min_cross_section_ratio, 0.20)
        self.assertGreaterEqual(len(summary.neck_findings), 1)
        neck = summary.neck_findings[0]
        self.assertIsInstance(neck, NeckFinding)
        self.assertGreaterEqual(neck.z_mm, 10.0)
        self.assertLessEqual(neck.z_mm, 22.0)

        project = ProjectInfo(
            path=Path("hourglass.3mf"),
            source_settings={"layer_height": "0.2"},
            filaments=(FilamentInfo(1, "PLA", "#FFFFFF", "PLA"),),
            plates=(PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
            objects=("Hourglass",),
            archive_entries=("3D/3dmodel.model",),
            warnings=(),
            geometry_summary=summary,
        )
        plan = ConversionPlan(
            machine=Profile("CC2", "machine", Path("m.json"), {}),
            process=Profile("0.20", "process", Path("p.json"), {}),
            filaments=(Profile("PLA", "filament", Path("f.json"), {}),),
            machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]},
            process_settings={"layer_height": "0.2", "wall_loops": "2", "sparse_infill_density": "15%"},
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(project, plan, PrintGoal("esforco", "equilibrio", load_type="flexao_lateral", physical_material="PLA"))
        neck_alerts = [a for a in advices if "pescoço" in a.title.lower() or "seção estreita" in a.title.lower()]
        self.assertGreaterEqual(len(neck_alerts), 1)

    def test_rank_orientations_considers_load_type_without_breaking_default_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            tall_bar = Path(directory) / "bar.3mf"
            # Barra vertical alta: base 12x12, altura 60 mm
            _write_stepped_prism_3mf(tall_bar, [(6.0, 6.0, 0.0), (6.0, 6.0, 60.0)])
            scene = load_scene(tall_bar)

        area = ["0x0", "256x0", "256x256", "0x256"]
        neutral = rank_orientations(scene, "+Y", area, 256.0)
        load_ranked = rank_orientations(scene, "+Y", area, 256.0, load_type="tracao_eixo_z")

        # Sem load_type definido continua compatível; com tracao_eixo_z a melhor alternativa é deitada (Z << XY)
        self.assertEqual(neutral[0].label, "Atual")
        best_alt = next(c for c in load_ranked[1:] if c.valid)
        dx = best_alt.bounds[1] - best_alt.bounds[0]
        dy = best_alt.bounds[3] - best_alt.bounds[2]
        dz = best_alt.bounds[5] - best_alt.bounds[4]
        self.assertGreater(max(dx, dy), dz)
        self.assertIn("camadas", best_alt.load_note.lower())


if __name__ == "__main__":
    unittest.main()
