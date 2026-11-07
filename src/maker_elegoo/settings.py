"""Preferências locais, sem credenciais de serviços externos."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULTS = {"nozzle": "0.4", "last_dir": "", "slicer_exe": ""}


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
    if result["nozzle"] not in {"0.2", "0.4", "0.8"}:
        result["nozzle"] = "0.4"
    return result


def save_settings(data: dict, path: Path | None = None) -> None:
    target = Path(path) if path else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: str(data.get(key, default)) for key, default in DEFAULTS.items()}
    if clean["nozzle"] not in {"0.2", "0.4", "0.8"}:
        clean["nozzle"] = "0.4"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
