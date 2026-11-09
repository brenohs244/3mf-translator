"""Plano explícito de transferência de parâmetros de processo."""

from __future__ import annotations

from dataclasses import dataclass

from .materials import Finding, analyze_material_change
from .profiles import Profile, SlicerInstall, machine_family_names, resolve_profile
from .project import ProjectInfo


# Ajustes de intenção do modelo; velocidades, acelerações e temperaturas vêm do ELEGOO.
TRANSFERABLE = {
    "wall_loops", "top_shell_layers", "bottom_shell_layers", "sparse_infill_density",
    "sparse_infill_pattern", "enable_support", "support_type",
    "support_on_build_plate_only", "brim_type", "brim_width",
    "seam_position", "ironing_type", "detect_thin_wall",
}

SOURCE_REPAIRS = {"raft_first_layer_expansion": "0", "tree_support_wall_count": "0"}


@dataclass(frozen=True)
class ConversionPlan:
    machine: Profile
    process: Profile
    filaments: tuple[Profile, ...]
    machine_settings: dict
    process_settings: dict
    filament_settings: tuple[dict, ...]
    transferred: dict
    unmapped: dict
    replaced: dict
    source_repairs: dict
    material_findings: tuple[Finding, ...]


def _valid_transfer(key: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if key in {"wall_loops", "top_shell_layers", "bottom_shell_layers"}:
        return value.isdigit() and 0 <= int(value) <= 20
    if key == "sparse_infill_density":
        try:
            return value.endswith("%") and 0 <= float(value[:-1]) <= 100
        except ValueError:
            return False
    if key in {"enable_support", "support_on_build_plate_only", "detect_thin_wall"}:
        return value in {"0", "1"}
    return len(value) <= 100 and "\n" not in value


def build_conversion(project: ProjectInfo, install: SlicerInstall, machine: Profile,
                     process: Profile, filaments: list[Profile]) -> ConversionPlan:
    if len(filaments) != len(project.filaments):
        raise ValueError("Escolha um perfil ELEGOO para cada filamento do projeto")
    machine_settings = resolve_profile(machine, install)
    process_settings = resolve_profile(process, install)
    filament_settings = tuple(resolve_profile(item, install) for item in filaments)
    if machine_settings.get("printer_model") != "Elegoo Centauri Carbon 2":
        raise ValueError("O perfil de máquina não é da Centauri Carbon 2")
    nozzle = str(machine_settings.get("nozzle_diameter", [""])[0])
    compatible_machines = machine_family_names(machine, install)
    compatible = process_settings.get("compatible_printers", [])
    if compatible and not compatible_machines.intersection(compatible):
        raise ValueError(f"Processo incompatível com o bico {nozzle}")
    for index, config in enumerate(filament_settings):
        compatible = config.get("compatible_printers", [])
        if compatible and not compatible_machines.intersection(compatible):
            raise ValueError(f"Filamento {index + 1} incompatível com o bico {nozzle}")
    transferred = {}
    for key in TRANSFERABLE:
        value = project.source_settings.get(key)
        if key in process_settings and _valid_transfer(key, value):
            process_settings[key] = value
            transferred[key] = value
    supported = set(machine_settings) | set(process_settings)
    for config in filament_settings:
        supported.update(config)
    unmapped = {key: value for key, value in project.source_settings.items()
                if key not in supported and key not in SOURCE_REPAIRS}
    replaced = {key: value for key, value in project.source_settings.items()
                if key in supported and key not in transferred and key not in SOURCE_REPAIRS}
    repairs = {key: replacement for key, replacement in SOURCE_REPAIRS.items()
               if project.source_settings.get(key) == "-1"}
    findings = analyze_material_change(project, list(filament_settings))
    return ConversionPlan(machine, process, tuple(filaments), machine_settings, process_settings,
                          filament_settings, transferred, unmapped, replaced, repairs, tuple(findings))
