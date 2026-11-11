"""Compara orientações com exportação e fatiamento locais no ELEGOO Slicer."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .converter import ConversionResult, convert_project
from .mapping import ConversionPlan
from .orientation import (Candidate, OrientationError, load_scene,
                          rank_orientations, write_oriented_copy)
from .project import ProjectInfo, inspect_project
from .slicer import SlicerCLI


@dataclass(frozen=True)
class OrientationEvaluation:
    candidate: Candidate
    result: ConversionResult


@dataclass(frozen=True)
class OrientationAnalysis:
    front: str
    current: OrientationEvaluation
    alternatives: tuple[OrientationEvaluation, ...]
    recommended: Candidate
    reason: str
    rejected: tuple[Candidate, ...] = ()


def evaluate_orientations(project: ProjectInfo, plan: ConversionPlan, front: str,
                          slicer: SlicerCLI, *,
                          progress: Callable[[str, int, int], None] | None = None,
                          cancelled: Callable[[], bool] | None = None) -> OrientationAnalysis:
    if cancelled and cancelled():
        raise OrientationError("Análise de orientação cancelada")
    scene = load_scene(project.path)
    area = plan.machine_settings.get("printable_area", [])
    height = float(plan.machine_settings.get("printable_height", "0"))
    candidates = rank_orientations(scene, front, area, height)
    selected = [candidates[0], *[item for item in candidates[1:] if item.valid][:2]]
    evaluations = []
    with tempfile.TemporaryDirectory(prefix="maker-elegoo-orientation-") as scratch:
        folder = Path(scratch)
        for index, candidate in enumerate(selected, 1):
            if cancelled and cancelled():
                raise OrientationError("Análise de orientação cancelada")
            if progress:
                progress(candidate.label, index, len(selected))
            if candidate.is_current:
                input_project = project
            else:
                oriented = write_oriented_copy(project.path, candidate,
                                               folder / f"candidate_{index}.3mf")
                input_project = inspect_project(oriented)
            result = convert_project(input_project, plan, folder / f"result_{index}.3mf", slicer)
            evaluations.append(OrientationEvaluation(candidate, result))
    current, *alternatives = evaluations
    good = [item for item in alternatives if item.candidate.valid and item.result.success]
    if not current.result.success and good:
        chosen = min(good, key=lambda item: item.candidate.score)
        reason = "A posição atual falhou no fatiamento; a alternativa foi validada."
    else:
        threshold = current.candidate.front_overhang_mm2 * 0.85
        improved = [item for item in good
                    if item.candidate.front_overhang_mm2 < threshold]
        chosen = min(improved, key=lambda item: item.candidate.score) if improved else None
        reason = ("Risco frontal estimado menor e fatiamento validado."
                  if chosen else "Nenhuma alternativa validada melhorou claramente a frente; mantenha a posição atual.")
    rejected = tuple(item for item in candidates[1:] if not item.valid)
    return OrientationAnalysis(front, current, tuple(alternatives),
                               chosen.candidate if chosen else current.candidate, reason, rejected)


def apply_orientation(project: ProjectInfo, plan: ConversionPlan, candidate: Candidate,
                      destination: Path, slicer: SlicerCLI) -> ConversionResult:
    destination = Path(destination)
    if destination.exists() or destination.resolve() == project.path.resolve():
        raise FileExistsError("Escolha um novo nome para a cópia orientada")
    if candidate.is_current or not candidate.valid:
        raise OrientationError("A posição escolhida não é uma alternativa válida")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maker-elegoo-orientation-apply-",
                                     dir=destination.parent) as scratch:
        oriented = write_oriented_copy(project.path, candidate,
                                       Path(scratch) / "oriented.3mf")
        expected = load_scene(oriented)
        provisional = Path(scratch) / "validated.3mf"
        result = convert_project(inspect_project(oriented), plan, provisional, slicer)
        public = replace(result, destination=destination,
                         export=replace(result.export, destination=destination),
                         output_project=None)
        if not result.success:
            return public
        try:
            actual = load_scene(provisional)
            same_rotation = all(abs(left - right) <= 0.001 for left, right in
                                zip(expected.world_transform[:9], actual.world_transform[:9]))
        except OrientationError:
            same_rotation = False
        if not same_rotation:
            return replace(public, success=False,
                           message="O fatiador alterou a orientação da cópia; confira antes de imprimir")
        if destination.exists():
            raise FileExistsError("O destino passou a existir durante o fatiamento")
        provisional.rename(destination)
        output_project = replace(result.output_project, path=destination) if result.output_project else None
        return replace(public, output_project=output_project)
