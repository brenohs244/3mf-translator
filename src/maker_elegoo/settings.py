"""Preferências locais, sem credenciais de serviços externos."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path


DEFAULTS = {
    "nozzle": "0.4",
    "machine": "",
    "last_dir": "",
    "slicer_exe": "",
    "mode": "offline",
    "purpose": "decorativa",
    "priority": "equilibrio",
    "load_type": "nao_sei",
    "criticality": "nao_sei",
    "fit_clearance": "nao_sei",
    "heat_exposure": "nao_sei",
    "save_print_history": "0",
    "ai_model": "gemini-3.8-flash",
}


def _valid_nozzle(value: str) -> bool:
    try:
        diameter = float(value)
        return math.isfinite(diameter) and 0.1 <= diameter <= 2
    except ValueError:
        return False


def settings_path() -> Path:
    override = os.getenv("MAKER_ELEGOO_CONFIG_DIR")
    if override:
        return Path(override) / "settings.json"
    base = Path(os.getenv("APPDATA") or Path.home())
    return base / "MakerElegoo" / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    target = Path(path) if path else settings_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(DEFAULTS)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return dict(DEFAULTS)
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        if isinstance(raw.get(key), str):
            result[key] = raw[key]
    if not _valid_nozzle(result["nozzle"]):
        result["nozzle"] = "0.4"
    return result


def save_settings(data: dict, path: Path | None = None) -> None:
    target = Path(path) if path else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: str(data.get(key, default)) for key, default in DEFAULTS.items()}
    if not _valid_nozzle(clean["nozzle"]):
        clean["nozzle"] = "0.4"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
