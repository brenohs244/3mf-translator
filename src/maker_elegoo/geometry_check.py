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
class NeckFinding:
    z_mm: float
    width_mm: float
    depth_mm: float
    cross_area_mm2: float
    peak_below_area_mm2: float
    peak_above_area_mm2: float
    ratio_to_peak: float
    part_name: str = ""


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
    neck_findings: tuple[NeckFinding, ...] = ()


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
    min_cross_section_ratio: float = 1.0
    has_thin_neck: bool = False
    neck_findings: tuple[NeckFinding, ...] = ()


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


def _slice_area_and_spans(segments: list[tuple[float, float, float, float]]) -> tuple[float, float, float]:
    if not segments:
        return 0.0, 0.0, 0.0
    s_minx = min(min(seg[0], seg[2]) for seg in segments)
    s_maxx = max(max(seg[0], seg[2]) for seg in segments)
    s_miny = min(min(seg[1], seg[3]) for seg in segments)
    s_maxy = max(max(seg[1], seg[3]) for seg in segments)
    sx = max(0.0, s_maxx - s_minx)
    sy = max(0.0, s_maxy - s_miny)
    if sx <= 1e-4 or sy <= 1e-4:
        return 0.0, sx, sy

    bands = 16
    dy = sy / bands
    area = 0.0
    for band in range(bands):
        y_scan = s_miny + sy * (band + 0.5) / bands
        xs: list[float] = []
        for x0, y0, x1, y1 in segments:
            if (y0 <= y_scan < y1) or (y1 <= y_scan < y0):
                t = (y_scan - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        if len(xs) >= 2:
            xs.sort()
            for idx in range(0, len(xs) - 1, 2):
                area += max(0.0, xs[idx + 1] - xs[idx]) * dy
    return area, sx, sy


def _detect_z_necks(
    verts: array,
    tris: array,
    w_mat: tuple[float, ...],
    bounds: tuple[float, float, float, float, float, float],
    part_name: str,
) -> tuple[float, tuple[NeckFinding, ...]]:
    minz, maxz = bounds[4], bounds[5]
    sz = maxz - minz
    tri_count = len(tris) // 3
    if sz < 10.0 or tri_count < 4:
        return 1.0, ()

    if tri_count > 180_000:
        # Malhas extremamente densas (>180k triângulos) usam amostragem de largura espacial sem raycast completo.
        step = max(1, tri_count // 90_000)
        return 1.0, () if step > 1 else ()

    world = array("f")
    for offset in range(0, len(verts), 3):
        world.extend(apply_transform(w_mat, (verts[offset], verts[offset + 1], verts[offset + 2])))

    slices = 20
    z_start = minz + sz * 0.06
    z_end = minz + sz * 0.94
    z_span = z_end - z_start
    if z_span <= 1e-4:
        return 1.0, ()
    z_levels = [z_start + z_span * idx / (slices - 1) for idx in range(slices)]
    buckets: list[list[tuple[float, float, float, float]]] = [[] for _ in range(slices)]

    for t in range(tri_count):
        base = t * 3
        ia, ib, ic = tris[base] * 3, tris[base + 1] * 3, tris[base + 2] * 3
        az = world[ia + 2]
        bz = world[ib + 2]
        cz = world[ic + 2]
        t_minz = min(az, bz, cz)
        t_maxz = max(az, bz, cz)
        if t_maxz < z_start or t_minz > z_end or t_maxz - t_minz <= 1e-6:
            continue
        i_lo = max(0, int(math.floor((t_minz - z_start) * (slices - 1) / z_span)))
        i_hi = min(slices - 1, int(math.ceil((t_maxz - z_start) * (slices - 1) / z_span)))
        pts = (
            (world[ia], world[ia + 1], az),
            (world[ib], world[ib + 1], bz),
            (world[ic], world[ic + 1], cz),
        )
        edges = ((pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[0]))
        for s_idx in range(i_lo, i_hi + 1):
            zp = z_levels[s_idx]
            hits: list[tuple[float, float]] = []
            for p0, p1 in edges:
                dz = p1[2] - p0[2]
                if (p0[2] <= zp < p1[2]) or (p1[2] <= zp < p0[2]):
                    frac = (zp - p0[2]) / dz
                    hits.append((p0[0] + frac * (p1[0] - p0[0]), p0[1] + frac * (p1[1] - p0[1])))
            if len(hits) == 2:
                buckets[s_idx].append((hits[0][0], hits[0][1], hits[1][0], hits[1][1]))

    stats = []
    for s_idx, segs in enumerate(buckets):
        area, sx, sy = _slice_area_and_spans(segs)
        if area > 1e-4:
            stats.append((z_levels[s_idx], area, sx, sy))
    if len(stats) < 3:
        return 1.0, ()

    areas = [item[1] for item in stats]
    best_finding: NeckFinding | None = None
    min_ratio = 1.0
    for idx, (z_mm, area_mm2, sx, sy) in enumerate(stats):
        below = max(areas[:idx], default=0.0)
        above = max(areas[idx + 1:], default=0.0)
        if below <= 1e-4:
            continue
        if above > 1e-4:
            ref_peak = min(below, above)
            ratio = area_mm2 / ref_peak
            min_ratio = min(min_ratio, ratio)
            if ratio <= 0.35 and (best_finding is None or ratio < best_finding.ratio_to_peak):
                best_finding = NeckFinding(
                    z_mm=round(z_mm, 1),
                    width_mm=round(sx, 2),
                    depth_mm=round(sy, 2),
                    cross_area_mm2=round(area_mm2, 1),
                    peak_below_area_mm2=round(below, 1),
                    peak_above_area_mm2=round(above, 1),
                    ratio_to_peak=round(ratio, 3),
                    part_name=part_name,
                )
        elif sz >= 20.0 and min(sx, sy) <= 4.5:
            ratio = area_mm2 / below
            min_ratio = min(min_ratio, ratio)
            if ratio <= 0.25 and (best_finding is None or ratio < best_finding.ratio_to_peak):
                best_finding = NeckFinding(
                    z_mm=round(z_mm, 1),
                    width_mm=round(sx, 2),
                    depth_mm=round(sy, 2),
                    cross_area_mm2=round(area_mm2, 1),
                    peak_below_area_mm2=round(below, 1),
                    peak_above_area_mm2=round(above, 1),
                    ratio_to_peak=round(ratio, 3),
                    part_name=part_name,
                )

    return round(min(1.0, min_ratio), 3), ((best_finding,) if best_finding is not None else ())


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
            item_min_ratio = 1.0
            item_necks: list[NeckFinding] = []
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
                    part_ratio, part_necks = _detect_z_necks(verts, tris, w_mat, bnds, f"Objeto {item_idx}")
                    item_min_ratio = min(item_min_ratio, part_ratio)
                    item_necks.extend(part_necks)
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
                    neck_findings=tuple(item_necks[:1]),
                ))

        if not parts:
            return GeometrySummary(0, 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 0.0, 0.0, 0.0, 0.0, False)

        all_necks = tuple(neck for p in parts for neck in p.neck_findings)
        min_ratio = min((n.ratio_to_peak for n in all_necks), default=1.0)
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
            min_cross_section_ratio=min_ratio,
            has_thin_neck=bool(all_necks),
            neck_findings=all_necks,
        )
