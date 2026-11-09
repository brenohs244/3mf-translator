import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.project import FilamentInfo, ProjectInfo
from maker_elegoo.ui import MakerElegooApp


class UIProfileTests(unittest.TestCase):
    def test_selects_local_custom_machine_process_and_filament(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "AppData" / "ElegooSlicer"
            exe_dir = root / "ProgramFiles" / "ElegooSlicer"
            exe_dir.mkdir(parents=True)
            (exe_dir / "elegoo-slicer.exe").touch()
            base = "Elegoo Centauri Carbon 2 0.4 nozzle"
            entries = [
                ("system/Elegoo/machine/ECC2/base.json", {"type": "machine", "name": base,
                    "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]}),
                ("user/default/machine/custom.json", {"name": "PERFECT PET-G", "inherits": base}),
                ("system/Elegoo/process/ECC2/standard.json", {"type": "process", "name": "Standard",
                    "compatible_printers": [base]}),
                ("user/default/process/custom.json", {"name": "My process", "inherits": "Standard"}),
                ("system/Elegoo/filament/Generic/base.json", {"type": "filament", "name": "Generic PLA",
                    "compatible_printers": [base]}),
                ("user/default/filament/custom.json", {"name": "ENDER PLA", "inherits": "Generic PLA"}),
            ]
            for relative, data in entries:
                path = data_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            env = {"APPDATA": str(root / "AppData"), "ProgramFiles": str(root / "ProgramFiles"),
                   "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    app.project = ProjectInfo(root / "source.3mf", {},
                        (FilamentInfo(1, "PLA", "#fff", ""),), (), (), (), ())
                    self.assertIn("PERFECT PET-G", app.machine_combo["values"])
                    app.machine_var.set("PERFECT PET-G")
                    app._refresh_dependents()
                    self.assertIn("My process", app.process_combo["values"])
                    app.process_var.set("My process")
                    app.filament_vars[0].set("ENDER PLA")
                    machine, process, filaments = app._selected_profiles()
                    self.assertEqual((machine.name, process.name, filaments[0].name),
                                     ("PERFECT PET-G", "My process", "ENDER PLA"))
                finally:
                    app.destroy()
