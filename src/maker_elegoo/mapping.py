"""Plano explícito de transferência de parâmetros de processo."""

from __future__ import annotations

from dataclasses import dataclass

from .materials import Finding, analyze_material_change
from .profiles import Profile, SlicerInstall, machine_family_names, resolve_profile
from .project import ProjectInfo


# Ajustes de intenção do modelo; velocidades, acelerações e temperaturas vêm do ELEGOO.
TRANSFERABLE = {
    "wall_loops", "wall_generator", "top_shell_layers", "bottom_shell_layers",
    "sparse_infill_density", "sparse_infill_pattern",
    "enable_support", "support_type", "support_style",
    "support_top_z_distance", "support_interface_top_layers", "support_threshold_angle",
    "support_on_build_plate_only", "brim_type", "brim_width",
    "seam_position", "ironing_type", "detect_thin_wall", "enable_prime_tower",
}

SOURCE_REPAIRS = {"raft_first_layer_expansion": "0", "tree_support_wall_count": "0"}
SOURCE_REMOVE_KEYS = frozenset({
    "master_extruder_id",
    "extruder_ams_count",
    "extruder_printable_area",
    "extruder_printable_height",
    "extruder_type",
    "extruder_variant_list",
    "default_nozzle_volume_type",
    "physical_extruder_map",
    "print_extruder_id",
    "print_extruder_variant",
    "printer_extruder_id",
    "printer_extruder_variant",
    "nozzle_flush_dataset",
    "nozzle_volume_type",
    "grab_length",
    "extruder_max_nozzle_count",
    "extruder_nozzle_stats",
})


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
    if key == "wall_generator":
        return value in {"classic", "arachne"}
    if key == "support_style":
        return value in {
            "default", "grid", "snug",
            "tree_auto", "tree_slim", "tree_strong", "tree_hybrid", "organic",
        }
    if key == "support_top_z_distance":
        try:
            dist = float(value)
            return 0.0 <= dist <= 1.0
        except ValueError:
            return False
    if key == "support_interface_top_layers":
        return value.isdigit() and 0 <= int(value) <= 10
    if key == "support_threshold_angle":
        try:
            angle = float(value)
            return 0.0 <= angle <= 89.0
        except ValueError:
            return False
    if key == "sparse_infill_density":
        try:
            return value.endswith("%") and 0 <= float(value[:-1]) <= 100
        except ValueError:
            return False
    if key in {"enable_support", "support_on_build_plate_only", "detect_thin_wall", "enable_prime_tower"}:
        return value in {"0", "1"}
    if key == "brim_type":
        return value in {"auto_brim", "outer_only", "no_brim"}
    return len(value) <= 100 and "\n" not in value


def suggest_process(source_settings: dict, available_processes: list[Profile]) -> Profile | None:
    if not available_processes:
        return None
    raw_h = source_settings.get("layer_height")
    try:
        target_h = float(str(raw_h))
    except (TypeError, ValueError):
        target_h = 0.20

    def score(p: Profile) -> tuple[float, int, str]:
        import re
        h = None
        if "layer_height" in p.data:
            try:
                h = float(p.data["layer_height"])
            except (ValueError, TypeError):
                pass
        if h is None:
            m = re.search(r"(\d+(?:\.\d+)?)\s*mm", p.name, re.IGNORECASE)
            if m:
                try:
                    h = float(m.group(1))
                except ValueError:
                    pass
        if h is None:
            h = 0.20

        diff = abs(h - target_h)
        priority = 2
        name_lower = p.name.lower()
        if "standard" in name_lower:
            priority = 0
        elif "fine" in name_lower:
            priority = 1
        return (round(diff, 4), priority, p.name)

    return sorted(available_processes, key=score)[0]


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
        if (key in process_settings or key == "brim_type") and _valid_transfer(key, value):
            process_settings[key] = value
            transferred[key] = value
    single_plate_multicolor = any(
        len({slot for slot in ((getattr(plate, "used_filament_slots", ()) or plate.filament_slots))
             if slot and slot != "0"}) >= 2
        for plate in project.plates
    )
    if single_plate_multicolor and "enable_prime_tower" in process_settings:
        process_settings["enable_prime_tower"] = "1"
    repairs: dict[str, str | None] = {
        key: replacement for key, replacement in SOURCE_REPAIRS.items()
        if project.source_settings.get(key) == "-1"
    }
    nozzles = machine_settings.get("nozzle_diameter", ["0.4"])
    if not isinstance(nozzles, list) or len(nozzles) <= 1:
        for key in SOURCE_REMOVE_KEYS:
            if key in project.source_settings:
                repairs[key] = None
    supported = set(machine_settings) | set(process_settings)
    for config in filament_settings:
        supported.update(config)
    unmapped = {key: value for key, value in project.source_settings.items()
                if key not in supported and key not in SOURCE_REPAIRS and key not in repairs}
    replaced = {key: value for key, value in project.source_settings.items()
                if key in supported and key not in transferred and key not in SOURCE_REPAIRS and key not in repairs}
    findings = analyze_material_change(project, list(filament_settings))
    return ConversionPlan(machine, process, tuple(filaments), machine_settings, process_settings,
                          filament_settings, transferred, unmapped, replaced, repairs, tuple(findings))
