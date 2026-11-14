"""Renderização local offline (PPM) da 1ª camada e projeção de overhangs em 3MF/G-code."""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .gcode_audit import PlateGcodeAudit
from .geometry_check import _ParsedModel, _parse_model_stream
from .orientation import IDENTITY, apply_transform, compose_transform

_BG_COLOR = (0x1E, 0x24, 0x2B)
_GRID_COLOR = (0x2B, 0x34, 0x3E)
_BORDER_COLOR = (0x44, 0x52, 0x61)
_OVERHANG_COLOR = (0xE6, 0x8A, 0x1E)
_CONTACT_COLOR = (0x2A, 0xB7, 0xA9)
_GCODE_COLOR = (0x7D, 0xF9, 0xFF)


@dataclass(frozen=True)
class LayerPreview:
    """Imagem PPM (P6) carregável em tk.PhotoImage com métricas da 1ª camada."""

    ppm_bytes: bytes
    width: int
    height: int
    bed_width_mm: float
    bed_depth_mm: float
    contact_area_mm2: float
    overhang_area_mm2: float
    neck_z_mm: float | None
    gcode_segments_drawn: int
    legend: str


def _fill_triangle_2d(
    buf: bytearray,
    width: int,
    height: int,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    color: tuple[int, int, int],
) -> None:
    x0 = max(0, int(math.floor(min(ax, bx, cx))))
    x1 = min(width - 1, int(math.ceil(max(ax, bx, cx))))
    y0 = max(0, int(math.floor(min(ay, by, cy))))
    y1 = min(height - 1, int(math.ceil(max(ay, by, cy))))
    if x1 < x0 or y1 < y0:
        return

    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denom) < 1e-8:
        # Triângulo degenerado/vertical projetado: marca a linha simples de contorno
        for px, py in ((int(round(ax)), int(round(ay))), (int(round(bx)), int(round(by))), (int(round(cx)), int(round(cy)))):
            if 0 <= px < width and 0 <= py < height:
                idx = (py * width + px) * 3
                buf[idx], buf[idx + 1], buf[idx + 2] = color
        return

    r, g, b = color
    for py in range(y0, y1 + 1):
        py_c = py + 0.5
        row_off = py * width * 3
        for px in range(x0, x1 + 1):
            px_c = px + 0.5
            w1 = ((by - cy) * (px_c - cx) + (cx - bx) * (py_c - cy)) / denom
            w2 = ((cy - ay) * (px_c - cx) + (ax - cx) * (py_c - cy)) / denom
            w3 = 1.0 - w1 - w2
            if w1 >= -0.02 and w2 >= -0.02 and w3 >= -0.02:
                idx = row_off + px * 3
                buf[idx], buf[idx + 1], buf[idx + 2] = r, g, b


def _draw_line(
    buf: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    r, g, b = color
    while True:
        if 0 <= x0 < width and 0 <= y0 < height:
            idx = (y0 * width + x0) * 3
            buf[idx], buf[idx + 1], buf[idx + 2] = r, g, b
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def _collect_mesh_batches(project_path: Path) -> list[tuple[array, array]]:
    batches: list[tuple[array, array]] = []
    with ZipFile(project_path) as archive:
        names = {n.replace("\\", "/"): n for n in archive.namelist()}
        main_key = "3D/3dmodel.model"
        if main_key not in names:
            return batches
        parsed: dict[str, _ParsedModel] = {
            main_key: _parse_model_stream(archive, names[main_key], include_items=True)
        }
        if parsed[main_key].unit != "millimeter":
            return batches

        def get_model(key: str) -> _ParsedModel | None:
            if key in parsed:
                return parsed[key]
            actual = names.get(key)
            if not actual:
                return None
            model = _parse_model_stream(archive, actual, include_items=False)
            parsed[key] = model
            return model

        root = parsed[main_key]
        items = root.items or [(oid, IDENTITY) for oid in root.meshes]
        for root_oid, item_mat in items:
            stack = [(main_key, root_oid, item_mat, frozenset({(main_key, root_oid)}))]
            while stack:
                m_key, oid, w_mat, trail = stack.pop()
                m_data = get_model(m_key)
                if m_data is None:
                    continue
                for verts, tris in m_data.meshes.get(oid, ()):
                    if not verts or not tris:
                        continue
                    world = array("f")
                    for off in range(0, len(verts), 3):
                        world.extend(apply_transform(w_mat, (verts[off], verts[off + 1], verts[off + 2])))
                    batches.append((world, tris))
                for comp_path, comp_oid, comp_mat in m_data.components.get(oid, ()):
                    nxt_key = comp_path or m_key
                    node = (nxt_key, comp_oid)
                    if node in trail or len(trail) > 64:
                        continue
                    stack.append((nxt_key, comp_oid, compose_transform(w_mat, comp_mat), trail | {node}))
    return batches


def render_layer1_and_overhang_preview(
    project_path: Path,
    *,
    gcode_audit: PlateGcodeAudit | None = None,
    bed_width_mm: float = 256.0,
    bed_depth_mm: float = 256.0,
    size_px: int = 320,
    neck_z_mm: float | None = None,
) -> LayerPreview:
    """Gera prévia visual top-down (PPM) da base na mesa, overhangs >45° e percursos da 1ª camada."""
    width = height = max(64, int(size_px))
    buf = bytearray(_BG_COLOR * (width * height))

    def to_px(x_mm: float, y_mm: float) -> tuple[float, float]:
        px = (x_mm / max(1.0, bed_width_mm)) * (width - 1)
        py = (1.0 - y_mm / max(1.0, bed_depth_mm)) * (height - 1)
        return px, py

    # Grade de 32 mm + borda da mesa Centauri Carbon 2
    grid_step = 32.0
    g_val = grid_step
    while g_val < bed_width_mm:
        gx, _ = to_px(g_val, 0.0)
        _draw_line(buf, width, height, int(round(gx)), 0, int(round(gx)), height - 1, _GRID_COLOR)
        g_val += grid_step
    g_val = grid_step
    while g_val < bed_depth_mm:
        _, gy = to_px(0.0, g_val)
        _draw_line(buf, width, height, 0, int(round(gy)), width - 1, int(round(gy)), _GRID_COLOR)
        g_val += grid_step
    _draw_line(buf, width, height, 0, 0, width - 1, 0, _BORDER_COLOR)
    _draw_line(buf, width, height, width - 1, 0, width - 1, height - 1, _BORDER_COLOR)
    _draw_line(buf, width, height, width - 1, height - 1, 0, height - 1, _BORDER_COLOR)
    _draw_line(buf, width, height, 0, height - 1, 0, 0, _BORDER_COLOR)

    batches = _collect_mesh_batches(Path(project_path))
    global_minz = math.inf
    for world, _ in batches:
        for off in range(2, len(world), 3):
            if world[off] < global_minz:
                global_minz = world[off]
    if not math.isfinite(global_minz):
        global_minz = 0.0

    contact_area = 0.0
    overhang_area = 0.0
    overhang_tris: list[tuple[float, float, float, float, float, float]] = []
    contact_tris: list[tuple[float, float, float, float, float, float]] = []

    for world, tris in batches:
        tri_count = len(tris) // 3
        step = max(1, tri_count // 120_000)
        for t in range(0, tri_count, step):
            base = t * 3
            ia, ib, ic = tris[base] * 3, tris[base + 1] * 3, tris[base + 2] * 3
            ax, ay, az = world[ia], world[ia + 1], world[ia + 2]
            bx, by, bz = world[ib], world[ib + 1], world[ib + 2]
            cx, cy, cz = world[ic], world[ic + 1], world[ic + 2]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            norm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm <= 1e-12:
                continue
            area = norm * step / 2.0
            on_bed = max(abs(az - global_minz), abs(bz - global_minz), abs(cz - global_minz)) <= 0.5
            if on_bed:
                contact_area += area * abs(nz) / norm
                pax, pay = to_px(ax, ay)
                pbx, pby = to_px(bx, by)
                pcx, pcy = to_px(cx, cy)
                contact_tris.append((pax, pay, pbx, pby, pcx, pcy))
            elif nz < -0.70710678 * norm:
                overhang_area += area
                pax, pay = to_px(ax, ay)
                pbx, pby = to_px(bx, by)
                pcx, pcy = to_px(cx, cy)
                overhang_tris.append((pax, pay, pbx, pby, pcx, pcy))

    for tri in overhang_tris:
        _fill_triangle_2d(buf, width, height, *tri, _OVERHANG_COLOR)
    for tri in contact_tris:
        _fill_triangle_2d(buf, width, height, *tri, _CONTACT_COLOR)

    segments_drawn = 0
    if gcode_audit and gcode_audit.layer1_segments:
        for sx0, sy0, sx1, sy1 in gcode_audit.layer1_segments:
            px0, py0 = to_px(sx0, sy0)
            px1, py1 = to_px(sx1, sy1)
            _draw_line(
                buf, width, height,
                int(round(px0)), int(round(py0)),
                int(round(px1)), int(round(py1)),
                _GCODE_COLOR,
            )
            segments_drawn += 1

    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    legend = (
        "Verde-azulado = base na mesa · Laranja = saliências >45°"
        + (" · Ciano = percurso G-code da 1ª camada" if segments_drawn else "")
    )
    return LayerPreview(
        ppm_bytes=header + bytes(buf),
        width=width,
        height=height,
        bed_width_mm=bed_width_mm,
        bed_depth_mm=bed_depth_mm,
        contact_area_mm2=round(contact_area, 1),
        overhang_area_mm2=round(overhang_area, 1),
        neck_z_mm=neck_z_mm,
        gcode_segments_drawn=segments_drawn,
        legend=legend,
    )
