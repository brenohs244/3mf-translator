import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo import profiles
from maker_elegoo.mapping import build_conversion
from maker_elegoo.material_selection import parse_material_identity, select_material_profile
from maker_elegoo.profiles import SlicerInstall, list_profiles, resolve_profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo, inspect_project
from maker_elegoo.ui import MakerElegooApp


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_perf_install(root: Path, *, num_filaments: int = 16) -> SlicerInstall:
    exe = root / "elegoo-slicer.exe"
    exe.touch()
    data_dir = root / "ElegooSlicer"
    sys_dir = data_dir / "system" / "Elegoo"
    base_machine = "Elegoo Centauri Carbon 2 0.4 nozzle"

    _write_json(
        sys_dir / "machine" / "ECC2" / "base.json",
        {
            "type": "machine",
            "name": base_machine,
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
        },
    )
    _write_json(
        sys_dir / "process" / "ECC2" / "base_proc.json",
        {
            "type": "process",
            "name": "fdm_process_common",
            "layer_height": "0.2",
            "wall_loops": "2",
            "sparse_infill_density": "15%",
            "compatible_printers": [base_machine],
        },
    )
    _write_json(
        sys_dir / "process" / "ECC2" / "std.json",
        {
            "type": "process",
            "name": "0.20mm Standard @Elegoo CC2 0.4 nozzle",
            "inherits": "fdm_process_common",
        },
    )
    _write_json(
        sys_dir / "filament" / "ECC2" / "fdm_fil_base.json",
        {
            "type": "filament",
            "name": "fdm_filament_common",
            "fan_max_speed": ["100"],
            "compatible_printers": [base_machine],
        },
    )
    _write_json(
        sys_dir / "filament" / "ECC2" / "pla_vendor.json",
        {
            "type": "filament",
            "name": "Elegoo PLA @ECC2",
            "inherits": "fdm_filament_common",
            "filament_type": ["PLA"],
            "filament_vendor": ["Elegoo"],
        },
    )
    _write_json(
        sys_dir / "filament" / "ECC2" / "pla_cf.json",
        {
            "type": "filament",
            "name": "Elegoo PLA-CF @ECC2",
            "inherits": "fdm_filament_common",
            "filament_type": ["PLA-CF"],
            "filament_vendor": ["Elegoo"],
        },
    )
    for i in range(num_filaments):
        _write_json(
            sys_dir / "filament" / "ECC2" / f"extra_{i}.json",
            {
                "type": "filament",
                "name": f"Extra Mat {i} @ECC2",
                "inherits": "fdm_filament_common",
                "filament_type": ["PETG"],
                "filament_vendor": ["Elegoo"],
            },
        )
    return SlicerInstall(exe, data_dir)


class PerformanceTests(unittest.TestCase):
    def test_profile_cache_eliminates_redundant_json_reads_and_invalidates_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = _build_perf_install(root, num_filaments=16)
            profiles.clear_profile_cache()

            orig_read = profiles._read_profile
            reads = 0

            def counted_read(path: Path, kind: str):
                nonlocal reads
                reads += 1
                return orig_read(path, kind)

            with patch.object(profiles, "_read_profile", side_effect=counted_read):
                machines = list_profiles(install, "machine", "0.4")
                procs = list_profiles(install, "process", "0.4", machine=machines[0])
                fils = list_profiles(install, "filament", "0.4", machine=machines[0])
                first_load_reads = reads
                # 1 machine + 2 process + 19 filament = 22 JSON files (deve ler cada arquivo no máximo 1 vez)
                self.assertLessEqual(first_load_reads, 24)

                # Selecionar material e montar vários planos seguidos NÃO deve reler JSONs do disco
                reads = 0
                for _ in range(3):
                    sel = select_material_profile(parse_material_identity("PLA"), fils, install)
                    self.assertIsNotNone(sel.profile)
                    self.assertEqual(sel.profile.name, "Elegoo PLA @ECC2")
                self.assertEqual(reads, 0)

                proj = ProjectInfo(
                    root / "cube.3mf",
                    {"layer_height": "0.2"},
                    (FilamentInfo(1, "PLA", "#FFFFFF", ""),),
                    (PlateInfo(1, 1),),
                    ("Cube",),
                    (),
                    (),
                    used_filament_slots=("1",),
                )
                reads = 0
                for _ in range(5):
                    build_conversion(proj, install, machines[0], procs[0], [sel.profile])
                self.assertEqual(reads, 0)

            # Alteração no arquivo pai em disco deve invalidar cache imediatamente
            base_fil = install.data_dir / "system" / "Elegoo" / "filament" / "ECC2" / "fdm_fil_base.json"
            payload = json.loads(base_fil.read_text(encoding="utf-8"))
            payload["fan_max_speed"] = ["88"]
            payload["_bump"] = 1  # garante mudança de tamanho caso mtime_ns coincida
            base_fil.write_text(json.dumps(payload), encoding="utf-8")

            resolved = resolve_profile(sel.profile, install)
            self.assertEqual(resolved["fan_max_speed"], ["88"])

    def test_inspect_project_fast_pass_defers_heavy_model_scan_and_ui_runs_zero_idle_pollers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = _build_perf_install(root, num_filaments=4)
            profiles.clear_profile_cache()

            src_3mf = root / "sample.3mf"
            pad = " " * 20000
            model_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                "<resources>"
                '<object id="1" type="model"><mesh>'
                "<vertices>"
                '<vertex x="0" y="0" z="0"/>'
                '<vertex x="10" y="0" z="0"/>'
                '<vertex x="0" y="10" z="0"/>'
                '<vertex x="0" y="0" z="10"/>'
                "</vertices>"
                "<triangles>"
                '<triangle v1="0" v2="1" v3="2" paint_color="0C"/>'
                '<triangle v1="0" v2="1" v3="3"/>'
                '<triangle v1="1" v2="2" v3="3"/>'
                '<triangle v1="0" v2="2" v3="3"/>'
                "</triangles>"
                f"<!-- {pad} -->"
                "</mesh></object>"
                "</resources><build><item objectid=\"1\"/></build></model>"
            )
            with ZipFile(src_3mf, "w") as zf:
                zf.writestr(
                    "Metadata/project_settings.config",
                    json.dumps({"filament_type": ["PLA", "PLA"], "filament_colour": ["#FFFFFF", "#000000"]}),
                )
                zf.writestr(
                    "Metadata/model_settings.config",
                    "<config>"
                    '<object id="1"><metadata key="name" value="Obj"/><metadata key="extruder" value="1"/></object>'
                    '<plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="1"/></model_instance></plate>'
                    "</config>",
                )
                zf.writestr("3D/3dmodel.model", model_xml)

            fast_proj = inspect_project(src_3mf, include_geometry=False, include_model_scan=False)
            self.assertEqual(fast_proj.used_filament_slots, ("1",))
            self.assertFalse(any("paint_color" in f for f in fast_proj.advanced_features))

            full_proj = inspect_project(src_3mf, include_geometry=False, include_model_scan=True)
            self.assertEqual(full_proj.used_filament_slots, ("1", "3"))
            self.assertTrue(any("paint_color" in f for f in full_proj.advanced_features))

            env = {
                "APPDATA": str(root),
                "ELEGOO_SLICER_EXE": str(install.executable),
                "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs"),
            }
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    # Ocioso ao abrir: zero pollers periódicos desperdiçando CPU
                    self.assertEqual(len(app.tk.call("after", "info")), 0)

                    # Mudança de objetivo e material não deve reler JSONs em cache
                    with patch.object(profiles, "_read_profile", wraps=profiles._read_profile) as read_spy:
                        app.purpose_var.set("Recebe força (esforço mecânico)")
                        app.priority_var.set("Qualidade visual")
                        self.assertEqual(read_spy.call_count, 0)

                    # _inspect_file abre rápido sem travar e agenda varredura pesada + geometria em background
                    app.file_var.set(str(src_3mf))
                    with patch("maker_elegoo.ui.inspect_project", wraps=inspect_project) as insp_spy:
                        app._inspect_file()
                        self.assertGreaterEqual(insp_spy.call_count, 1)
                        first_kwargs = insp_spy.call_args_list[0].kwargs
                        self.assertFalse(first_kwargs.get("include_model_scan", True))

                    # Aguarda worker em background concluir inspect + geometria e aplica via _poll_inspect
                    item = app.inspect_queue.get(timeout=5)
                    app.inspect_queue.put(item)
                    app._poll_inspect()
                    self.assertIsNotNone(app.project.geometry_summary)
                    self.assertEqual(app.project.used_filament_slots, ("1", "3"))
                    self.assertTrue(any("paint_color" in f for f in app.project.advanced_features))
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
