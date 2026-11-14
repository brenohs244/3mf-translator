"""Auditoria em streaming do G-code real gerado pelo ELEGOO Slicer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_LAYER1_SEGMENT_CAP = 4000
_SHORT_LAYER_THRESHOLD_S = 6.0
_SPEED_JUMP_THRESHOLD_MM_S = 120.0
_MIN_DWELL_SECONDS = 30
_TOKEN_RE = re.compile(r"([A-Z])([-+]?\d*\.?\d+)")


@dataclass(frozen=True)
class PlateGcodeAudit:
    """Métricas reais extraídas do G-code de uma placa antes da limpeza temporária."""

    plate: int
    layer_count: int
    first_layer_nozzle_temp: float | None
    nozzle_temps: tuple[float, ...]
    bed_temps: tuple[float, ...]
    part_fan_max_pct: int | None
    aux_fan_max_pct: int | None
    exhaust_fan_max_pct: int | None
    has_preheat_dwell: bool
    preheat_dwell_seconds: int
    max_volumetric_flow_mm3_s: float
    min_layer_time_s: float | None
    short_layers_under_6s: int
    max_print_speed_mm_s: float
    speed_jump_count: int
    layer1_bounds_mm: tuple[float, float, float, float] | None
    layer1_island_count: int
    layer1_segments: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class GcodeAuditSummary:
    """Resumo consolidado da auditoria real de G-code das placas fatiadas."""

    plates: tuple[PlateGcodeAudit, ...]
    findings: tuple[str, ...] = ()


def _parse_params(code_part: str) -> dict[str, float]:
    params: dict[str, float] = {}
    for letter, raw in _TOKEN_RE.findall(code_part.upper()):
        if letter in {"N", "M", "G"}:
            continue
        try:
            params[letter] = float(raw)
        except ValueError:
            pass
    return params


def _extract_cmd(code_part: str) -> str:
    stripped = code_part.strip().upper()
    if not stripped:
        return ""
    first = stripped.split(None, 1)[0]
    if first.startswith("N") and len(stripped.split()) > 1:
        first = stripped.split(None, 2)[1]
    return first


def _pwm_to_pct(pwm_value: float) -> int:
    if pwm_value <= 0:
        return 0
    return max(0, min(100, round(pwm_value * 100.0 / 255.0)))


def _update_fan_peak(current: int | None, pct: int) -> int:
    return pct if current is None else max(current, pct)


def _count_grid_islands(cells: set[tuple[int, int]]) -> int:
    """Agrupa células 2D ocupadas (1,5 mm) por conectividade 8-vizinhos para contar ilhas reais."""
    remaining = set(cells)
    islands = 0
    while remaining:
        islands += 1
        stack = [remaining.pop()]
        while stack:
            cx, cy = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nxt = (cx + dx, cy + dy)
                    if nxt in remaining:
                        remaining.remove(nxt)
                        stack.append(nxt)
    return islands


def audit_gcode_file(
    path: Path,
    *,
    plate: int = 1,
    filament_diameter_mm: float = 1.75,
) -> PlateGcodeAudit:
    """Lê um arquivo `.gcode` em streaming extraindo métricas reais de processo e 1ª camada."""
    diameter = filament_diameter_mm
    area = math.pi * (diameter / 2.0) ** 2

    nozzle_temps: list[float] = []
    bed_temps: list[float] = []
    first_layer_nozzle_temp: float | None = None
    part_fan_max: int | None = None
    aux_fan_max: int | None = None
    exhaust_fan_max: int | None = None
    preheat_dwell_seconds = 0

    saw_layer_markers = False
    in_custom_block = False
    layer_count = 0
    layer_times: dict[int, float] = {}
    layer_extruded: dict[int, bool] = {}

    abs_xyz = True
    abs_e = True
    x = 0.0
    y = 0.0
    z = 0.0
    e = 0.0
    feed_mm_s = 50.0
    prev_print_speed: float | None = None
    max_print_speed = 0.0
    max_volumetric = 0.0
    speed_jump_count = 0
    last_print_z = 0.0

    l1_min_x = math.inf
    l1_max_x = -math.inf
    l1_min_y = math.inf
    l1_max_y = -math.inf
    l1_has_bounds = False
    l1_cells: set[tuple[int, int]] = set()
    l1_segments: list[tuple[float, float, float, float]] = []

    with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith(";"):
                lower = stripped.lower()
                if lower.startswith("; filament_diameter:"):
                    try:
                        parsed_d = float(stripped.partition(":")[2].split(",")[0].strip())
                        if 1.0 <= parsed_d <= 3.5:
                            diameter = parsed_d
                            area = math.pi * (diameter / 2.0) ** 2
                    except ValueError:
                        pass
                elif lower.startswith(";type:"):
                    section = lower.partition(":")[2].strip()
                    in_custom_block = section == "custom"
                elif lower.startswith("; total layer number:") or lower.startswith(";layer_count:"):
                    saw_layer_markers = True
                elif lower.startswith(";layer_change") or lower.startswith("; layer "):
                    saw_layer_markers = True
                    in_custom_block = False
                    layer_count += 1
                    layer_times.setdefault(layer_count, 0.0)
                    layer_extruded.setdefault(layer_count, False)
                continue

            code_part = stripped.split(";", 1)[0].strip()
            if not code_part:
                continue
            cmd = _extract_cmd(code_part)
            if not cmd:
                continue

            if cmd == "G90":
                abs_xyz = True
                continue
            if cmd == "G91":
                abs_xyz = False
                continue
            if cmd == "M82":
                abs_e = True
                continue
            if cmd == "M83":
                abs_e = False
                continue

            params = _parse_params(code_part)
            if cmd == "G92":
                if "E" in params:
                    e = params["E"]
                if "X" in params:
                    x = params["X"]
                if "Y" in params:
                    y = params["Y"]
                if "Z" in params:
                    z = params["Z"]
                continue

            if cmd in {"M104", "M109"}:
                temp = params.get("S")
                if temp is not None and temp > 0:
                    if temp not in nozzle_temps:
                        nozzle_temps.append(temp)
                    if layer_count <= 1 and first_layer_nozzle_temp is None:
                        first_layer_nozzle_temp = temp
                continue

            if cmd in {"M140", "M190"}:
                temp = params.get("S")
                if temp is not None and temp > 0 and temp not in bed_temps:
                    bed_temps.append(temp)
                continue

            if cmd == "M106":
                if not in_custom_block:
                    fan_idx = int(round(params.get("P", 0.0)))
                    pct = _pwm_to_pct(params.get("S", 255.0))
                    if fan_idx == 0:
                        part_fan_max = _update_fan_peak(part_fan_max, pct)
                    elif fan_idx == 2:
                        aux_fan_max = _update_fan_peak(aux_fan_max, pct)
                    elif fan_idx == 3:
                        exhaust_fan_max = _update_fan_peak(exhaust_fan_max, pct)
                continue

            if cmd == "M107":
                if not in_custom_block:
                    fan_idx = int(round(params.get("P", 0.0)))
                    if fan_idx == 0 and part_fan_max is None:
                        part_fan_max = 0
                    elif fan_idx == 2 and aux_fan_max is None:
                        aux_fan_max = 0
                    elif fan_idx == 3 and exhaust_fan_max is None:
                        exhaust_fan_max = 0
                continue

            if cmd == "G4":
                dwell = int(round(params["S"])) if "S" in params else int(round(params.get("P", 0.0) / 1000.0))
                if dwell >= _MIN_DWELL_SECONDS:
                    preheat_dwell_seconds = max(preheat_dwell_seconds, dwell)
                continue

            if cmd not in {"G0", "G1"}:
                continue

            if "F" in params and params["F"] > 0:
                feed_mm_s = params["F"] / 60.0

            nx = (params["X"] if abs_xyz else x + params["X"]) if "X" in params else x
            ny = (params["Y"] if abs_xyz else y + params["Y"]) if "Y" in params else y
            nz = (params["Z"] if abs_xyz else z + params["Z"]) if "Z" in params else z

            if "E" in params:
                raw_e = params["E"]
                de = (raw_e - e) if abs_e else raw_e
                e = raw_e if abs_e else (e + raw_e)
            else:
                de = 0.0

            dist_xy = math.hypot(nx - x, ny - y)
            move_dist = math.sqrt(dist_xy * dist_xy + (nz - z) ** 2)
            dt = (move_dist / feed_mm_s) if (move_dist > 1e-6 and feed_mm_s > 0) else 0.0

            is_printing = (not in_custom_block) and de > 1e-5 and dist_xy > 1e-4
            if not saw_layer_markers and is_printing:
                if layer_count == 0 or nz > last_print_z + 0.05:
                    layer_count += 1
                    last_print_z = nz
                    layer_times.setdefault(layer_count, 0.0)
                    layer_extruded.setdefault(layer_count, False)

            if layer_count >= 1 and not in_custom_block:
                layer_times[layer_count] = layer_times.get(layer_count, 0.0) + dt
                if is_printing:
                    layer_extruded[layer_count] = True

            if is_printing:
                max_print_speed = max(max_print_speed, feed_mm_s)
                if prev_print_speed is not None and abs(feed_mm_s - prev_print_speed) >= _SPEED_JUMP_THRESHOLD_MM_S:
                    speed_jump_count += 1
                prev_print_speed = feed_mm_s
                if dt > 1e-6:
                    volumetric = (de * area) / dt
                    if volumetric < 120.0:  # Ignora artefatos extremos de micro-movimento/prime.
                        max_volumetric = max(max_volumetric, volumetric)

                if layer_count == 1:
                    l1_min_x = min(l1_min_x, x, nx)
                    l1_max_x = max(l1_max_x, x, nx)
                    l1_min_y = min(l1_min_y, y, ny)
                    l1_max_y = max(l1_max_y, y, ny)
                    l1_has_bounds = True
                    steps = max(1, int(math.ceil(dist_xy / 1.0)))
                    for s_i in range(steps + 1):
                        t_u = s_i / steps
                        px = x + (nx - x) * t_u
                        py = y + (ny - y) * t_u
                        l1_cells.add((int(math.floor(px / 1.5)), int(math.floor(py / 1.5))))
                    if len(l1_segments) < _LAYER1_SEGMENT_CAP:
                        l1_segments.append((round(x, 2), round(y, 2), round(nx, 2), round(ny, 2)))

            x, y, z = nx, ny, nz

    timed_layers = [
        layer_times[idx]
        for idx, had_extrude in layer_extruded.items()
        if had_extrude and idx >= 2 and layer_times.get(idx, 0.0) > 0
    ]
    if not timed_layers:
        timed_layers = [
            layer_times[idx]
            for idx, had_extrude in layer_extruded.items()
            if had_extrude and layer_times.get(idx, 0.0) > 0
        ]
    min_layer_time = round(min(timed_layers), 2) if timed_layers else None
    short_layers = sum(1 for value in timed_layers if value < _SHORT_LAYER_THRESHOLD_S)

    bounds = (
        (round(l1_min_x, 2), round(l1_max_x, 2), round(l1_min_y, 2), round(l1_max_y, 2))
        if l1_has_bounds
        else None
    )
    return PlateGcodeAudit(
        plate=plate,
        layer_count=layer_count,
        first_layer_nozzle_temp=first_layer_nozzle_temp,
        nozzle_temps=tuple(nozzle_temps),
        bed_temps=tuple(bed_temps),
        part_fan_max_pct=part_fan_max,
        aux_fan_max_pct=aux_fan_max,
        exhaust_fan_max_pct=exhaust_fan_max,
        has_preheat_dwell=preheat_dwell_seconds >= _MIN_DWELL_SECONDS,
        preheat_dwell_seconds=preheat_dwell_seconds,
        max_volumetric_flow_mm3_s=round(max_volumetric, 2),
        min_layer_time_s=min_layer_time,
        short_layers_under_6s=short_layers,
        max_print_speed_mm_s=round(max_print_speed, 1),
        speed_jump_count=speed_jump_count,
        layer1_bounds_mm=bounds,
        layer1_island_count=_count_grid_islands(l1_cells) if l1_cells else 0,
        layer1_segments=tuple(l1_segments),
    )


def summarize_gcode_audit(
    audits: Iterable[PlateGcodeAudit],
    *,
    max_volumetric_limit: float | None = None,
    target_polymers: set[str] | frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Traduz métricas auditadas de G-code em achados práticos e verificáveis."""
    plate_list = list(audits)
    if not plate_list:
        return ()

    findings: list[str] = []
    upper_polymers = {p.upper() for p in target_polymers}
    abs_asa = any("ABS" in p or "ASA" in p for p in upper_polymers)

    for plate in plate_list:
        prefix = f"Placa {plate.plate}: " if len(plate_list) > 1 else ""
        if plate.has_preheat_dwell:
            mins = plate.preheat_dwell_seconds / 60.0
            findings.append(
                f"{prefix}Pré-aquecimento passivo confirmado no G-code (G4 S{plate.preheat_dwell_seconds}, ~{mins:.1f} min)."
            )
        if max_volumetric_limit is not None and plate.max_volumetric_flow_mm3_s > max_volumetric_limit + 0.5:
            findings.append(
                f"{prefix}Vazão volumétrica atingiu ~{plate.max_volumetric_flow_mm3_s:.1f} mm³/s acima do teto do perfil "
                f"({max_volumetric_limit:g} mm³/s); risco de subextrusão."
            )
        if plate.short_layers_under_6s > 0:
            min_txt = f"{plate.min_layer_time_s:.1f} s" if plate.min_layer_time_s is not None else "< 6 s"
            findings.append(
                f"{prefix}{plate.short_layers_under_6s} camada(s) abaixo de 6 s (mínima ~{min_txt}); "
                "pinos/topos podem amolecer sem resfriamento local."
            )
        if abs_asa and plate.part_fan_max_pct is not None and plate.part_fan_max_pct > 50:
            findings.append(
                f"{prefix}Ventoinha da peça comandada até {plate.part_fan_max_pct}% no G-code em ABS/ASA; "
                "pode resfriar em excesso áreas sem saliência e enfraquecer camadas."
            )
        if abs_asa and plate.aux_fan_max_pct is not None and plate.aux_fan_max_pct > 10:
            findings.append(
                f"{prefix}Ventoinha auxiliar em {plate.aux_fan_max_pct}% no G-code em ABS/ASA; "
                "sopro lateral favorece empenamento."
            )
        if plate.speed_jump_count >= 15:
            findings.append(
                f"{prefix}{plate.speed_jump_count} saltos bruscos de velocidade (>= 120 mm/s) no G-code; "
                "podem marcar a superfície externa (confira no preview)."
            )
        if plate.layer1_island_count >= 4:
            findings.append(
                f"{prefix}1ª camada com {plate.layer1_island_count} ilhas separadas; confira limpeza da placa."
            )

    return tuple(dict.fromkeys(findings))
