import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo import profiles
from maker_elegoo.mapping import build_conversion
from maker_elegoo.material_selection import parse_material_identity, select_material_profile
from maker_elegoo.profiles import SlicerInstall, list_profiles, resolve_profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


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


if __name__ == "__main__":
    unittest.main()
