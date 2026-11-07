"""Descoberta dos perfis JSON instalados pelo ELEGOO Slicer."""

from __future__ import annotations

import json
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
    for root in (install.data_dir / "system", install.data_dir / "user" / "default"):
        if root.exists():
            yield from root.rglob(f"{kind}/**/*.json")


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


def list_profiles(install: SlicerInstall, kind: str, nozzle: str) -> list[Profile]:
    if kind not in {"machine", "process", "filament"}:
        raise ProfileError(f"Tipo de perfil inválido: {kind}")
    target = f"Elegoo Centauri Carbon 2 {nozzle} nozzle"
    result: list[Profile] = []
    for path in _profile_paths(install, kind):
        profile = _read_profile(path, kind)
        if profile is None:
            continue
        if kind == "machine":
            if profile.name != target:
                continue
        elif kind == "process":
            compatible = profile.data.get("compatible_printers")
            if compatible and target not in compatible:
                continue
            if not compatible and f"{nozzle} nozzle" not in profile.name:
                continue
            if "ECC2" not in path.parts and "default" not in path.parts:
                continue
        else:
            if "ECC2" not in path.parts and "Generic" not in path.parts and "default" not in path.parts:
                continue
            compatible = profile.data.get("compatible_printers")
            if compatible and target not in compatible:
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
    candidates: dict[str, list[Profile]] = {}
    for candidate_path in _profile_paths(install, kind):
        candidate = _read_profile(candidate_path, kind)
        if candidate:
            candidates.setdefault(candidate.name, []).append(candidate)
            candidates.setdefault(candidate.path.stem, []).append(candidate)

    def visit(current: Path, active: set[Path]) -> dict:
        if current in active:
            raise ProfileError(f"Há um ciclo na herança do perfil: {current.name}")
        item = _read_profile(current, kind)
        if item is None:
            raise ProfileError(f"Perfil inválido: {current}")
        parent_name = item.data.get("inherits")
        if not parent_name:
            return dict(item.data)
        options = candidates.get(str(parent_name), [])
        if not options:
            raise ProfileError(f"Perfil pai não encontrado: {parent_name}")
        # Priorizar o mesmo fornecedor e o mesmo escopo do perfil filho.
        options = sorted(options, key=lambda p: ("Elegoo" not in p.path.parts, "system" not in p.path.parts, len(p.path.parts)))
        merged = visit(options[0].path, active | {current})
        merged.update(item.data)
        return merged

    return visit(path, set())
