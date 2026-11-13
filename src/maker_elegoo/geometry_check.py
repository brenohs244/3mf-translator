"""Pré-análise geométrica em streaming para projetos 3MF (multi-objeto e >3M triângulos)."""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat
from zipfile import ZipFile

from .orientation import IDENTITY, apply_transform, compose_transform, parse_transform


@dataclass(frozen=True)
class ObjectGeometry:
    name: str
    triangle_count: int
    bounds: tuple[float, float, float, float, float, float]
    size_x: float
    size_y: float
    size_z: float
    contact_mm2: float
    overhang_mm2: float
    slender: bool


@dataclass(frozen=True)
class GeometrySummary:
    triangle_count: int
    object_count: int
    bounds: tuple[float, float, float, float, float, float]
    size_x: float
    size_y: float
    size_z: float
    contact_mm2: float
    overhang_mm2: float
    has_slender_parts: bool
    parts: tuple[ObjectGeometry, ...] = ()


@dataclass
class _ParsedModel:
    unit: str
    meshes: dict[str, list[tuple[array, array]]]
    components: dict[str, list[tuple[str | None, str, tuple[float, ...]]]]
    items: list[tuple[str, tuple[float, ...]]]


def _parse_model_stream(archive: ZipFile, member_name: str, *, include_items: bool) -> _ParsedModel:
    meshes: dict[str, list[tuple[array, array]]] = {}
    components: dict[str, list[tuple[str | None, str, tuple[float, ...]]]] = {}
    items: list[tuple[str, tuple[float, ...]]] = []
    unit = "millimeter"
    current_obj: str | None = None
    in_mesh = False
    verts = array("f")
    tris = array("I")

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal unit, current_obj, in_mesh, verts, tris
        tag = name.rsplit("}", 1)[-1]
        if tag == "model":
            unit = (attrs.get("unit") or "millimeter").lower()
        elif tag == "object":
            current_obj = attrs.get("id")
        elif tag == "mesh" and current_obj is not None:
            in_mesh = True
            verts = array("f")
            tris = array("I")
        elif tag == "vertex" and in_mesh:
            try:
                verts.extend((float(attrs["x"]), float(attrs["y"]), float(attrs["z"])))
            except (KeyError, ValueError):
                pass
        elif tag == "triangle" and in_mesh:
            try:
                v1, v2, v3 = int(attrs["v1"]), int(attrs["v2"]), int(attrs["v3"])
                if v1 >= 0 and v2 >= 0 and v3 >= 0:
                    tris.extend((v1, v2, v3))
            except (KeyError, ValueError):
                pass
        elif tag == "component" and current_obj is not None:
            comp_id = attrs.get("objectid", "")
            comp_path = None
            for attr_key, attr_val in attrs.items():
                if attr_key.rsplit("}", 1)[-1] == "path" and attr_val:
                    comp_path = attr_val.lstrip("/").replace("\\", "/")
                    break
            try:
                mat = parse_transform(attrs.get("transform"))
            except Exception:
                mat = IDENTITY
            components.setdefault(current_obj, []).append((comp_path, comp_id, mat))
        elif tag == "item" and include_items:
            oid = attrs.get("objectid", "")
            try:
                mat = parse_transform(attrs.get("transform"))
            except Exception:
                mat = IDENTITY
            if oid:
                items.append((oid, mat))

    def end(name: str) -> None:
        nonlocal current_obj, in_mesh, verts, tris
        tag = name.rsplit("}", 1)[-1]
        if tag == "mesh" and in_mesh and current_obj is not None:
            if verts or tris:
                meshes.setdefault(current_obj, []).append((verts, tris))
            verts = array("f")
            tris = array("I")
            in_mesh = False
        elif tag == "object":
            current_obj = None

    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = lambda *_: (_ for _ in ()).throw(ValueError("DTD não aceito"))
    with archive.open(member_name) as stream:
        while chunk := stream.read(1024 * 1024):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    return _ParsedModel(unit=unit, meshes=meshes, components=components, items=items)


def _is_slender(sx: float, sy: float, sz: float, contact_mm2: float) -> bool:
    footprint = min(sx, sy)
    if sz >= 15.0 and footprint > 0 and (sz / footprint) >= 3.0 and contact_mm2 < 250.0:
        return True
    if 0.0 < contact_mm2 < 60.0 and min(sx, sy, sz) < 12.0:
        return True
    return False


def _evaluate_mesh(
    verts: array,
    tris: array,
    world_matrix: tuple[float, ...],
) -> tuple[int, tuple[float, float, float, float, float, float], float, float]:
    vert_count = len(verts) // 3
    tri_count = len(tris) // 3
    if vert_count == 0 or tri_count == 0:
        return 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 0.0

    world = array("f")
    minx = miny = minz = math.inf
    maxx = maxy = maxz = -math.inf
    m0, m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11 = world_matrix
    for i in range(0, len(verts), 3):
        x, y, z = verts[i], verts[i + 1], verts[i + 2]
        wx = m0 * x + m3 * y + m6 * z + m9
        wy = m1 * x + m4 * y + m7 * z + m10
        wz = m2 * x + m5 * y + m8 * z + m11
        world.extend((wx, wy, wz))
        if wx < minx: minx = wx
        if wx > maxx: maxx = wx
        if wy < miny: miny = wy
        if wy > maxy: maxy = wy
        if wz < minz: minz = wz
        if wz > maxz: maxz = wz

    contact = 0.0
    overhang = 0.0
    step = max(1, tri_count // 120_000)
    max_vert_idx = vert_count - 1
    for t in range(0, tri_count, step):
        base = t * 3
        i0, i1, i2 = tris[base], tris[base + 1], tris[base + 2]
        if i0 > max_vert_idx or i1 > max_vert_idx or i2 > max_vert_idx:
            continue
        o0, o1, o2 = i0 * 3, i1 * 3, i2 * 3
        ax, ay, az = world[o0], world[o0 + 1], world[o0 + 2]
        bx, by, bz = world[o1], world[o1 + 1], world[o1 + 2]
        cx, cy, cz = world[o2], world[o2 + 1], world[o2 + 2]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm <= 1e-12:
            continue
        area = 0.5 * norm * step
        on_bed = max(abs(az - minz), abs(bz - minz), abs(cz - minz)) <= 0.5
        if on_bed:
            contact += area * abs(nz) / norm
        elif nz < -0.70710678 * norm:
            overhang += area

    return tri_count, (minx, maxx, miny, maxy, minz, maxz), contact, overhang


def analyze_project_geometry(path: Path) -> GeometrySummary:
    """Analisa dimensões, apoio, overhangs (>45°) e partes esguias em todos os .model do 3MF."""
    path = Path(path)
    with ZipFile(path) as archive:
        names = {n.replace("\\", "/"): n for n in archive.namelist()}
        main_key = "3D/3dmodel.model"
        if main_key not in names:
            raise ValueError("3MF sem 3D/3dmodel.model")
        parsed_cache: dict[str, _ParsedModel] = {
            main_key: _parse_model_stream(archive, names[main_key], include_items=True)
        }
        if parsed_cache[main_key].unit != "millimeter":
            return GeometrySummary(0, 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 0.0, 0.0, 0.0, 0.0, False)

        def get_model(model_key: str) -> _ParsedModel | None:
            if model_key in parsed_cache:
                return parsed_cache[model_key]
            actual = names.get(model_key)
            if not actual:
                return None
            parsed = _parse_model_stream(archive, actual, include_items=False)
            parsed_cache[model_key] = parsed
            return parsed

        root_model = parsed_cache[main_key]
        parts: list[ObjectGeometry] = []
        items = root_model.items or [(oid, IDENTITY) for oid in root_model.meshes]

        for item_idx, (root_oid, item_mat) in enumerate(items, 1):
            stack: list[tuple[str, str, tuple[float, ...], frozenset[tuple[str, str]]]] = [
                (main_key, root_oid, item_mat, frozenset({(main_key, root_oid)}))
            ]
            item_tris = 0
            item_contact = 0.0
            item_overhang = 0.0
            minx = miny = minz = math.inf
            maxx = maxy = maxz = -math.inf

            while stack:
                m_key, oid, w_mat, trail = stack.pop()
                m_data = get_model(m_key)
                if m_data is None:
                    continue
                for verts, tris in m_data.meshes.get(oid, ()):
                    t_count, bnds, c_area, o_area = _evaluate_mesh(verts, tris, w_mat)
                    if t_count == 0:
                        continue
                    item_tris += t_count
                    item_contact += c_area
                    item_overhang += o_area
                    minx, maxx = min(minx, bnds[0]), max(maxx, bnds[1])
                    miny, maxy = min(miny, bnds[2]), max(maxy, bnds[3])
                    minz, maxz = min(minz, bnds[4]), max(maxz, bnds[5])
                for comp_path, comp_oid, comp_mat in m_data.components.get(oid, ()):
                    next_model = comp_path or m_key
                    node = (next_model, comp_oid)
                    if node in trail or len(trail) > 64:
                        continue
                    stack.append((next_model, comp_oid, compose_transform(w_mat, comp_mat), trail | {node}))

            if item_tris > 0:
                sx, sy, sz = maxx - minx, maxy - miny, maxz - minz
                parts.append(ObjectGeometry(
                    name=f"Objeto {item_idx}",
                    triangle_count=item_tris,
                    bounds=(minx, maxx, miny, maxy, minz, maxz),
                    size_x=sx, size_y=sy, size_z=sz,
                    contact_mm2=item_contact,
                    overhang_mm2=item_overhang,
                    slender=_is_slender(sx, sy, sz, item_contact),
                ))

        if not parts:
            return GeometrySummary(0, 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 0.0, 0.0, 0.0, 0.0, False)

        gx0 = min(p.bounds[0] for p in parts)
        gx1 = max(p.bounds[1] for p in parts)
        gy0 = min(p.bounds[2] for p in parts)
        gy1 = max(p.bounds[3] for p in parts)
        gz0 = min(p.bounds[4] for p in parts)
        gz1 = max(p.bounds[5] for p in parts)
        return GeometrySummary(
            triangle_count=sum(p.triangle_count for p in parts),
            object_count=len(parts),
            bounds=(gx0, gx1, gy0, gy1, gz0, gz1),
            size_x=gx1 - gx0,
            size_y=gy1 - gy0,
            size_z=gz1 - gz0,
            contact_mm2=sum(p.contact_mm2 for p in parts),
            overhang_mm2=sum(p.overhang_mm2 for p in parts),
            has_slender_parts=any(p.slender for p in parts),
            parts=tuple(parts),
        )
