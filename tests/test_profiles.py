import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.profiles import ProfileError, SlicerInstall, discover_slicer, list_profiles, resolve_profile


def profile(root, relative, values):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


class ProfileTests(unittest.TestCase):
    def test_local_custom_profiles_follow_inherited_machine_and_nozzle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "elegoo-slicer.exe"
            exe.touch()
            base_name = "Elegoo Centauri Carbon 2 0.4 nozzle"
            profile(root, "system/Elegoo/machine/ECC2/base.json", {
                "type": "machine", "name": base_name,
                "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]})
            profile(root, "system/Elegoo/process/ECC2/standard.json", {
                "type": "process", "name": "Standard 0.4",
                "compatible_printers": [base_name]})
            profile(root, "system/Elegoo/filament/Generic/pla.json", {
                "type": "filament", "name": "Generic PLA",
                "compatible_printers": [base_name]})
            profile(root, "user/account-42/machine/custom.json", {
                "name": "0.2 PERFECT PLA", "inherits": base_name})
            profile(root, "user/account-42/process/custom.json", {
                "name": "PERFECT PLA", "inherits": "Standard 0.4"})
            profile(root, "user/account-42/filament/custom.json", {
                "name": "ENDER PLA", "inherits": "Generic PLA"})
            install = discover_slicer(executable=exe, data_dir=root)

            machines = list_profiles(install, "machine", "0.4")
            self.assertIn("0.2 PERFECT PLA", [item.name for item in machines])
            self.assertNotIn("0.2 PERFECT PLA", [item.name for item in list_profiles(install, "machine", "0.2")])
            custom = next(item for item in machines if item.name == "0.2 PERFECT PLA")
            self.assertIn("PERFECT PLA", [item.name for item in list_profiles(install, "process", "0.4", machine=custom)])
            self.assertIn("ENDER PLA", [item.name for item in list_profiles(install, "filament", "0.4", machine=custom)])

    def test_local_profiles_exclude_other_printer_and_wrong_nozzle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "elegoo-slicer.exe"
            exe.touch()
            target = "Elegoo Centauri Carbon 2 0.4 nozzle"
            other = "Elegoo Centauri Carbon 2 0.2 nozzle"
            for name, nozzle in ((target, "0.4"), (other, "0.2")):
                profile(root, f"system/Elegoo/machine/ECC2/{nozzle}.json", {
                    "type": "machine", "name": name,
                    "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": [nozzle]})
            profile(root, "system/Elegoo/process/ECC2/wrong.json", {
                "type": "process", "name": "Wrong process", "compatible_printers": [other]})
            profile(root, "user/default/filament/wrong.json", {
                "name": "Wrong filament", "compatible_printers": [other]})
            profile(root, "user/default/machine/other.json", {
                "name": "Other printer", "printer_model": "Other", "nozzle_diameter": ["0.4"]})
            install = discover_slicer(executable=exe, data_dir=root)
            self.assertEqual([item.name for item in list_profiles(install, "machine", "0.4")], [target])
            self.assertNotIn("Wrong process", [item.name for item in list_profiles(install, "process", "0.4")])
            self.assertNotIn("Wrong filament", [item.name for item in list_profiles(install, "filament", "0.4")])

    def test_malformed_local_machine_nozzle_does_not_enter_available_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("missing", None), ("empty", []), ("text", ["unknown"])):
                data = {"type": "machine", "name": name,
                        "printer_model": "Elegoo Centauri Carbon 2"}
                if value is not None:
                    data["nozzle_diameter"] = value
                profile(root, f"user/default/machine/{name}.json", data)
            profile(root, "system/Elegoo/machine/ECC2/valid.json", {
                "type": "machine", "name": "Valid CC2",
                "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]})
            install = SlicerInstall(root / "elegoo-slicer.exe", root)
            self.assertEqual([item.name for item in list_profiles(install, "machine", None)], ["Valid CC2"])

    def test_discovers_machine_process_and_user_filament(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "elegoo-slicer.exe"
            exe.touch()
            profile(root, "system/Elegoo/machine/ECC2/cc2.json", {
                "type": "machine", "name": "Elegoo Centauri Carbon 2 0.4 nozzle",
                "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]})
            profile(root, "system/Elegoo/process/ECC2/standard.json", {
                "type": "process", "name": "Standard", "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"]})
            profile(root, "user/default/filament/custom.json", {
                "name": "My PLA", "filament_type": ["PLA"]})
            install = discover_slicer(executable=exe, data_dir=root)
            self.assertEqual([p.name for p in list_profiles(install, "machine", "0.4")],
                             ["Elegoo Centauri Carbon 2 0.4 nozzle"])
            self.assertEqual([p.name for p in list_profiles(install, "process", "0.4")], ["Standard"])
            self.assertIn("My PLA", [p.name for p in list_profiles(install, "filament", "0.4")])

    def test_resolves_inheritance_and_rejects_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = profile(root, "system/Elegoo/filament/base.json", {
                "type": "filament", "name": "Base", "nozzle_temperature": ["220"]})
            child = profile(root, "system/Elegoo/filament/ECC2/child.json", {
                "type": "filament", "name": "Child", "inherits": "Base", "filament_type": ["PETG"]})
            install = SlicerInstall(root / "elegoo-slicer.exe", root)
            resolved = resolve_profile(child, install)
            self.assertEqual(resolved["nozzle_temperature"], ["220"])
            self.assertEqual(resolved["filament_type"], ["PETG"])
            base.write_text(json.dumps({"type": "filament", "name": "Base", "inherits": "Child"}))
            with self.assertRaisesRegex(ProfileError, "ciclo"):
                resolve_profile(child, install)

    def test_rejects_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = profile(root, "system/Elegoo/process/ECC2/child.json", {
                "type": "process", "name": "Child", "inherits": "Absent"})
            with self.assertRaisesRegex(ProfileError, "não encontrado"):
                resolve_profile(child, SlicerInstall(root / "elegoo-slicer.exe", root))
