"""Descoberta dos perfis JSON instalados pelo ELEGOO Slicer."""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
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


_ALL_KINDS = ("machine", "process", "filament")
_CACHE_LOCK = threading.RLock()
_PROFILE_CACHE: dict[tuple[str, str], "_KindCacheEntry"] = {}


@dataclass
class _KindCacheEntry:
    file_sigs: dict[Path, tuple[int, int]]
    profiles: list[Profile]
    candidates: dict[str, list[Profile]]
    resolved_by_path: dict[Path, dict] = field(default_factory=dict)
    chains_by_path: dict[Path, tuple[Path, ...]] = field(default_factory=dict)
    family_by_path: dict[Path, set[str]] = field(default_factory=dict)
    list_results: dict[tuple[str | None, str | None], tuple[Profile, ...]] = field(default_factory=dict)


def clear_profile_cache() -> None:
    """Limpa o cache em memória de perfis e heranças do ELEGOO Slicer."""
    with _CACHE_LOCK:
        _PROFILE_CACHE.clear()


def _install_cache_key(install: SlicerInstall, kind: str) -> tuple[str, str]:
    try:
        base = str(install.data_dir.resolve())
    except OSError:
        base = str(install.data_dir)
    return base, kind


def _file_sig(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _copy_resolved(data: dict) -> dict:
    return {k: list(v) if isinstance(v, list) else v for k, v in data.items()}


def _walk_kind_dirs(root: Path, kind: str, out: list[Path]) -> None:
    other_kinds = set(_ALL_KINDS) - {kind}
    for dirpath, dirnames, filenames in os.walk(root):
        base = os.path.basename(dirpath)
        if base in other_kinds:
            dirnames[:] = []
            continue
        if base == kind:
            # Dentro da árvore do tipo alvo, todos os *.json pertencem a esse kind
            for sub_dir, _, sub_files in os.walk(dirpath):
                sub_p = Path(sub_dir)
                for fn in sub_files:
                    if fn.endswith(".json"):
                        out.append(sub_p / fn)
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in other_kinds)


def _profile_paths(install: SlicerInstall, kind: str) -> list[Path]:
    paths: list[Path] = []
    system = install.data_dir / "system"
    if system.is_dir():
        _walk_kind_dirs(system, kind, paths)
    users = install.data_dir / "user"
    if users.is_dir():
        try:
            accounts = sorted(users.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            accounts = []
        for account in accounts:
            root = account / kind
            if root.is_dir():
                for dirpath, _, filenames in os.walk(root):
                    cur = Path(dirpath)
                    for fn in sorted(filenames):
                        if fn.endswith(".json"):
                            paths.append(cur / fn)
    return paths


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


def _parent(options: list[Profile]) -> Profile:
    return sorted(options, key=lambda p: ("Elegoo" not in p.path.parts,
                                          "system" not in p.path.parts, len(p.path.parts)))[0]


def _resolve_with_chain(
    profile: Profile,
    candidates: dict[str, list[Profile]],
    active: set[Path],
    memo: dict[Path, tuple[dict, tuple[Path, ...]]],
) -> tuple[dict, tuple[Path, ...]]:
    if profile.path in active:
        raise ProfileError(f"Há um ciclo na herança do perfil: {profile.path.name}")
    cached = memo.get(profile.path)
    if cached is not None:
        return cached
    parent_name = profile.data.get("inherits")
    if not parent_name:
        res = (dict(profile.data), (profile.path,))
        memo[profile.path] = res
        return res
    options = candidates.get(str(parent_name), [])
    if not options:
        raise ProfileError(f"Perfil pai não encontrado: {parent_name}")
    parent_dict, parent_chain = _resolve_with_chain(
        _parent(options), candidates, active | {profile.path}, memo
    )
    merged = dict(parent_dict)
    merged.update(profile.data)
    res = (merged, parent_chain + (profile.path,))
    memo[profile.path] = res
    return res


def _resolve(profile: Profile, candidates: dict[str, list[Profile]], active: set[Path]) -> dict:
    resolved, _ = _resolve_with_chain(profile, candidates, active, {})
    return resolved


def _build_kind_entry(install: SlicerInstall, kind: str, paths: list[Path], sigs: dict[Path, tuple[int, int]]) -> _KindCacheEntry:
    loaded: list[Profile] = []
    candidates: dict[str, list[Profile]] = {}
    for path in paths:
        item = _read_profile(path, kind)
        if item is None:
            continue
        loaded.append(item)
        candidates.setdefault(item.name, []).append(item)
        candidates.setdefault(item.path.stem, []).append(item)

    entry = _KindCacheEntry(
        file_sigs=sigs,
        profiles=loaded,
        candidates=candidates,
    )
    memo: dict[Path, tuple[dict, tuple[Path, ...]]] = {}
    for item in loaded:
        try:
            resolved, chain = _resolve_with_chain(item, candidates, set(), memo)
        except ProfileError:
            continue
        entry.resolved_by_path[item.path] = resolved
        entry.chains_by_path[item.path] = chain
    return entry


def _scan_kind_sigs(install: SlicerInstall, kind: str) -> tuple[list[Path], dict[Path, tuple[int, int]]]:
    paths = _profile_paths(install, kind)
    sigs: dict[Path, tuple[int, int]] = {}
    for path in paths:
        sig = _file_sig(path)
        if sig is not None:
            sigs[path] = sig
    return paths, sigs


def _get_kind_entry(install: SlicerInstall, kind: str) -> _KindCacheEntry:
    key = _install_cache_key(install, kind)
    paths, sigs = _scan_kind_sigs(install, kind)
    with _CACHE_LOCK:
        existing = _PROFILE_CACHE.get(key)
        if existing is not None and existing.file_sigs == sigs:
            return existing
    entry = _build_kind_entry(install, kind, paths, sigs)
    with _CACHE_LOCK:
        _PROFILE_CACHE[key] = entry
    return entry


def _candidate_index(install: SlicerInstall, kind: str) -> dict[str, list[Profile]]:
    return _get_kind_entry(install, kind).candidates


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
    entry = _get_kind_entry(install, "machine")
    with _CACHE_LOCK:
        cached = entry.family_by_path.get(machine.path)
        if cached is not None:
            return set(cached)
    candidates = entry.candidates
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
    with _CACHE_LOCK:
        entry.family_by_path[machine.path] = set(names)
    return names


def list_profiles(install: SlicerInstall, kind: str, nozzle: str | None,
                  *, machine: Profile | None = None) -> list[Profile]:
    if kind not in {"machine", "process", "filament"}:
        raise ProfileError(f"Tipo de perfil inválido: {kind}")
    entry = _get_kind_entry(install, kind)
    machine_key = machine.name if machine else None
    cache_q = (nozzle, machine_key)
    if machine is not None:
        # Garante que a lista de máquinas também é validada contra edições recentes
        compatible_names = machine_family_names(machine, install)
    else:
        target = f"Elegoo Centauri Carbon 2 {nozzle} nozzle" if nozzle else None
        compatible_names = {target} if target else set()

    with _CACHE_LOCK:
        cached_list = entry.list_results.get(cache_q)
        if cached_list is not None and (machine is None or compatible_names == machine_family_names(machine, install)):
            return list(cached_list)

    result: list[Profile] = []
    for profile in entry.profiles:
        resolved = entry.resolved_by_path.get(profile.path)
        if resolved is None:
            continue
        path = profile.path
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
    ordered = tuple(sorted(result, key=lambda profile: profile.name.casefold()))
    with _CACHE_LOCK:
        entry.list_results[cache_q] = ordered
    return list(ordered)


def resolve_profile(profile: Profile | Path, install: SlicerInstall) -> dict:
    path = profile.path if isinstance(profile, Profile) else Path(profile)
    kind = profile.kind if isinstance(profile, Profile) else path.parent.parent.name if path.parent.name == "ECC2" else path.parent.name
    if kind not in {"machine", "process", "filament"}:
        kind = next((part for part in path.parts if part in {"machine", "process", "filament"}), "")
    if not kind:
        raise ProfileError(f"Tipo de perfil não identificado: {path}")

    key = _install_cache_key(install, kind)
    with _CACHE_LOCK:
        cached_entry = _PROFILE_CACHE.get(key)
    if cached_entry is not None and path in cached_entry.chains_by_path:
        chain = cached_entry.chains_by_path[path]
        if all(_file_sig(dep) == cached_entry.file_sigs.get(dep) for dep in chain):
            return _copy_resolved(cached_entry.resolved_by_path[path])

    entry = _get_kind_entry(install, kind)
    if path in entry.resolved_by_path:
        return _copy_resolved(entry.resolved_by_path[path])

    item = _read_profile(path, kind)
    if item is None:
        raise ProfileError(f"Perfil inválido: {path}")
    return _resolve(item, entry.candidates, set())
