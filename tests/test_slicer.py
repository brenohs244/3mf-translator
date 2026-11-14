import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.slicer import SlicerCLI


class SlicerTests(unittest.TestCase):
    def test_validation_rejects_wrong_plate_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()

            def runner(args, **kwargs):
                output = Path(args[args.index("--outputdir") + 1])
                (output / "plate_1.gcode").write_text("G1 X1")
                (output / "plate_3.gcode").write_text("G1 X3")
                return subprocess.CompletedProcess(args, 0, "", "")

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 2)
        self.assertFalse(result.success)
        self.assertIn("2", result.message)

    def test_validation_rejects_zero_exit_without_gcode(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()
            calls = []

            def runner(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 1)
        self.assertFalse(result.success)
        self.assertIn("G-code", result.message)
        self.assertIn("--slice", calls[0])
        self.assertIn("0", calls[0])

    def test_validation_rejects_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()

            def runner(args, **kwargs):
                raise subprocess.TimeoutExpired(args, 1)

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 1)
        self.assertFalse(result.success)
        self.assertIn("tempo", result.message)

    def test_validation_accepts_expected_plate_gcode(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()

            def runner(args, **kwargs):
                output = Path(args[args.index("--outputdir") + 1])
                (output / "plate_1.gcode").write_text("G1 X1", encoding="utf-8")
                (output / "plate_2.gcode").write_text("G1 X2", encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "", "")

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 2)
        self.assertTrue(result.success)
        self.assertEqual(result.plate_count, 2)

    def test_validation_reads_time_and_material_from_real_gcode_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()

            def runner(args, **kwargs):
                output = Path(args[args.index("--outputdir") + 1])
                (output / "plate_1.gcode").write_text(
                    "; total filament used [g] = 28.70\n"
                    "; estimated printing time (normal mode) = 2h 18m 8s\nG1 X1\n",
                    encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "", "")

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 1)
        self.assertTrue(result.success)
        self.assertEqual(result.estimated_seconds, 8288)
        self.assertEqual(result.filament_grams, 28.70)

    def test_next_available_destination_and_existing_destination_handling(self):
        from maker_elegoo.slicer import next_available_destination
        from maker_elegoo.ui import _resolve_existing_destination

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "peca_ELEGOO.3mf"
            self.assertEqual(next_available_destination(base), base)
            base.write_bytes(b"existing")
            cand2 = next_available_destination(base)
            self.assertEqual(cand2, root / "peca_ELEGOO_2.3mf")
            cand2.write_bytes(b"existing2")
            cand3 = next_available_destination(base)
            self.assertEqual(cand3, root / "peca_ELEGOO_3.3mf")

            # Escolha False ("Não" -> usar sufixo sem apagar original)
            resolved_suffix = _resolve_existing_destination(base, ask_action=lambda *_, **__: False)
            self.assertEqual(resolved_suffix, root / "peca_ELEGOO_3.3mf")
            self.assertTrue(base.exists())

            # Escolha None ("Cancelar" -> aborta)
            resolved_cancel = _resolve_existing_destination(base, ask_action=lambda *_, **__: None)
            self.assertIsNone(resolved_cancel)
            self.assertTrue(base.exists())

            # Escolha True ("Sim" -> confirma sobrescrita removendo destino anterior)
            resolved_overwrite = _resolve_existing_destination(base, ask_action=lambda *_, **__: True)
            self.assertEqual(resolved_overwrite, base)
            self.assertFalse(base.exists())

