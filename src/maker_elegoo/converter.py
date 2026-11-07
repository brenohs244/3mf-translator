"""Orquestra a conversão, a validação e o relatório de fidelidade."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from .mapping import ConversionPlan
from .project import ProjectInfo, inspect_project
from .slicer import ExportResult, SlicerCLI, ValidationResult


@dataclass(frozen=True)
class GeometryComparison:
    unchanged: bool
    changed_resources: tuple[str, ...]


@dataclass(frozen=True)
class ConversionResult:
    success: bool
    destination: Path
    message: str
    export: ExportResult
    validation: ValidationResult | None
    geometry: GeometryComparison | None
    output_project: ProjectInfo | None
    unmapped: dict


def _geometry_hashes(path: Path) -> dict[str, str]:
    result = {}
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("3D/") and name.endswith(".model"):
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    count = 0
                    try:
                        for _, element in ElementTree.iterparse(stream, events=("end",)):
                            tag = element.tag.rsplit("}", 1)[-1]
                            if tag in {"vertex", "triangle"}:
                                digest.update(tag.encode())
                                for key, value in sorted(element.attrib.items()):
                                    digest.update(key.encode())
                                    digest.update(value.encode())
                                count += 1
                            element.clear()
                    except ElementTree.ParseError:
                        count = 0
                if count:
                    result[name] = digest.hexdigest()
        if not result:
            # Um 3MF sem registros de malha não permite comparação semântica.
            result = {name: hashlib.sha256(archive.read(name)).hexdigest()
                      for name in archive.namelist()
                      if name.startswith("3D/") and name.endswith(".model")}
    return result


def compare_geometry(source: Path, target: Path) -> GeometryComparison:
    before, after = _geometry_hashes(source), _geometry_hashes(target)
    if Counter(before.values()) == Counter(after.values()):
        return GeometryComparison(True, ())
    changed = tuple(sorted(name for name in before.keys() | after.keys()
                           if before.get(name) != after.get(name)))
    return GeometryComparison(False, changed)


def convert_project(project: ProjectInfo, plan: ConversionPlan, destination: Path,
                    slicer: SlicerCLI) -> ConversionResult:
    exported = slicer.export(project, plan, destination)
    if not exported.success:
        return ConversionResult(False, exported.destination, exported.message, exported,
                                None, None, None, plan.unmapped)
    try:
        output = inspect_project(exported.destination)
    except Exception as exc:
        return ConversionResult(False, exported.destination, f"Saída 3MF inválida: {exc}", exported,
                                None, None, None, plan.unmapped)
    if output.source_settings.get("printer_model") != "Elegoo Centauri Carbon 2":
        return ConversionResult(False, exported.destination, "Impressora de destino incorreta no 3MF",
                                exported, None, None, output, plan.unmapped)
    if len(output.plates) != len(project.plates):
        return ConversionResult(False, exported.destination, "Quantidade de placas mudou na exportação",
                                exported, None, None, output, plan.unmapped)
    geometry = compare_geometry(project.path, exported.destination)
    validation = slicer.validate(exported.destination, len(output.plates))
    unmapped = {key: value for key, value in project.source_settings.items()
                if key not in output.source_settings}
    return ConversionResult(validation.success, exported.destination, validation.message,
                            exported, validation, geometry, output, unmapped)
