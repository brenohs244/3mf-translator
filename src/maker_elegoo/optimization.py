"""Compara objetivos de impressão usando cópias e fatiamento local."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .converter import ConversionResult, convert_project
from .mapping import ConversionPlan
from .project import ProjectInfo
from .slicer import SlicerCLI


OBJECTIVES = {
    "original": {},
    "qualidade": {},
    "velocidade": {},
    "economia": {"sparse_infill_density": "8%"},
    "resistencia": {"sparse_infill_density": "25%", "wall_loops": "4"},
}


@dataclass(frozen=True)
class Variant:
    objective: str
    result: ConversionResult
    changed: dict[str, str]


def compare_objectives(project: ProjectInfo, plan: ConversionPlan, destination_dir: Path,
                       slicer: SlicerCLI) -> tuple[Variant, ...]:
    """Fatia variantes separadas. Sem métricas, não ordena nem recomenda."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    variants = []
    for objective, changes in OBJECTIVES.items():
        allowed = {key: value for key, value in changes.items() if key in plan.process_settings}
        if objective in {"qualidade", "velocidade"} and "layer_height" in plan.process_settings:
            try:
                current = float(plan.process_settings["layer_height"])
                factor = 0.8 if objective == "qualidade" else 1.2
                proposed = round(current * factor, 3)
                if 0.08 <= proposed <= 0.32:
                    allowed["layer_height"] = f"{proposed:g}"
            except (TypeError, ValueError):
                pass
        settings = dict(plan.process_settings)
        settings.update(allowed)
        variant_plan = replace(plan, process_settings=settings)
        destination = destination_dir / f"{project.path.stem}_{objective}.3mf"
        if destination.exists():
            raise FileExistsError(destination)
        result = convert_project(project, variant_plan, destination, slicer)
        variants.append(Variant(objective, result, allowed))
    return tuple(variants)

