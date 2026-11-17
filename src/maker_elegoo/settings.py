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
    "update_repo": "brenohs244/3mf-translator",
    "auto_check_updates": "0",
    "last_physical_material": "",
    "last_material_readiness": "carregado",
    "last_profile_by_material": "{}",
}

_VALID_READINESS = {"carregado", "planejado"}


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
    if result["last_material_readiness"] not in _VALID_READINESS:
        result["last_material_readiness"] = "carregado"
    return result


def load_material_memory(settings: dict) -> dict[str, str]:
    """Lê com segurança o mapa {material_label: perfil_preferido} das preferências."""
    raw = settings.get("last_profile_by_material", "{}") if isinstance(settings, dict) else "{}"
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    else:
        return {}
    if not isinstance(parsed, dict):
        return {}
    cleaned: dict[str, str] = {}
    for k, v in parsed.items():
        ks = str(k).strip()
        vs = str(v).strip()
        if ks and vs:
            cleaned[ks] = vs
    return cleaned


def save_material_memory(mapping: dict[str, str]) -> str:
    """Serializa o mapa {material_label: perfil_preferido} para gravação em settings.json."""
    cleaned = {
        str(k).strip(): str(v).strip()
        for k, v in (mapping or {}).items()
        if str(k).strip() and str(v).strip()
    }
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def save_settings(data: dict, path: Path | None = None) -> None:
    target = Path(path) if path else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: str(data.get(key, default)) for key, default in DEFAULTS.items()}
    if not _valid_nozzle(clean["nozzle"]):
        clean["nozzle"] = "0.4"
    if clean["last_material_readiness"] not in _VALID_READINESS:
        clean["last_material_readiness"] = "carregado"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
