"""Banco de dados SQLite local para registrar simulações de fatiamento para orçamento."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import __version__
from .mapping import ConversionPlan
from .material_selection import SlotMaterialTarget, active_filament_slots, parse_material_identity
from .project import ProjectInfo
from .settings import load_settings, settings_path
from .slicer import ValidationResult

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    app_version TEXT NOT NULL,
    project_name TEXT NOT NULL,
    project_sha256 TEXT NOT NULL DEFAULT '',
    machine_name TEXT NOT NULL,
    nozzle_mm TEXT NOT NULL,
    process_name TEXT NOT NULL,
    layer_height_mm REAL,
    purpose TEXT NOT NULL DEFAULT 'decorativa',
    priority TEXT NOT NULL DEFAULT 'equilibrio',
    scale_percent REAL NOT NULL DEFAULT 100.0,
    plate_count INTEGER NOT NULL DEFAULT 1,
    part_count INTEGER NOT NULL DEFAULT 0,
    estimated_seconds INTEGER NOT NULL DEFAULT 0,
    filament_grams REAL NOT NULL DEFAULT 0.0,
    size_x_mm REAL,
    size_y_mm REAL,
    size_z_mm REAL,
    has_supports INTEGER NOT NULL DEFAULT 0,
    short_layers_under_6s INTEGER NOT NULL DEFAULT 0,
    max_volumetric_flow_mm3_s REAL,
    gcode_summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS simulation_plates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    plate_index INTEGER NOT NULL,
    estimated_seconds INTEGER,
    filament_grams REAL,
    layer_count INTEGER,
    max_nozzle_temp_c REAL,
    max_bed_temp_c REAL
);

CREATE TABLE IF NOT EXISTS simulation_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    slot_index INTEGER NOT NULL,
    material_type TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    color_hex TEXT NOT NULL DEFAULT '',
    readiness TEXT NOT NULL DEFAULT 'carregado',
    filament_grams REAL
);

CREATE INDEX IF NOT EXISTS idx_simulations_created_at ON simulations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_simulations_sha256 ON simulations(project_sha256);
CREATE INDEX IF NOT EXISTS idx_sim_plates_sim_id ON simulation_plates(simulation_id, plate_index);
CREATE INDEX IF NOT EXISTS idx_sim_slots_sim_id ON simulation_slots(simulation_id, slot_index);

CREATE VIEW IF NOT EXISTS v_simulations_summary AS
SELECT
    s.*,
    ROUND(COALESCE(s.estimated_seconds, 0) / 3600.0, 4) AS estimated_hours,
    COALESCE(agg.slot_count, 0) AS slot_count,
    COALESCE(agg.materials_summary, '') AS materials_summary,
    COALESCE(agg.profiles_summary, '') AS profiles_summary
FROM simulations AS s
LEFT JOIN (
    SELECT
        simulation_id,
        COUNT(*) AS slot_count,
        GROUP_CONCAT(material_type, ' + ') AS materials_summary,
        GROUP_CONCAT(profile_name, ' + ') AS profiles_summary
    FROM (
        SELECT simulation_id, material_type, profile_name
        FROM simulation_slots
        ORDER BY simulation_id, slot_index
    )
    GROUP BY simulation_id
) AS agg
    ON agg.simulation_id = s.id;
"""


@dataclass(frozen=True)
class QuoteSlotRecord:
    slot_index: int
    material_type: str
    profile_name: str
    color_hex: str
    readiness: str
    filament_grams: float | None


@dataclass(frozen=True)
class QuotePlateRecord:
    plate_index: int
    estimated_seconds: int | None
    filament_grams: float | None
    layer_count: int | None
    max_nozzle_temp_c: float | None
    max_bed_temp_c: float | None


@dataclass(frozen=True)
class SimulationRecordResult:
    simulation_id: int
    db_path: Path
    created_at: str
    estimated_seconds: int
    filament_grams: float
    plate_count: int
    slot_count: int


def quote_db_path(custom_path: str | Path | None = None, *, settings: dict | None = None) -> Path:
    """Resolve o caminho do SQLite de orçamentos por CLI/argumento, env, settings ou padrão AppData."""
    if custom_path is not None and str(custom_path).strip():
        return Path(str(custom_path).strip())
    env_override = (os.getenv("MAKER_ELEGOO_QUOTE_DB") or "").strip()
    if env_override:
        return Path(env_override)
    loaded = settings if settings is not None else load_settings()
    configured = str(loaded.get("quote_db_path", "") or "").strip() if isinstance(loaded, dict) else ""
    if configured:
        return Path(configured)
    return settings_path().parent / "maker_elegoo_quotes.db"


def compute_file_sha256(path: Path) -> str:
    """Calcula SHA-256 em streaming para identificar re-simulações sem guardar o 3MF no banco."""
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def ensure_quote_db(db_path: Path | None = None) -> Path:
    """Inicializa o banco SQLite em modo WAL com schema versionado e view de leitura externa."""
    target = quote_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(target), timeout=5.0)) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute(
            "INSERT OR REPLACE INTO schema_metadata (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_metadata (key, value) VALUES (?, ?)",
            ("producer", "maker-elegoo"),
        )
        conn.commit()
    return target


def _first_scalar(value: object, default: str = "") -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else default
    if value is None:
        return default
    return str(value)


def _opt_float(value: object) -> float | None:
    txt = _first_scalar(value, "").strip()
    if not txt:
        return None
    try:
        num = float(txt)
        return num if num == num else None
    except ValueError:
        return None


def _is_truthy_setting(value: object) -> bool:
    return _first_scalar(value, "").strip().lower() in {"1", "true", "yes", "on"}


def record_simulation(
    project: ProjectInfo,
    plan: ConversionPlan,
    validation: ValidationResult,
    *,
    slot_targets: Iterable[SlotMaterialTarget] = (),
    readiness: str = "carregado",
    purpose: str = "decorativa",
    priority: str = "equilibrio",
    scale_percent: float | None = None,
    rescale_info: object | None = None,
    db_path: Path | None = None,
    created_at: str | None = None,
) -> SimulationRecordResult:
    """Registra uma simulação fatiada com sucesso no banco SQLite de orçamentos."""
    if not validation.success:
        raise ValueError("Apenas simulações fatiadas com sucesso devem ser registradas no banco de orçamento.")

    target_db = ensure_quote_db(db_path)
    stamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    clean_readiness = readiness if readiness in {"carregado", "planejado"} else "carregado"
    project_name = project.path.name if getattr(project, "path", None) else "projeto.3mf"
    project_sha = compute_file_sha256(project.path) if getattr(project, "path", None) else ""

    nozzle_str = _first_scalar(plan.machine_settings.get("nozzle_diameter"), "").strip()
    layer_height = _opt_float(plan.process_settings.get("layer_height"))

    resolved_scale_pct = 100.0
    if rescale_info is not None and getattr(rescale_info, "scale_factor", None):
        resolved_scale_pct = round(float(rescale_info.scale_factor) * 100.0, 2)
    elif scale_percent is not None:
        resolved_scale_pct = round(float(scale_percent), 2)

    size_x: float | None = None
    size_y: float | None = None
    size_z: float | None = None
    if rescale_info is not None and getattr(rescale_info, "new_size_mm", None):
        dims = rescale_info.new_size_mm
        size_x, size_y, size_z = (round(float(dims[0]), 2), round(float(dims[1]), 2), round(float(dims[2]), 2))
    else:
        geom = getattr(project, "geometry_summary", None)
        if geom is not None:
            factor = resolved_scale_pct / 100.0
            size_x = round(float(geom.size_x) * factor, 2)
            size_y = round(float(geom.size_y) * factor, 2)
            size_z = round(float(geom.size_z) * factor, 2)

    has_supports = int(
        _is_truthy_setting(plan.process_settings.get("enable_support"))
        or _is_truthy_setting(project.source_settings.get("enable_support"))
    )

    audit = getattr(validation, "gcode_audit", None)
    audit_by_plate = {
        int(pa.plate): pa
        for pa in (getattr(audit, "plates", ()) or ())
    }
    short_layers_total = sum(int(getattr(pa, "short_layers_under_6s", 0) or 0) for pa in audit_by_plate.values())
    max_flow_vals = [
        float(pa.max_volumetric_flow_mm3_s)
        for pa in audit_by_plate.values()
        if getattr(pa, "max_volumetric_flow_mm3_s", None) is not None
    ]
    max_vol_flow = round(max(max_flow_vals), 2) if max_flow_vals else None

    plate_records: list[QuotePlateRecord] = []
    if validation.plate_metrics:
        for pm in validation.plate_metrics:
            pa = audit_by_plate.get(int(pm.plate))
            max_nozzle = max(pa.nozzle_temps) if (pa and pa.nozzle_temps) else None
            max_bed = max(pa.bed_temps) if (pa and pa.bed_temps) else None
            plate_records.append(
                QuotePlateRecord(
                    plate_index=int(pm.plate),
                    estimated_seconds=int(pm.estimated_seconds) if pm.estimated_seconds is not None else None,
                    filament_grams=round(float(pm.filament_grams), 4) if pm.filament_grams is not None else None,
                    layer_count=int(pa.layer_count) if pa is not None else None,
                    max_nozzle_temp_c=float(max_nozzle) if max_nozzle is not None else None,
                    max_bed_temp_c=float(max_bed) if max_bed is not None else None,
                )
            )
    else:
        for idx in range(1, max(1, int(validation.plate_count)) + 1):
            pa = audit_by_plate.get(idx)
            plate_records.append(
                QuotePlateRecord(
                    plate_index=idx,
                    estimated_seconds=validation.estimated_seconds if validation.plate_count == 1 else None,
                    filament_grams=validation.filament_grams if validation.plate_count == 1 else None,
                    layer_count=int(pa.layer_count) if pa is not None else None,
                    max_nozzle_temp_c=max(pa.nozzle_temps) if (pa and pa.nozzle_temps) else None,
                    max_bed_temp_c=max(pa.bed_temps) if (pa and pa.bed_temps) else None,
                )
            )

    active_slots = set(active_filament_slots(project))
    target_by_slot = {int(t.slot): t for t in slot_targets}
    slot_grams_tuple = tuple(getattr(validation, "slot_filament_grams", ()) or ())
    slot_records: list[QuoteSlotRecord] = []
    for idx, fil in enumerate(project.filaments):
        if active_slots and fil.slot not in active_slots:
            continue
        tgt = target_by_slot.get(fil.slot)
        prof_name = ""
        if tgt and tgt.profile is not None:
            prof_name = tgt.profile.name
        elif idx < len(plan.filaments):
            prof_name = plan.filaments[idx].name
        mat_label = ""
        if tgt and tgt.identity.label and tgt.identity.polymer not in {"", "DESCONHECIDO", "NAO_SEI"}:
            mat_label = tgt.identity.label
        elif idx < len(plan.filament_settings):
            ft = _first_scalar(plan.filament_settings[idx].get("filament_type"), "")
            mat_label = parse_material_identity(ft).label if ft else ""
        if not mat_label or mat_label in {"DESCONHECIDO", "NAO_SEI"}:
            mat_label = parse_material_identity(fil.material).label

        grams_for_slot: float | None = None
        if idx < len(slot_grams_tuple):
            grams_for_slot = round(float(slot_grams_tuple[idx]), 4)
        elif len(active_slots) == 1 and validation.filament_grams is not None:
            grams_for_slot = round(float(validation.filament_grams), 4)

        slot_records.append(
            QuoteSlotRecord(
                slot_index=int(fil.slot),
                material_type=mat_label,
                profile_name=prof_name,
                color_hex=fil.color or "",
                readiness=clean_readiness,
                filament_grams=grams_for_slot,
            )
        )

    total_seconds = int(validation.estimated_seconds or 0)
    total_grams = round(float(validation.filament_grams or 0.0), 4)
    part_count = len(project.objects) if getattr(project, "objects", None) else sum(
        int(p.instance_count or 0) for p in getattr(project, "plates", ()) or ()
    )

    summary_payload = {
        "warnings": list(getattr(validation, "warnings", ()) or ()),
        "audit_findings": list(getattr(audit, "findings", ()) or ()),
        "slot_filament_grams_raw": list(slot_grams_tuple),
    }

    with closing(sqlite3.connect(str(target_db), timeout=5.0)) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.execute(
            """
            INSERT INTO simulations (
                created_at, app_version, project_name, project_sha256,
                machine_name, nozzle_mm, process_name, layer_height_mm,
                purpose, priority, scale_percent, plate_count, part_count,
                estimated_seconds, filament_grams,
                size_x_mm, size_y_mm, size_z_mm,
                has_supports, short_layers_under_6s, max_volumetric_flow_mm3_s,
                gcode_summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stamp,
                __version__,
                project_name,
                project_sha,
                plan.machine.name,
                nozzle_str,
                plan.process.name,
                layer_height,
                purpose,
                priority,
                resolved_scale_pct,
                int(validation.plate_count),
                int(part_count),
                total_seconds,
                total_grams,
                size_x,
                size_y,
                size_z,
                has_supports,
                short_layers_total,
                max_vol_flow,
                json.dumps(summary_payload, ensure_ascii=False),
            ),
        )
        sim_id = int(cur.lastrowid)
        for plate in plate_records:
            conn.execute(
                """
                INSERT INTO simulation_plates (
                    simulation_id, plate_index, estimated_seconds, filament_grams,
                    layer_count, max_nozzle_temp_c, max_bed_temp_c
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sim_id,
                    plate.plate_index,
                    plate.estimated_seconds,
                    plate.filament_grams,
                    plate.layer_count,
                    plate.max_nozzle_temp_c,
                    plate.max_bed_temp_c,
                ),
            )
        for slot in slot_records:
            conn.execute(
                """
                INSERT INTO simulation_slots (
                    simulation_id, slot_index, material_type, profile_name,
                    color_hex, readiness, filament_grams
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sim_id,
                    slot.slot_index,
                    slot.material_type,
                    slot.profile_name,
                    slot.color_hex,
                    slot.readiness,
                    slot.filament_grams,
                ),
            )
        conn.commit()

    return SimulationRecordResult(
        simulation_id=sim_id,
        db_path=target_db,
        created_at=stamp,
        estimated_seconds=total_seconds,
        filament_grams=total_grams,
        plate_count=int(validation.plate_count),
        slot_count=len(slot_records),
    )
