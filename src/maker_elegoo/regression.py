"""Regressão local de projetos 3MF; não copia nem envia arquivos de entrada."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .converter import convert_project
from .mapping import ConversionPlan
from .project import inspect_project
from .slicer import SlicerCLI


@dataclass(frozen=True)
class RegressionCase:
    path: Path
    plan: ConversionPlan


def run_regression(cases: list[RegressionCase], output_dir: Path, slicer: SlicerCLI) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, case in enumerate(cases, 1):
        project = inspect_project(case.path)
        destination = output_dir / f"case_{index}.3mf"
        result = convert_project(project, case.plan, destination, slicer)
        rows.append({"case": index, "source_name": case.path.name, "success": result.success,
                     "message": result.message, "plates": len(project.plates),
                     "sliced_plates": result.validation.plate_count if result.validation else 0,
                     "slicer_executable": str(slicer.executable),
                     "machine_profile": case.plan.machine.name,
                     "process_profile": case.plan.process.name,
                     "filament_profiles": [profile.name for profile in case.plan.filaments]})
    report = output_dir / "regression.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
