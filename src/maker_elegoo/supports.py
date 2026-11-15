"""Fórmula determinística de suportes otimizados para fácil remoção no ELEGOO Slicer."""

from __future__ import annotations

import math
from typing import Iterable

from .project import ProjectInfo

STICKY_POLYMERS = frozenset({"PETG", "ABS", "ASA", "PA", "PC", "TPU"})


def normalize_polymer(material: str) -> str:
    """Normaliza nome comercial do filamento para polímero base."""
    text = (material or "").strip().upper()
    for token in ("PETG", "ASA", "ABS", "TPU", "PLA", "PA", "PC"):
        if token in text:
            return token
    return text or "PLA"


def resolve_target_polymer(project: ProjectInfo | None, filament_settings: Iterable[dict]) -> str:
    """Identifica o polímero-alvo predominante (priorizando polímeros pegajosos nos slots usados)."""
    configs = list(filament_settings)
    used_slots = {
        str(slot) for slot in (getattr(project, "used_filament_slots", ()) or ())
        if slot and str(slot) != "0"
    }
    candidates: list[str] = []
    for idx, cfg in enumerate(configs, 1):
        if used_slots and str(idx) not in used_slots:
            continue
        raw = cfg.get("filament_type", [""])
        val = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
        poly = normalize_polymer(str(val or ""))
        candidates.append(poly)
    if not candidates:
        for cfg in configs:
            raw = cfg.get("filament_type", [""])
            val = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
            candidates.append(normalize_polymer(str(val or "")))
    for poly in candidates:
        if poly in STICKY_POLYMERS:
            return poly
    return candidates[0] if candidates else "PLA"


def _fmt_mm(value: float) -> str:
    return f"{round(value, 2):g}"


def compute_easy_support_settings(
    layer_height: float,
    nozzle_diameter: float,
    polymer: str = "PLA",
    *,
    support_type: str = "tree(auto)",
) -> dict[str, str]:
    """Calcula folgas Z/XY e camadas de interface para remoção limpa de suportes.

    Considera o arredondamento real do ELEGOO Slicer (`ceil(top_z / layer_height) * layer_height`
    quando `independent_support_layer_height = 0`) para impedir que uma pequena folga extra
    provoque salto para `2 × layer_height` acima do limite seguro de ponte do bico.
    """
    lh = max(0.06, min(0.60, float(layer_height)))
    nozzle = max(0.15, min(1.20, float(nozzle_diameter)))
    poly = normalize_polymer(polymer)
    sticky = poly in STICKY_POLYMERS

    if nozzle <= 0.25:
        desired_min_z = 0.16 if sticky else 0.14
        cap_factor = 0.80
    else:
        desired_min_z = 0.22 if sticky else 0.20
        cap_factor = 0.80 if sticky else 0.72

    max_cap_z = max(lh, round(cap_factor * nozzle, 2))
    steps = max(1, int(math.ceil((desired_min_z - 1e-6) / lh)))
    while steps > 1 and round(steps * lh, 2) > max_cap_z + 1e-6:
        steps -= 1
    z_gap = max(0.08, round(steps * lh, 2))
    z_str = _fmt_mm(z_gap)

    xy_factor = 1.50 if sticky else 1.25
    xy_floor = 0.45 if sticky else 0.35
    xy_gap = round(max(xy_floor, xy_factor * nozzle), 2)

    spacing_factor = 0.85 if sticky else 0.75
    spacing_floor = 0.25 if sticky else 0.20
    spacing_cap = 0.45 if sticky else 0.40
    raw_spacing = min(spacing_cap, max(spacing_floor, spacing_factor * nozzle))
    spacing = round(round(raw_spacing * 20.0) / 20.0, 2)

    stype_lower = (support_type or "tree(auto)").strip().lower()
    style = "snug" if "normal" in stype_lower else "tree_slim"

    return {
        "support_top_z_distance": z_str,
        "support_bottom_z_distance": z_str,
        "support_object_xy_distance": _fmt_mm(xy_gap),
        "support_interface_top_layers": "3",
        "support_interface_bottom_layers": "2",
        "support_interface_spacing": _fmt_mm(spacing),
        "support_style": style,
    }
