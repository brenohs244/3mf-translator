"""Diferenças observáveis entre os materiais do projeto e os perfis ELEGOO."""

from __future__ import annotations

from dataclasses import dataclass

from .project import ProjectInfo


@dataclass(frozen=True)
class Finding:
    slot: int
    key: str
    source: str
    target: str
    message: str


MATERIAL_KEYS = (
    "nozzle_temperature",
    "textured_plate_temp",
    "fan_max_speed",
    "filament_max_volumetric_speed",
)


def _at(value: object, index: int) -> str:
    if isinstance(value, list):
        return str(value[index]) if index < len(value) else ""
    return "" if value is None else str(value)


def analyze_material_change(project: ProjectInfo, target_filaments: list[dict]) -> list[Finding]:
    if len(target_filaments) != len(project.filaments):
        raise ValueError("Escolha um perfil para cada filamento")
    findings: list[Finding] = []
    for index, (source, target) in enumerate(zip(project.filaments, target_filaments)):
        target_material = _at(target.get("filament_type"), 0) or "Desconhecido"
        if source.material.upper() != target_material.upper():
            findings.append(Finding(source.slot, "filament_type", source.material, target_material,
                                    "Troca de material: confirme a aplicação da peça e a compatibilidade dos materiais"))
        for key in MATERIAL_KEYS:
            before = _at(project.source_settings.get(key), index)
            after = _at(target.get(key), 0)
            if before and after and before != after:
                findings.append(Finding(source.slot, key, before, after,
                                        f"Perfil ELEGOO altera {key} no filamento {source.slot}"))
    return findings
