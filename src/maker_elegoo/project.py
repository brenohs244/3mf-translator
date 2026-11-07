"""Leitura segura de metadados de projetos 3MF Bambu/Orca."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class ProjectError(ValueError):
    """Arquivo 3MF ausente, inválido ou incompatível."""


@dataclass(frozen=True)
class FilamentInfo:
    slot: int
    material: str
    color: str
    profile: str


@dataclass(frozen=True)
class PlateInfo:
    number: int
    instance_count: int


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    source_settings: dict
    filaments: tuple[FilamentInfo, ...]
    plates: tuple[PlateInfo, ...]
    objects: tuple[str, ...]
    archive_entries: tuple[str, ...]
    warnings: tuple[str, ...]


def _read_small(archive: ZipFile, name: str, limit: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ProjectError(f"Metadado grande demais: {name}")
    return archive.read(info)


def _list_value(settings: dict, key: str) -> list[str]:
    value = settings.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def inspect_project(path: Path, *, max_uncompressed_bytes: int = 2_000_000_000) -> ProjectInfo:
    path = Path(path)
    if not path.is_file():
        raise ProjectError(f"Arquivo não encontrado: {path}")
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            seen: set[str] = set()
            total = 0
            for info in infos:
                name = info.filename.replace("\\", "/")
                parts = name.split("/")
                if (name.startswith("/") or re.match(r"^[A-Za-z]:", name)
                        or ".." in parts or "" in parts[:-1]):
                    raise ProjectError(f"Caminho inseguro dentro do 3MF: {info.filename}")
                folded = name.casefold()
                if folded in seen:
                    raise ProjectError(f"Entrada duplicada dentro do 3MF: {info.filename}")
                seen.add(folded)
                total += info.file_size
                if total > max_uncompressed_bytes:
                    raise ProjectError("3MF excede o limite de tamanho descompactado")
            names = tuple(info.filename for info in infos)
            if "3D/3dmodel.model" not in names:
                raise ProjectError("3MF sem geometria principal")
            if "Metadata/project_settings.config" not in names:
                raise ProjectError("3MF sem configurações de projeto")
            raw = _read_small(archive, "Metadata/project_settings.config", 16_000_000)
            settings = json.loads(raw)
            if not isinstance(settings, dict):
                raise ProjectError("Configurações de projeto inválidas")

            materials = _list_value(settings, "filament_type")
            colors = _list_value(settings, "filament_colour") or _list_value(settings, "filament_color")
            profiles = _list_value(settings, "filament_settings_id")
            count = max(len(materials), len(colors), len(profiles), 1)
            filaments = tuple(
                FilamentInfo(i + 1,
                             materials[i] if i < len(materials) else "Desconhecido",
                             colors[i] if i < len(colors) else "#808080",
                             profiles[i] if i < len(profiles) else "")
                for i in range(count)
            )

            object_names: list[str] = []
            plates: list[PlateInfo] = []
            warnings: list[str] = []
            model_settings = "Metadata/model_settings.config"
            if model_settings in names:
                xml = _read_small(archive, model_settings, 64_000_000)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise ProjectError("XML com declaração de entidade não é aceito")
                root = ElementTree.fromstring(xml)
                for obj in root.findall("object"):
                    names_for_object = [m.get("value", "") for m in obj.findall("metadata")
                                        if m.get("key") == "name"]
                    object_names.append(names_for_object[0] if names_for_object else f"Objeto {obj.get('id', '?')}")
                for index, plate in enumerate(root.findall("plate"), 1):
                    plates.append(PlateInfo(index, len(plate.findall("model_instance"))))
            else:
                warnings.append("Metadados de objetos e placas ausentes")
            if not plates:
                plate_numbers = sorted({int(m.group(1)) for name in names
                                        if (m := re.fullmatch(r"Metadata/plate_(\d+)\.json", name))})
                plates = [PlateInfo(i, 0) for i in plate_numbers] or [PlateInfo(1, 0)]
            return ProjectInfo(path, settings, filaments, tuple(plates), tuple(object_names), names, tuple(warnings))
    except (BadZipFile, OSError, json.JSONDecodeError, ElementTree.ParseError, KeyError) as exc:
        raise ProjectError(f"Não foi possível ler o 3MF: {exc}") from exc
