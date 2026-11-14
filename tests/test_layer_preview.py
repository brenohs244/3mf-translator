import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.calibration import write_calibration_source_3mf
from maker_elegoo.converter import ConversionResult
from maker_elegoo.gcode_audit import GcodeAuditSummary, PlateGcodeAudit
from maker_elegoo.layer_preview import LayerPreview, render_layer1_and_overhang_preview
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.profiles import Profile
from maker_elegoo.project import inspect_project
from maker_elegoo.slicer import ExportResult, ValidationResult
from maker_elegoo.ui import MakerElegooApp, format_conversion_report


class LayerPreviewAndReportTests(unittest.TestCase):
    def test_renders_valid_ppm_preview_from_3mf_and_gcode_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            src = write_calibration_source_3mf(Path(directory) / "cal.3mf")
            audit = PlateGcodeAudit(
                plate=1,
                layer_count=20,
                first_layer_nozzle_temp=240.0,
                nozzle_temps=(240.0,),
                bed_temps=(105.0,),
                part_fan_max_pct=35,
                aux_fan_max_pct=0,
                exhaust_fan_max_pct=60,
                has_preheat_dwell=True,
                preheat_dwell_seconds=300,
                max_volumetric_flow_mm3_s=11.4,
                min_layer_time_s=7.3,
                short_layers_under_6s=0,
                max_print_speed_mm_s=180.0,
                speed_jump_count=2,
                layer1_bounds_mm=(103.0, 153.0, 111.0, 158.0),
                layer1_island_count=3,
                layer1_segments=((103.0, 111.0, 153.0, 111.0), (153.0, 111.0, 153.0, 121.0)),
            )
            preview = render_layer1_and_overhang_preview(src, gcode_audit=audit, size_px=320)

        self.assertIsInstance(preview, LayerPreview)
        self.assertEqual(preview.width, 320)
        self.assertEqual(preview.height, 320)
        header = b"P6\n320 320\n255\n"
        self.assertTrue(preview.ppm_bytes.startswith(header))
        self.assertEqual(len(preview.ppm_bytes), len(header) + 320 * 320 * 3)
        self.assertGreater(preview.contact_area_mm2, 500.0)
        self.assertGreaterEqual(preview.gcode_segments_drawn, 2)
        # Verifica pixel colorido de contato e de percurso G-code
        body = preview.ppm_bytes[len(header):]
        self.assertIn(bytes((0x2A, 0xB7, 0xA9)), body)
        self.assertIn(bytes((0x7D, 0xF9, 0xFF)), body)

    def test_conversion_report_shows_real_gcode_audit_and_profile_warnings(self):
        plan = ConversionPlan(
            machine=Profile("ECC2 0.4", "machine", Path("m.json"), {}),
            process=Profile("0.20mm Standard", "process", Path("p.json"), {}),
            filaments=(Profile("Elegoo ABS @ECC2", "filament", Path("f.json"), {}),),
            machine_settings={},
            process_settings={},
            filament_settings=({
                "filament_type": ["ABS"],
                "filament_max_volumetric_speed": ["12"],
            },),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        audit = PlateGcodeAudit(
            plate=1,
            layer_count=15,
            first_layer_nozzle_temp=245.0,
            nozzle_temps=(245.0,),
            bed_temps=(105.0,),
            part_fan_max_pct=70,
            aux_fan_max_pct=0,
            exhaust_fan_max_pct=50,
            has_preheat_dwell=True,
            preheat_dwell_seconds=300,
            max_volumetric_flow_mm3_s=14.8,
            min_layer_time_s=4.2,
            short_layers_under_6s=2,
            max_print_speed_mm_s=220.0,
            speed_jump_count=3,
            layer1_bounds_mm=(100.0, 140.0, 100.0, 140.0),
            layer1_island_count=2,
        )
        result = ConversionResult(
            True, Path("out.3mf"), "Todas as placas foram fatiadas",
            ExportResult(True, Path("out.3mf"), "ok"),
            ValidationResult(True, 1, "ok", (), 900, 15.0, (), GcodeAuditSummary((audit,))),
            None, None, {},
        )
        report = format_conversion_report(result, plan)
        self.assertIn("Auditoria real do G-code:", report)
        self.assertIn("14.8", report)
        self.assertIn("G4 S300", report)
        self.assertIn("ventoinha da peça", report.lower())

    def test_ui_layer1_preview_dialog_renders_and_closes(self):
        import tkinter as tk
        try:
            app = MakerElegooApp()
        except tk.TclError:
            self.skipTest("Display Tkinter indisponível neste ambiente")
        try:
            app.withdraw()
            with tempfile.TemporaryDirectory() as directory:
                src = write_calibration_source_3mf(Path(directory) / "cal_ui.3mf")
                app.project = inspect_project(src, include_geometry=True)
                dialog = app._preview_layer1_dialog()
                self.assertIsNotNone(dialog)
                app.update_idletasks()
                dialog.destroy()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
