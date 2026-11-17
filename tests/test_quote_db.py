import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.gcode_audit import GcodeAuditSummary, PlateGcodeAudit
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.material_selection import MaterialIdentity, SlotMaterialTarget
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.scale import RescaleResult, ScaleRisk
from maker_elegoo.slicer import PlateValidationMetric, ValidationResult


class QuoteDBTests(unittest.TestCase):
    def _sample_profiles(self, root: Path):
        mach = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", root / "m.json", {
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
        })
        proc = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", root / "p.json", {
            "layer_height": "0.20",
            "enable_support": "1",
        })
        fil1 = Profile("ENDER PLA", "filament", root / "f1.json", {"filament_type": ["PLA"]})
        fil2 = Profile("Elegoo ABS @ECC2", "filament", root / "f2.json", {"filament_type": ["ABS"]})
        return mach, proc, fil1, fil2

    def test_quote_db_path_precedence_and_schema_wal_creation(self):
        from maker_elegoo.quote_db import SCHEMA_VERSION, ensure_quote_db, quote_db_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": str(root / "cfg")}, clear=False):
                default_db = quote_db_path(settings={"quote_db_path": ""})
                self.assertEqual(default_db, root / "cfg" / "maker_elegoo_quotes.db")

                from_settings = quote_db_path(settings={"quote_db_path": str(root / "prefs.db")})
                self.assertEqual(from_settings, root / "prefs.db")

            with patch.dict(os.environ, {"MAKER_ELEGOO_QUOTE_DB": str(root / "env.db")}, clear=False):
                self.assertEqual(quote_db_path(), root / "env.db")
                self.assertEqual(quote_db_path(root / "explicit.db"), root / "explicit.db")

            db = ensure_quote_db(root / "quotes.db")
            self.assertTrue(db.is_file())
            with closing(sqlite3.connect(db)) as conn:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                ver = conn.execute("PRAGMA user_version").fetchone()[0]
                meta = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
                }
            self.assertEqual(str(mode).lower(), "wal")
            self.assertEqual(ver, SCHEMA_VERSION)
            self.assertEqual(meta, (str(SCHEMA_VERSION),))
            self.assertTrue(
                {"schema_metadata", "simulations", "simulation_plates", "simulation_slots", "v_simulations_summary"}.issubset(tables)
            )

    def test_records_single_and_multislot_simulations_and_allows_external_ro_read(self):
        from maker_elegoo.quote_db import record_simulation

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_file = root / "quotes.db"
            src_3mf = root / "suporte_camera.3mf"
            src_3mf.write_bytes(b"fake-3mf-payload-for-sha256")
            mach, proc, fil1, fil2 = self._sample_profiles(root)

            # 1) Simulacao 1 slot com escala + total sem quebra por slot no G-code
            proj_single = ProjectInfo(
                src_3mf,
                {"layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 2, ("1",), ("1",), ("1",)),),
                ("Suporte",),
                (),
                (),
                used_filament_slots=("1",),
            )
            plan_single = ConversionPlan(
                mach, proc, (fil1,), mach.data, proc.data, (fil1.data,), {}, {}, {}, {}, ()
            )
            audit_single = GcodeAuditSummary(plates=(
                PlateGcodeAudit(1, 120, 215.0, (215.0,), (60.0,), 100, 50, 0, False, 0, 14.5, 4.2, 3, 220.0, 2, None, 1),
            ))
            val_single = ValidationResult(
                True, 1, "ok", (), 5400, 42.5,
                (PlateValidationMetric(1, 5400, 42.5),),
                audit_single,
            )
            scale_res = RescaleResult(
                src_3mf, 1.25, (40.0, 20.0, 10.0), (50.0, 25.0, 12.5),
                ScaleRisk(1.25, (40.0, 20.0, 10.0), (50.0, 25.0, 12.5), (), None, False),
                False,
            )
            rec1 = record_simulation(
                proj_single,
                plan_single,
                val_single,
                slot_targets=(SlotMaterialTarget(1, MaterialIdentity("PLA"), fil1, True, planned_only=True),),
                readiness="planejado",
                purpose="esforco",
                priority="equilibrio",
                rescale_info=scale_res,
                db_path=db_file,
            )
            self.assertEqual(rec1.simulation_id, 1)
            self.assertEqual(rec1.estimated_seconds, 5400)
            self.assertAlmostEqual(rec1.filament_grams, 42.5)
            self.assertEqual(rec1.slot_count, 1)

            # 2) Simulacao multisslot com quebra exata por slot vs outra sem quebra no G-code
            proj_multi = ProjectInfo(
                src_3mf,
                {"layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "P1"), FilamentInfo(2, "ABS", "#000000", "A1")),
                (PlateInfo(1, 1, ("1", "2"), ("1", "2"), ("1", "2")), PlateInfo(2, 1, ("1",), ("1",), ("1",))),
                ("Peca A", "Peca B"),
                (),
                (),
                used_filament_slots=("1", "2"),
            )
            plan_multi = ConversionPlan(
                mach, proc, (fil1, fil2), mach.data, proc.data, (fil1.data, fil2.data), {}, {}, {}, {}, ()
            )
            targets_multi = (
                SlotMaterialTarget(1, MaterialIdentity("PLA"), fil1, True),
                SlotMaterialTarget(2, MaterialIdentity("ABS"), fil2, True),
            )
            val_multi_exact = ValidationResult(
                True, 2, "ok", (), 3600, 30.0,
                (
                    PlateValidationMetric(1, 2400, 20.0, (12.5, 7.5)),
                    PlateValidationMetric(2, 1200, 10.0, (10.0, 0.0)),
                ),
                None,
                (22.5, 7.5),
            )
            rec2 = record_simulation(
                proj_multi, plan_multi, val_multi_exact,
                slot_targets=targets_multi, readiness="carregado", db_path=db_file,
            )
            self.assertEqual(rec2.simulation_id, 2)

            val_multi_no_split = ValidationResult(
                True, 1, "ok", (), 1800, 20.0,
                (PlateValidationMetric(1, 1800, 20.0),),
            )
            rec3 = record_simulation(
                proj_multi, plan_multi, val_multi_no_split,
                slot_targets=targets_multi, readiness="carregado", db_path=db_file,
            )
            self.assertEqual(rec3.simulation_id, 3)

            # Sistema externo lê em modo somente-leitura via URI WAL
            ro_uri = f"file:{db_file.as_posix()}?mode=ro"
            with closing(sqlite3.connect(ro_uri, uri=True)) as ext:
                ext.row_factory = sqlite3.Row
                rows = ext.execute("SELECT * FROM v_simulations_summary ORDER BY id ASC").fetchall()
                slots1 = ext.execute("SELECT * FROM simulation_slots WHERE simulation_id = 1").fetchall()
                slots2 = ext.execute("SELECT * FROM simulation_slots WHERE simulation_id = 2 ORDER BY slot_index").fetchall()
                slots3 = ext.execute("SELECT * FROM simulation_slots WHERE simulation_id = 3 ORDER BY slot_index").fetchall()

            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["project_name"], "suporte_camera.3mf")
            self.assertEqual(len(rows[0]["project_sha256"]), 64)
            self.assertAlmostEqual(rows[0]["scale_percent"], 125.0)
            self.assertAlmostEqual(rows[0]["size_x_mm"], 50.0)
            self.assertAlmostEqual(rows[0]["size_z_mm"], 12.5)
            self.assertAlmostEqual(rows[0]["estimated_hours"], 1.5)
            self.assertEqual(rows[0]["has_supports"], 1)
            self.assertEqual(rows[0]["short_layers_under_6s"], 3)
            self.assertAlmostEqual(slots1[0]["filament_grams"], 42.5)
            self.assertEqual(slots1[0]["profile_name"], "ENDER PLA")
            self.assertEqual(slots1[0]["readiness"], "planejado")

            self.assertEqual(rows[1]["plate_count"], 2)
            self.assertEqual(rows[1]["materials_summary"], "PLA + ABS")
            self.assertAlmostEqual(slots2[0]["filament_grams"], 22.5)
            self.assertAlmostEqual(slots2[1]["filament_grams"], 7.5)

            # Multisslot sem divisão no G-code não chuta divisão artificial
            self.assertIsNone(slots3[0]["filament_grams"])
            self.assertIsNone(slots3[1]["filament_grams"])
