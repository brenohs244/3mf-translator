"""Testes TDD para Etapa 0B (compatibilidade multiobjeto/H2C/multicor) e Etapa 1."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.converter import compare_geometry
from maker_elegoo.labels import LABELS, PURPOSE_LABELS, describe_change, purpose_label
from maker_elegoo.mapping import build_conversion
from maker_elegoo.profiles import Profile, SlicerInstall
from maker_elegoo.project import inspect_project
from maker_elegoo.slicer import SlicerCLI, _patched_source


_CUBE_VERTS = """
<vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>
<vertex x="10" y="10" z="0"/><vertex x="0" y="10" z="0"/>
<vertex x="0" y="0" z="10"/><vertex x="10" y="0" z="10"/>
<vertex x="10" y="10" z="10"/><vertex x="0" y="10" z="10"/>
"""
_CUBE_TRIS = """
<triangle v1="0" v2="1" v3="2"/><triangle v1="0" v2="2" v3="3"/>
<triangle v1="4" v2="5" v3="6"/><triangle v1="4" v2="6" v3="7"/>
"""
_TETRA_VERTS = """
<vertex x="20" y="0" z="0"/><vertex x="30" y="0" z="0"/>
<vertex x="25" y="10" z="0"/><vertex x="25" y="5" z="10"/>
"""
_TETRA_TRIS = """
<triangle v1="0" v2="1" v3="2"/><triangle v1="0" v2="1" v3="3"/>
<triangle v1="1" v2="2" v3="3"/><triangle v1="2" v2="0" v3="3"/>
"""


def _write_profile(root: Path, kind: str, name: str, data: dict) -> Profile:
    folder = root / kind / "ECC2"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    payload = {"type": kind, "name": name, **data}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Profile(name=name, kind=kind, path=path, data=payload)


def _write_3mf(path: Path, entries: dict[str, bytes | str]) -> None:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


class Etapa0BAnd1Tests(unittest.TestCase):
    def test_compare_geometry_accepts_split_objects_into_3d_objects_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.3mf"
            target = root / "target.3mf"
            shifted = root / "shifted.3mf"
            _write_3mf(source, {
                "3D/3dmodel.model": f"""<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources>
  <object id="1" type="model"><mesh><vertices>{_CUBE_VERTS}</vertices><triangles>{_CUBE_TRIS}</triangles></mesh></object>
  <object id="2" type="model"><mesh><vertices>{_TETRA_VERTS}</vertices><triangles>{_TETRA_TRIS}</triangles></mesh></object>
</resources>
<build><item objectid="1"/><item objectid="2"/></build>
</model>""",
            })
            _write_3mf(target, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
 xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">
<resources>
  <object id="1" type="model"><components><component p:path="/3D/Objects/obj1.model" objectid="1"/></components></object>
  <object id="2" type="model"><components><component p:path="/3D/Objects/obj2.model" objectid="2"/></components></object>
</resources>
<build><item objectid="1"/><item objectid="2"/></build>
</model>""",
                "3D/Objects/obj1.model": f"""<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh><vertices>{_CUBE_VERTS.replace('z="10"', 'z="10.00001"')}</vertices><triangles>{_CUBE_TRIS}</triangles></mesh></object></resources>
</model>""",
                "3D/Objects/obj2.model": f"""<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="2" type="model"><mesh><vertices>{_TETRA_VERTS}</vertices><triangles>{_TETRA_TRIS}</triangles></mesh></object></resources>
</model>""",
            })
            _write_3mf(shifted, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
 xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">
<resources>
  <object id="1" type="model"><components><component p:path="/3D/Objects/obj1.model" objectid="1"/></components></object>
  <object id="2" type="model"><components><component p:path="/3D/Objects/obj2.model" objectid="2"/></components></object>
</resources>
<build><item objectid="1"/><item objectid="2"/></build>
</model>""",
                "3D/Objects/obj1.model": f"""<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh><vertices>{_CUBE_VERTS}</vertices><triangles>{_CUBE_TRIS}</triangles></mesh></object></resources>
</model>""",
                "3D/Objects/obj2.model": f"""<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="2" type="model"><mesh><vertices>{_TETRA_VERTS.replace('x="30"', 'x="30.05"')}</vertices><triangles>{_TETRA_TRIS}</triangles></mesh></object></resources>
</model>""",
            })
            self.assertTrue(compare_geometry(source, target).unchanged)
            self.assertFalse(compare_geometry(source, shifted).unchanged)

    def test_h2c_keys_removed_by_source_repairs_and_patched_source_preserves_paint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            machine = _write_profile(data_dir, "machine", "Elegoo Centauri Carbon 2 0.4 nozzle", {
                "printer_model": "Elegoo Centauri Carbon 2",
                "nozzle_diameter": ["0.4"],
                "printable_area": ["0x0,256x0,256x256,0x256"],
                "printable_height": "256",
            })
            process = _write_profile(data_dir, "process", "0.20mm Standard @Elegoo CC2 0.4 nozzle", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                "layer_height": "0.2",
                "wall_generator": "classic",
                "support_style": "default",
                "support_top_z_distance": "0.2",
                "support_interface_top_layers": "2",
                "support_threshold_angle": "30",
                "enable_prime_tower": "1",
            })
            filaments = [
                _write_profile(data_dir, "filament", f"Elegoo PLA Slot {i}", {
                    "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                    "filament_type": ["PLA"],
                    "filament_colour": ["#FFFFFF"],
                })
                for i in range(1, 6)
            ]
            install = SlicerInstall(executable=root / "elegoo-slicer.exe", data_dir=data_dir)
            src_settings = {
                "layer_height": "0.20",
                "filament_type": ["PLA"] * 5,
                "filament_colour": ["#111111", "#222222", "#333333", "#444444", "#555555"],
                "raft_first_layer_expansion": "-1",
                "master_extruder_id": "2",
                "extruder_ams_count": ["1#0|4#0", "1#0|4#0"],
                "physical_extruder_map": ["1", "0"],
                "print_extruder_id": ["1", "1", "2", "2"],
                "printer_extruder_id": ["1", "1", "2", "2"],
                "enable_prime_tower": "1",
            }
            src_3mf = root / "h2c.3mf"
            _write_3mf(src_3mf, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh>
<vertices><vertex x="0" y="0" z="0"/><vertex x="5" y="0" z="0"/><vertex x="0" y="5" z="0"/></vertices>
<triangles><triangle v1="0" v2="1" v3="2" paint_color="0C"/></triangles>
</mesh></object></resources><build><item objectid="1"/></build></model>""",
                "Metadata/project_settings.config": json.dumps(src_settings),
                "Metadata/model_settings.config": """<config>
  <plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="1"/></model_instance></plate>
  <object id="1"><metadata key="name" value="virgen"/><metadata key="extruder" value="2"/></object>
</config>""",
            })
            project = inspect_project(src_3mf)
            plan = build_conversion(project, install, machine, process, filaments)
            self.assertEqual(plan.source_repairs.get("raft_first_layer_expansion"), "0")
            self.assertIn("master_extruder_id", plan.source_repairs)
            self.assertIsNone(plan.source_repairs["master_extruder_id"])

            patched = root / "patched.3mf"
            _patched_source(project, plan.source_repairs, patched)
            with ZipFile(patched) as zf:
                patched_cfg = json.loads(zf.read("Metadata/project_settings.config"))
                patched_model = zf.read("3D/3dmodel.model").decode("utf-8")
            self.assertNotIn("master_extruder_id", patched_cfg)
            self.assertNotIn("extruder_ams_count", patched_cfg)
            self.assertNotIn("physical_extruder_map", patched_cfg)
            self.assertEqual(patched_cfg["raft_first_layer_expansion"], "0")
            self.assertIn('paint_color="0C"', patched_model)

    def test_transfers_etapa1_keys_and_forces_prime_tower_for_single_plate_multicolor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            machine = _write_profile(data_dir, "machine", "Elegoo Centauri Carbon 2 0.4 nozzle", {
                "printer_model": "Elegoo Centauri Carbon 2",
                "nozzle_diameter": ["0.4"],
            })
            process = _write_profile(data_dir, "process", "0.20mm Standard @Elegoo CC2 0.4 nozzle", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                "layer_height": "0.2",
                "wall_generator": "classic",
                "support_style": "default",
                "support_top_z_distance": "0.2",
                "support_interface_top_layers": "2",
                "support_threshold_angle": "30",
                "enable_prime_tower": "1",
            })
            f1 = _write_profile(data_dir, "filament", "Elegoo PLA 1", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"], "filament_type": ["PLA"]
            })
            f2 = _write_profile(data_dir, "filament", "Elegoo PLA 2", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"], "filament_type": ["PLA"]
            })
            install = SlicerInstall(executable=root / "elegoo-slicer.exe", data_dir=data_dir)
            src_3mf = root / "multicolor.3mf"
            _write_3mf(src_3mf, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh>
<vertices><vertex x="0" y="0" z="0"/><vertex x="5" y="0" z="0"/><vertex x="0" y="5" z="0"/></vertices>
<triangles><triangle v1="0" v2="1" v3="2" paint_color="8"/></triangles>
</mesh></object></resources><build><item objectid="1"/></build></model>""",
                "Metadata/project_settings.config": json.dumps({
                    "layer_height": "0.2",
                    "filament_type": ["PLA", "PLA"],
                    "filament_colour": ["#FFFFFF", "#000000"],
                    "wall_generator": "arachne",
                    "support_style": "tree_slim",
                    "support_top_z_distance": "0.16",
                    "support_interface_top_layers": "3",
                    "support_threshold_angle": "42",
                    "enable_prime_tower": "0",
                }),
                "Metadata/model_settings.config": """<config>
  <plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="1"/></model_instance></plate>
  <object id="1"><metadata key="name" value="dual"/><metadata key="extruder" value="1"/></object>
</config>""",
            })
            project = inspect_project(src_3mf)
            plan = build_conversion(project, install, machine, process, [f1, f2])
            self.assertEqual(plan.process_settings["wall_generator"], "arachne")
            self.assertEqual(plan.process_settings["support_style"], "tree_slim")
            self.assertEqual(plan.process_settings["support_top_z_distance"], "0.16")
            self.assertEqual(plan.process_settings["support_interface_top_layers"], "3")
            self.assertEqual(plan.process_settings["support_threshold_angle"], "42")
            self.assertEqual(plan.process_settings["enable_prime_tower"], "1")

            # Valores inválidos devem ser rejeitados pela validação de transferência
            bad_3mf = root / "bad.3mf"
            _write_3mf(bad_3mf, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh>
<vertices><vertex x="0" y="0" z="0"/><vertex x="5" y="0" z="0"/><vertex x="0" y="5" z="0"/></vertices>
<triangles><triangle v1="0" v2="1" v3="2"/></triangles>
</mesh></object></resources><build><item objectid="1"/></build></model>""",
                "Metadata/project_settings.config": json.dumps({
                    "layer_height": "0.2",
                    "filament_type": ["PLA"],
                    "filament_colour": ["#FFFFFF"],
                    "wall_generator": "magic_wall",
                    "support_top_z_distance": "-0.5",
                    "support_interface_top_layers": "99",
                    "support_threshold_angle": "120",
                    "enable_prime_tower": "maybe",
                }),
            })
            bad_project = inspect_project(bad_3mf)
            bad_plan = build_conversion(bad_project, install, machine, process, [f1])
            self.assertEqual(bad_plan.process_settings["wall_generator"], "classic")
            self.assertEqual(bad_plan.process_settings["support_top_z_distance"], "0.2")

    def test_project_inspects_paint_color_slots_parts_manual_support_and_object_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "complex.3mf"
            _write_3mf(p, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
 xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">
<resources><object id="1" type="model"><components><component p:path="/3D/Objects/body.model" objectid="1"/></components></object></resources>
<build><item objectid="1"/></build></model>""",
                "3D/Objects/body.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh>
<vertices><vertex x="0" y="0" z="0"/><vertex x="5" y="0" z="0"/><vertex x="0" y="5" z="0"/></vertices>
<triangles>
  <triangle v1="0" v2="1" v3="2" paint_color="4"/>
  <triangle v1="0" v2="1" v3="2" paint_color="8"/>
  <triangle v1="0" v2="1" v3="2" paint_color="0C"/>
  <triangle v1="0" v2="1" v3="2" paint_color="1C"/>
  <triangle v1="0" v2="1" v3="2" paint_color="2C"/>
</triangles>
</mesh></object></resources><build><item objectid="1"/></build></model>""",
                "Metadata/project_settings.config": json.dumps({
                    "layer_height": "0.20",
                    "filament_type": ["PLA"] * 6,
                    "filament_colour": ["#111", "#222", "#333", "#444", "#555", "#666"],
                    "enable_support": "1",
                    "support_type": "normal(manual)",
                }),
                "Metadata/model_settings.config": """<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <model_instance><metadata key="object_id" value="1"/></model_instance>
  </plate>
  <object id="1">
    <metadata key="name" value="virgen"/>
    <metadata key="extruder" value="2"/>
    <metadata key="layer_height" value="0.12"/>
    <metadata key="enable_support" value="1"/>
    <metadata key="support_type" value="tree(auto)"/>
    <part id="10" subtype="normal_part">
      <metadata key="name" value="detalhe"/>
      <metadata key="extruder" value="3"/>
    </part>
  </object>
</config>""",
            })
            info = inspect_project(p)
            self.assertEqual(info.used_filament_slots, ("1", "2", "3", "4", "5"))
            self.assertEqual(info.plates[0].used_filament_slots, ("1", "2", "3", "4", "5"))
            self.assertTrue(info.plates[0].has_paint_color)
            self.assertFalse(info.plates[0].has_paint_supports)
            self.assertTrue(any("suporte manual" in feat.lower() for feat in info.advanced_features))
            self.assertEqual(len(info.object_overrides), 1)
            self.assertEqual(info.object_overrides[0].settings.get("layer_height"), "0.12")
            self.assertEqual(info.object_overrides[0].settings.get("support_type"), "tree(auto)")

    def test_labels_include_etapa1_and_keychain_purposes(self):
        self.assertIn("chaveiro_rigido", PURPOSE_LABELS)
        self.assertIn("chaveiro_articulado", PURPOSE_LABELS)
        self.assertIn("wall_generator", LABELS)
        self.assertIn("support_style", LABELS)
        self.assertIn("support_top_z_distance", LABELS)
        self.assertIn("elefant_foot_compensation", LABELS)
        self.assertNotEqual(purpose_label("chaveiro_rigido"), "chaveiro_rigido")
        self.assertIn("Gerador de parede", describe_change("wall_generator", "classic", "arachne"))

    def test_slicer_export_restores_enable_prime_tower_if_cli_drops_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            machine = _write_profile(data_dir, "machine", "Elegoo Centauri Carbon 2 0.4 nozzle", {
                "printer_model": "Elegoo Centauri Carbon 2",
                "nozzle_diameter": ["0.4"],
            })
            process = _write_profile(data_dir, "process", "0.20mm Standard @Elegoo CC2 0.4 nozzle", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"],
                "layer_height": "0.2",
                "enable_prime_tower": "1",
            })
            f1 = _write_profile(data_dir, "filament", "Elegoo PLA 1", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"], "filament_type": ["PLA"]
            })
            f2 = _write_profile(data_dir, "filament", "Elegoo PLA 2", {
                "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"], "filament_type": ["PLA"]
            })
            install = SlicerInstall(executable=root / "elegoo-slicer.exe", data_dir=data_dir)
            src = root / "multi.3mf"
            _write_3mf(src, {
                "3D/3dmodel.model": """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh>
<vertices><vertex x="0" y="0" z="0"/><vertex x="5" y="0" z="0"/><vertex x="0" y="5" z="0"/></vertices>
<triangles><triangle v1="0" v2="1" v3="2" paint_color="8"/></triangles>
</mesh></object></resources><build><item objectid="1"/></build></model>""",
                "Metadata/project_settings.config": json.dumps({
                    "layer_height": "0.2", "filament_type": ["PLA", "PLA"],
                    "filament_colour": ["#FFFFFF", "#000000"], "enable_prime_tower": "0",
                }),
                "Metadata/model_settings.config": '<config><plate><model_instance><metadata key="object_id" value="1"/></model_instance></plate><object id="1"><metadata key="extruder" value="1"/></object></config>',
            })
            project = inspect_project(src, include_geometry=False)
            plan = build_conversion(project, install, machine, process, [f1, f2])

            def fake_runner(args, **_kwargs):
                out_path = Path(args[args.index("--export-3mf") + 1])
                _write_3mf(out_path, {
                    "3D/3dmodel.model": "<model/>",
                    "Metadata/project_settings.config": json.dumps({"enable_prime_tower": "0"}),
                })
                class _R:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return _R()

            cli = SlicerCLI(install.executable, runner=fake_runner)
            dst = root / "out.3mf"
            res = cli.export(project, plan, dst)
            self.assertTrue(res.success)
            with ZipFile(dst) as zf:
                out_cfg = json.loads(zf.read("Metadata/project_settings.config"))
            self.assertEqual(out_cfg["enable_prime_tower"], "1")


if __name__ == "__main__":
    unittest.main()
