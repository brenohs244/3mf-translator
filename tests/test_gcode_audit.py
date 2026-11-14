import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.gcode_audit import (
    GcodeAuditSummary,
    PlateGcodeAudit,
    audit_gcode_file,
    summarize_gcode_audit,
)
from maker_elegoo.slicer import SlicerCLI


SAMPLE_GCODE = """\
; estimated printing time (normal mode) = 4m 10s
; total filament used [g] = 5.40
; filament_diameter: 1.75
G90
M83
M140 S100
M190 S105 A
G4 S300
M104 S240
M109 S245
M106 P0 S204
M106 P2 S128
M106 P3 S179
;LAYER_CHANGE
;Z:0.20
G1 X100 Y100 F18000
G1 X110 Y100 E0.500 F3000
G1 X110 Y110 E0.500 F3000
G1 X140 Y140 F18000
G1 X150 Y140 E0.500 F3000
;LAYER_CHANGE
;Z:0.40
G1 X100 Y100 F18000
G1 X120 Y100 E1.200 F6000
G1 X140 Y100 E0.600 F18000
;LAYER_CHANGE
;Z:0.60
M107
G1 X100 Y100 E0.100 F3000
"""


class GcodeAuditTests(unittest.TestCase):
    def test_parses_temperatures_fans_preheat_flow_and_layer1_islands(self):
        with tempfile.TemporaryDirectory() as directory:
            gcode_path = Path(directory) / "plate_1.gcode"
            gcode_path.write_text(SAMPLE_GCODE, encoding="utf-8")
            audit = audit_gcode_file(gcode_path, plate=1)

        self.assertIsInstance(audit, PlateGcodeAudit)
        self.assertEqual(audit.plate, 1)
        self.assertEqual(audit.layer_count, 3)
        self.assertIn(245.0, audit.nozzle_temps)
        self.assertIn(105.0, audit.bed_temps)
        self.assertEqual(audit.part_fan_max_pct, 80)
        self.assertEqual(audit.aux_fan_max_pct, 50)
        self.assertEqual(audit.exhaust_fan_max_pct, 70)
        self.assertTrue(audit.has_preheat_dwell)
        self.assertEqual(audit.preheat_dwell_seconds, 300)
        self.assertGreater(audit.max_volumetric_flow_mm3_s, 14.0)
        self.assertGreaterEqual(audit.max_print_speed_mm_s, 300.0)
        self.assertGreaterEqual(audit.speed_jump_count, 1)
        self.assertIsNotNone(audit.min_layer_time_s)
        self.assertLess(audit.min_layer_time_s, 6.0)
        self.assertGreaterEqual(audit.short_layers_under_6s, 1)
        self.assertIsNotNone(audit.layer1_bounds_mm)
        self.assertEqual(audit.layer1_island_count, 2)
        self.assertGreaterEqual(len(audit.layer1_segments), 3)

    def test_handles_absolute_extrusion_m82_and_g92(self):
        gcode = """\
G90
M82
;LAYER_CHANGE
;Z:0.20
G92 E0
G1 X10 Y10 F12000
G1 X30 Y10 E1.200 F6000
G92 E0
G1 X30 Y30 E1.200 F6000
"""
        with tempfile.TemporaryDirectory() as directory:
            gcode_path = Path(directory) / "plate_1.gcode"
            gcode_path.write_text(gcode, encoding="utf-8")
            audit = audit_gcode_file(gcode_path, plate=1)

        self.assertAlmostEqual(audit.max_volumetric_flow_mm3_s, 14.43, delta=0.2)
        self.assertEqual(audit.layer1_island_count, 1)

    def test_summarize_flags_excess_flow_short_layers_and_abs_fan(self):
        audit = PlateGcodeAudit(
            plate=1,
            layer_count=12,
            first_layer_nozzle_temp=245.0,
            nozzle_temps=(245.0,),
            bed_temps=(100.0,),
            part_fan_max_pct=80,
            aux_fan_max_pct=30,
            exhaust_fan_max_pct=70,
            has_preheat_dwell=True,
            preheat_dwell_seconds=300,
            max_volumetric_flow_mm3_s=18.5,
            min_layer_time_s=3.4,
            short_layers_under_6s=3,
            max_print_speed_mm_s=300.0,
            speed_jump_count=4,
            layer1_bounds_mm=(100.0, 150.0, 100.0, 150.0),
            layer1_island_count=5,
            layer1_segments=((100.0, 100.0, 110.0, 100.0),),
        )
        findings = summarize_gcode_audit(
            [audit],
            max_volumetric_limit=12.0,
            target_polymers={"ABS"},
        )
        joined = "\n".join(findings)
        self.assertIn("vazão", joined.lower())
        self.assertIn("6 s", joined)
        self.assertIn("ventoinha", joined.lower())
        self.assertIn("G4", joined)

    def test_slicer_validate_populates_gcode_audit_before_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "converted.3mf"
            project.touch()

            def runner(args, **kwargs):
                output = Path(args[args.index("--outputdir") + 1])
                (output / "plate_1.gcode").write_text(SAMPLE_GCODE, encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "", "")

            result = SlicerCLI(Path("elegoo-slicer.exe"), runner=runner).validate(project, 1)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.gcode_audit)
        self.assertIsInstance(result.gcode_audit, GcodeAuditSummary)
        self.assertEqual(len(result.gcode_audit.plates), 1)
        self.assertEqual(result.gcode_audit.plates[0].preheat_dwell_seconds, 300)


if __name__ == "__main__":
    unittest.main()
