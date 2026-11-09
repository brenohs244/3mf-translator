"""Descoberta dos perfis JSON instalados pelo ELEGOO Slicer."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path


class ProfileError(ValueError):
    """Perfil ausente ou cadeia de herança inválida."""


@dataclass(frozen=True)
class SlicerInstall:
    executable: Path
    data_dir: Path


@dataclass(frozen=True)
class Profile:
    name: str
    kind: str
    path: Path
    data: dict


def discover_slicer(*, executable: Path | None = None, data_dir: Path | None = None) -> SlicerInstall:
    if executable is None:
        configured = os.getenv("ELEGOO_SLICER_EXE")
        candidates = [Path(configured)] if configured else []
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.getenv(variable):
                candidates.append(Path(os.environ[variable]) / "ElegooSlicer" / "elegoo-slicer.exe")
        executable = next((path for path in candidates if path.is_file()), None)
    if data_dir is None:
        roaming = os.getenv("APPDATA")
        data_dir = Path(roaming) / "ElegooSlicer" if roaming else None
    if not executable or not Path(executable).is_file():
        raise ProfileError("ELEGOO Slicer não encontrado; configure o caminho do executável")
    if not data_dir or not Path(data_dir).is_dir():
        raise ProfileError("Perfis do ELEGOO Slicer não encontrados em AppData")
    return SlicerInstall(Path(executable), Path(data_dir))


def _profile_paths(install: SlicerInstall, kind: str):
    system = install.data_dir / "system"
    if system.is_dir():
        yield from system.rglob(f"{kind}/**/*.json")
    users = install.data_dir / "user"
    if users.is_dir():
        for account in users.iterdir():
            root = account / kind
            if root.is_dir():
                yield from root.rglob("*.json")


def _read_profile(path: Path, kind: str) -> Profile | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    declared = data.get("type")
    if declared is not None and declared != kind:
        return None
    return Profile(str(data.get("name") or path.stem), kind, path, data)


def _candidate_index(install: SlicerInstall, kind: str) -> dict[str, list[Profile]]:
    candidates: dict[str, list[Profile]] = {}
    for path in _profile_paths(install, kind):
        candidate = _read_profile(path, kind)
        if candidate:
            candidates.setdefault(candidate.name, []).append(candidate)
            candidates.setdefault(candidate.path.stem, []).append(candidate)
    return candidates


def _parent(options: list[Profile]) -> Profile:
    return sorted(options, key=lambda p: ("Elegoo" not in p.path.parts,
                                          "system" not in p.path.parts, len(p.path.parts)))[0]


def _resolve(profile: Profile, candidates: dict[str, list[Profile]], active: set[Path]) -> dict:
    if profile.path in active:
        raise ProfileError(f"Há um ciclo na herança do perfil: {profile.path.name}")
    parent_name = profile.data.get("inherits")
    if not parent_name:
        return dict(profile.data)
    options = candidates.get(str(parent_name), [])
    if not options:
        raise ProfileError(f"Perfil pai não encontrado: {parent_name}")
    merged = _resolve(_parent(options), candidates, active | {profile.path})
    merged.update(profile.data)
    return merged


def _machine_diameter(config: dict) -> float | None:
    diameter = config.get("nozzle_diameter")
    if not isinstance(diameter, list) or not diameter:
        return None
    try:
        value = float(diameter[0])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0.1 <= value <= 2 else None


def machine_family_names(machine: Profile, install: SlicerInstall) -> set[str]:
    candidates = _candidate_index(install, "machine")
    names = {machine.name}
    current = machine
    visited: set[Path] = set()
    while current.data.get("inherits"):
        if current.path in visited:
            raise ProfileError(f"Há um ciclo na herança do perfil: {current.path.name}")
        visited.add(current.path)
        parent_name = str(current.data["inherits"])
        options = candidates.get(parent_name, [])
        if not options:
            raise ProfileError(f"Perfil pai não encontrado: {parent_name}")
        current = _parent(options)
        names.add(current.name)
    return names


def list_profiles(install: SlicerInstall, kind: str, nozzle: str | None,
                  *, machine: Profile | None = None) -> list[Profile]:
    if kind not in {"machine", "process", "filament"}:
        raise ProfileError(f"Tipo de perfil inválido: {kind}")
    target = f"Elegoo Centauri Carbon 2 {nozzle} nozzle" if nozzle else None
    compatible_names = machine_family_names(machine, install) if machine else ({target} if target else set())
    candidates = _candidate_index(install, kind)
    result: list[Profile] = []
    for path in _profile_paths(install, kind):
        profile = _read_profile(path, kind)
        if profile is None:
            continue
        try:
            resolved = _resolve(profile, candidates, set())
        except ProfileError:
            continue
        if kind == "machine":
            diameter = _machine_diameter(resolved)
            if (resolved.get("printer_model") != "Elegoo Centauri Carbon 2"
                    or diameter is None or (nozzle and diameter != float(nozzle))):
                continue
        elif kind == "process":
            compatible = resolved.get("compatible_printers")
            if compatible and not compatible_names.intersection(compatible):
                continue
            if not compatible and (not nozzle or f"{nozzle} nozzle" not in profile.name):
                continue
            if "ECC2" not in path.parts and "user" not in path.parts:
                continue
        else:
            if "ECC2" not in path.parts and "Generic" not in path.parts and "user" not in path.parts:
                continue
            compatible = resolved.get("compatible_printers")
            if compatible and not compatible_names.intersection(compatible):
                continue
        result.append(profile)
    return sorted(result, key=lambda profile: profile.name.casefold())


def resolve_profile(profile: Profile | Path, install: SlicerInstall) -> dict:
    path = profile.path if isinstance(profile, Profile) else Path(profile)
    kind = profile.kind if isinstance(profile, Profile) else path.parent.parent.name if path.parent.name == "ECC2" else path.parent.name
    if kind not in {"machine", "process", "filament"}:
        kind = next((part for part in path.parts if part in {"machine", "process", "filament"}), "")
    if not kind:
        raise ProfileError(f"Tipo de perfil não identificado: {path}")
    item = _read_profile(path, kind)
    if item is None:
        raise ProfileError(f"Perfil inválido: {path}")
    return _resolve(item, _candidate_index(install, kind), set())
