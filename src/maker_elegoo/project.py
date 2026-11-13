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
class ObjectOverride:
    object_id: str
    name: str
    settings: dict[str, str]


@dataclass(frozen=True)
class PlateInfo:
    number: int
    instance_count: int
    object_ids: tuple[str, ...] = ()
    filament_slots: tuple[str, ...] = ()
    used_filament_slots: tuple[str, ...] = ()
    has_paint_color: bool = False
    has_paint_supports: bool = False


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    source_settings: dict
    filaments: tuple[FilamentInfo, ...]
    plates: tuple[PlateInfo, ...]
    objects: tuple[str, ...]
    archive_entries: tuple[str, ...]
    warnings: tuple[str, ...]
    advanced_features: tuple[str, ...] = ()
    used_filament_slots: tuple[str, ...] = ()
    object_overrides: tuple[ObjectOverride, ...] = ()
    geometry_summary: object | None = None


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


def _decode_paint_node(token: str, pos: int, out: set[str]) -> int:
    if pos < 0:
        return -1
    val = int(token[pos], 16)
    pos -= 1
    sides = val & 3
    if sides == 0:
        state = val >> 2
        if state == 3 and pos >= 0:
            state = 3 + int(token[pos], 16)
            pos -= 1
        if state > 0:
            out.add(str(state))
        return pos
    for _ in range(sides + 1):
        pos = _decode_paint_node(token, pos, out)
    return pos


def _decode_paint_color_slots(token: str, max_slot: int) -> set[str]:
    slots: set[str] = set()
    clean = token.strip()
    if not clean:
        return slots
    try:
        pos = len(clean) - 1
        while pos >= 0:
            pos = _decode_paint_node(clean, pos, slots)
    except ValueError:
        return set()
    return {s for s in slots if s.isdigit() and 1 <= int(s) <= max(max_slot, 16)}


def _model_path_object_map(archive: ZipFile, names: tuple[str, ...]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    if "3D/3dmodel.model" not in names:
        return mapping
    current_obj: str | None = None
    with archive.open("3D/3dmodel.model") as stream:
        try:
            for event, element in ElementTree.iterparse(stream, events=("start", "end")):
                tag = element.tag.rsplit("}", 1)[-1]
                if event == "start":
                    if tag == "object":
                        current_obj = element.get("id")
                    elif tag == "component" and current_obj:
                        for attr_key, attr_val in element.attrib.items():
                            if attr_key.rsplit("}", 1)[-1] == "path" and attr_val:
                                norm = attr_val.lstrip("/").replace("\\", "/")
                                mapping.setdefault(norm, set()).add(current_obj)
                else:
                    if tag == "object":
                        current_obj = None
                    element.clear()
        except ElementTree.ParseError:
            pass
    return mapping


def _scan_models_paint_and_supports(
    archive: ZipFile,
    names: tuple[str, ...],
    filament_count: int,
) -> tuple[bool, bool, dict[str, set[str]], bool]:
    path_to_objs = _model_path_object_map(archive, names)
    paint_slots_by_obj: dict[str, set[str]] = {}
    has_paint_color = False
    has_paint_supports = False
    decoded_cache: dict[str, set[str]] = {}
    obj_re = re.compile(rb'<object\b[^>]*\bid="([^"]+)"')
    paint_re = re.compile(rb'paint_color="([^"]+)"')
    for name in names:
        normalized = name.replace("\\", "/")
        if not (normalized.startswith("3D/") and normalized.endswith(".model")):
            continue
        mapped_objs = path_to_objs.get(normalized, set())
        current_obj: str | None = next(iter(mapped_objs)) if len(mapped_objs) == 1 else None
        with archive.open(name) as stream:
            tail = b""
            while chunk := stream.read(2 * 1024 * 1024):
                data = tail + chunk
                if b"paint_supports=" in data:
                    has_paint_supports = True
                if not mapped_objs:
                    for match in obj_re.finditer(data):
                        current_obj = match.group(1).decode("utf-8", errors="ignore")
                if b"paint_color=" in data:
                    has_paint_color = True
                    target_objs = mapped_objs or ({current_obj} if current_obj else {"*"})
                    for match in paint_re.finditer(data):
                        token = match.group(1).decode("ascii", errors="ignore")
                        slots = decoded_cache.get(token)
                        if slots is None:
                            slots = _decode_paint_color_slots(token, filament_count)
                            decoded_cache[token] = slots
                        for oid in target_objs:
                            paint_slots_by_obj.setdefault(oid, set()).update(slots)
                tail = data[-128:]
    return has_paint_color, has_paint_supports, paint_slots_by_obj, bool(path_to_objs)


def _has_paint_color(archive: ZipFile, names: tuple[str, ...]) -> bool:
    for name in names:
        normalized = name.replace("\\", "/")
        if normalized.startswith("3D/") and normalized.endswith(".model"):
            with archive.open(name) as stream:
                tail = b""
                while chunk := stream.read(1024 * 1024):
                    data = tail + chunk
                    if b"paint_color=" in data:
                        return True
                    tail = data[-16:]
    return False


def _detect_advanced_features(
    archive: ZipFile,
    names: tuple[str, ...],
    model_root: ElementTree.Element | None,
    settings: dict | None = None,
    *,
    has_paint_color: bool | None = None,
    has_paint_supports: bool = False,
) -> tuple[str, ...]:
    features: list[str] = []
    normalized_names = {n.replace("\\", "/") for n in names}
    if "Metadata/layer_heights_profile.txt" in normalized_names:
        features.append("Altura de camada variável (curva por objeto)")
    if "Metadata/custom_gcode_per_layer.xml" in normalized_names:
        features.append("G-code personalizado por camada / pausas")
    has_modifier = False
    has_enforcer_or_blocker = False
    has_manual_model = False
    has_object_override = False
    if model_root is not None:
        for elem in model_root.iter():
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "part":
                subtype = (elem.get("subtype") or "").lower()
                if "modifier" in subtype or "negative" in subtype:
                    has_modifier = True
                if "support_enforcer" in subtype or "support_blocker" in subtype:
                    has_enforcer_or_blocker = True
            elif tag == "metadata":
                k = elem.get("key", "")
                v = (elem.get("value") or "").lower()
                if k == "support_type" and "manual" in v:
                    has_manual_model = True
                if k in {"layer_height", "enable_support", "support_type", "sparse_infill_density", "wall_loops"}:
                    has_object_override = True
    if has_modifier:
        features.append("Modificadores ou cortes por objeto")
    global_manual = bool(
        settings and str(settings.get("enable_support", "0")) == "1"
        and "manual" in str(settings.get("support_type", "")).lower()
    )
    if has_paint_supports:
        features.append("Pintura de suportes (paint_supports)")
    if global_manual and not (has_enforcer_or_blocker or has_paint_supports):
        features.append("Suporte manual no arquivo sem pintagem/enforcers explícitos")
    elif has_enforcer_or_blocker or has_manual_model:
        features.append("Suporte manual ou bloqueador por objeto")
    if has_object_override:
        features.append("Configurações específicas por objeto (model_settings)")
    if has_paint_color if has_paint_color is not None else _has_paint_color(archive, names):
        features.append("Pintura multicolorida (paint_color)")
    return tuple(features)


def inspect_project(
    path: Path,
    *,
    max_uncompressed_bytes: int = 2_000_000_000,
    include_geometry: bool = True,
) -> ProjectInfo:
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

            has_paint_color, has_paint_supports, paint_slots_by_obj, _ = _scan_models_paint_and_supports(
                archive, names, len(filaments),
            )
            object_names: list[str] = []
            object_overrides: list[ObjectOverride] = []
            plates: list[PlateInfo] = []
            warnings: list[str] = []
            root: ElementTree.Element | None = None
            model_settings = "Metadata/model_settings.config"
            all_used_slots: set[str] = set()
            if model_settings in names:
                xml = _read_small(archive, model_settings, 64_000_000)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise ProjectError("XML com declaração de entidade não é aceito")
                root = ElementTree.fromstring(xml)
                object_slots: dict[str, str] = {}
                object_all_slots: dict[str, set[str]] = {}
                for obj in root.findall("object"):
                    oid = obj.get("id", "")
                    obj_metas = {m.get("key", ""): m.get("value", "") for m in obj.findall("metadata") if m.get("key")}
                    obj_name = obj_metas.get("name") or f"Objeto {oid or '?'}"
                    object_names.append(obj_name)
                    ext = obj_metas.get("extruder", "")
                    object_slots[oid] = ext
                    used_for_obj: set[str] = set()
                    if ext and ext != "0":
                        used_for_obj.add(ext)
                    for part in obj.findall("part"):
                        for pm in part.findall("metadata"):
                            if pm.get("key") == "extruder":
                                p_ext = pm.get("value", "")
                                if p_ext and p_ext != "0":
                                    used_for_obj.add(p_ext)
                    if oid in paint_slots_by_obj:
                        used_for_obj.update(paint_slots_by_obj[oid])
                    if "*" in paint_slots_by_obj:
                        used_for_obj.update(paint_slots_by_obj["*"])
                    object_all_slots[oid] = used_for_obj
                    override_settings = {
                        k: v for k, v in obj_metas.items()
                        if k not in {"name", "extruder", "face_count", "thumbnail_file", "uuid"}
                    }
                    if override_settings:
                        object_overrides.append(ObjectOverride(oid, obj_name, override_settings))
                for index, plate in enumerate(root.findall("plate"), 1):
                    instances = plate.findall("model_instance")
                    ids = tuple(item.get("object_id") or next(
                        (meta.get("value", "") for meta in item.findall("metadata")
                         if meta.get("key") == "object_id"), "") for item in instances)
                    plate_used: set[str] = set()
                    for oid in ids:
                        plate_used.update(object_all_slots.get(oid, set()))
                    if not plate_used and ids:
                        plate_used.add("1")
                    all_used_slots.update(plate_used)
                    plate_used_sorted = tuple(sorted(plate_used, key=lambda s: int(s) if s.isdigit() else 999))
                    plate_painted = has_paint_color and any(
                        oid in paint_slots_by_obj or "*" in paint_slots_by_obj for oid in ids
                    )
                    plates.append(PlateInfo(
                        index,
                        len(instances),
                        ids,
                        tuple(object_slots.get(object_id, "") for object_id in ids),
                        plate_used_sorted,
                        plate_painted,
                        has_paint_supports,
                    ))
            else:
                warnings.append("Metadados de objetos e placas ausentes")
            if not all_used_slots:
                for slots in paint_slots_by_obj.values():
                    all_used_slots.update(slots)
            if not all_used_slots and plates:
                all_used_slots.add("1")
            if not plates:
                plate_numbers = sorted({int(m.group(1)) for name in names
                                        if (m := re.fullmatch(r"Metadata/plate_(\d+)\.json", name))})
                plates = [PlateInfo(i, 0, used_filament_slots=("1",)) for i in plate_numbers] or [
                    PlateInfo(1, 0, used_filament_slots=("1",))
                ]
            used_sorted = tuple(sorted(all_used_slots, key=lambda s: int(s) if s.isdigit() else 999))
            advanced_features = _detect_advanced_features(
                archive,
                names,
                root,
                settings,
                has_paint_color=has_paint_color,
                has_paint_supports=has_paint_supports,
            )
            geometry_summary = None
            if include_geometry:
                from .geometry_check import analyze_project_geometry
                try:
                    geom = analyze_project_geometry(path)
                    if geom.triangle_count > 0:
                        geometry_summary = geom
                except Exception:
                    geometry_summary = None
            return ProjectInfo(
                path, settings, filaments, tuple(plates), tuple(object_names),
                names, tuple(warnings), advanced_features,
                used_sorted, tuple(object_overrides), geometry_summary,
            )
    except (BadZipFile, OSError, json.JSONDecodeError, ElementTree.ParseError, KeyError) as exc:
        raise ProjectError(f"Não foi possível ler o 3MF: {exc}") from exc
