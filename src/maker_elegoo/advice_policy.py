"""Política única e determinística de restrições para Professor, IA e otimização."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

from .mapping import ConversionPlan
from .project import ProjectInfo

if TYPE_CHECKING:
    from .professor import Advice, PrintGoal


HARD_POLICY_RULES: dict[str, str] = {
    "wall_loops": "Piso mínimo de paredes perimetrais por uso e carga.",
    "top_shell_layers": "Piso mínimo de camadas sólidas de topo.",
    "bottom_shell_layers": "Piso mínimo de camadas sólidas de base.",
    "sparse_infill_density": "Piso mínimo de preenchimento estrutural ou térmico (ABS/ASA/PA/PC).",
    "sparse_infill_pattern": "Restrição contra padrões com cruzamento em articulações ou impacto.",
    "layer_height": "Limites do bico/máquina e teto para preservar folgas e partes móveis.",
    "brim_type": "Bloqueio de brim automático ou externo em peças articuladas ou com folgas móveis.",
    "outer_wall_speed": "Teto de velocidade externa para precisão dimensional, qualidade e TPU.",
    "inner_wall_speed": "Limites seguros de velocidade interna do perfil.",
    "top_surface_speed": "Limites seguros de velocidade superior do perfil.",
    "fan_min_speed": "Limites de ventoinha mínima compatíveis com o polímero.",
    "fan_max_speed": "Teto de ventoinha da peça para evitar choque térmico e delaminação.",
    "overhang_fan_speed": "Teto de ventoinha em saliências para polímeros sensíveis a choque térmico.",
    "additional_cooling_fan_speed": "Bloqueio da ventoinha auxiliar lateral em polímeros com retração.",
    "close_fan_the_first_x_layers": "Piso de camadas iniciais sem ventoinha para aderência térmica.",
    "slow_down_layer_time": "Piso de tempo mínimo por camada para estabilidade térmica.",
    "during_print_exhaust_fan_speed": "Faixa segura de exaustão do gabinete.",
    "passive_preheat_seconds": "Limites seguros de pré-aquecimento passivo na mesa.",
    "filament_shrink": "Faixa segura de compensação de retração.",
    "elefant_foot_compensation": "Faixa segura de compensação de pé de elefante.",
    "xy_contour_compensation": "Faixa segura de compensação XY de contorno.",
    "xy_hole_compensation": "Faixa segura de compensação XY de furos.",
}

OPTIONAL_ADVICE_KEYS: frozenset[str] = frozenset({
    "seam_position",
    "ironing_type",
    "wall_generator",
    "brim_width",
    "enable_support",
    "support_type",
    "support_style",
    "support_top_z_distance",
    "support_bottom_z_distance",
    "support_object_xy_distance",
    "support_interface_top_layers",
    "support_interface_bottom_layers",
    "support_interface_spacing",
})

_WARP_SENSITIVE_POLYMERS = frozenset({"ABS", "ASA", "PA", "PC"})


@dataclass(frozen=True)
class PolicyResult:
    """Resultado da validação conservadora sobre um conjunto de propostas."""

    accepted: tuple[Advice, ...]
    rejected: tuple[Advice, ...]
    reasons: tuple[str, ...]


def _as_str(val: Any, default: str = "") -> str:
    if isinstance(val, list):
        return str(val[0]) if val else default
    if val is None:
        return default
    return str(val)


def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(_as_str(val, str(default)).rstrip("%")))
    except (TypeError, ValueError):
        return default


def _as_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(_as_str(val, str(default)).rstrip("%"))
    except (TypeError, ValueError):
        return default


def _polymer_family(raw: Any) -> str:
    text = _as_str(raw, "").strip().upper()
    if not text:
        return ""
    if text.startswith("PETG"):
        return "PETG"
    if text.startswith("TPU"):
        return "TPU"
    if text.startswith("ASA"):
        return "ASA"
    if text.startswith("ABS"):
        return "ABS"
    if text.startswith("PLA"):
        return "PLA"
    return text.split("-", 1)[0].split(" ", 1)[0]


def _active_filament_cfgs(project: ProjectInfo | None, plan: ConversionPlan) -> list[tuple[int, dict[str, Any]]]:
    used = set(getattr(project, "used_filament_slots", ()) or ())
    if used:
        filtered = [(idx, cfg) for idx, cfg in enumerate(plan.filament_settings, start=1) if str(idx) in used]
        if filtered:
            return filtered
    return [(idx, cfg) for idx, cfg in enumerate(plan.filament_settings, start=1)]


def _check_policy_violation(
    adv: Advice,
    project: ProjectInfo | None,
    plan: ConversionPlan,
    goal: PrintGoal | None,
) -> str | None:
    from .professor import validate_change

    if adv.scope == "alert":
        return None

    proposed_str = str(adv.proposed)
    if not validate_change(adv.scope, adv.key, proposed_str, plan, slot=adv.slot):
        return (
            f"Proposta rejeitada para {adv.key} = {proposed_str}: valor fora da faixa segura "
            f"ou ausente no perfil da máquina ({adv.scope})."
        )

    purpose = getattr(goal, "purpose", "nao_sei") or "nao_sei"
    priority = getattr(goal, "priority", "equilibrio") or "equilibrio"
    load_type = getattr(goal, "load_type", "nao_sei") or "nao_sei"
    fit_clearance = getattr(goal, "fit_clearance", "nao_se_aplica") or "nao_se_aplica"
    heat_exposure = getattr(goal, "heat_exposure", "ambiente") or "ambiente"

    is_articulated = purpose in {"moveis", "chaveiro_articulado"} or fit_clearance == "partes_moveis"
    has_fit_clearance = is_articulated or fit_clearance == "encaixe_justo"
    active_cfgs = _active_filament_cfgs(project, plan)
    active_polymers = {_polymer_family(cfg.get("filament_type", "")) for _, cfg in active_cfgs}
    phys_mat = _polymer_family(getattr(goal, "physical_material", "")) if goal else ""
    if phys_mat:
        active_polymers.add(phys_mat)
    has_warp_sensitive = bool(active_polymers & _WARP_SENSITIVE_POLYMERS)
    has_tpu = "TPU" in active_polymers
    nozzle = _as_float(plan.machine_settings.get("nozzle_diameter", "0.4"), 0.4)

    if adv.scope == "process":
        key = adv.key
        if key == "wall_loops":
            floor = 1
            if purpose == "esforco":
                floor = 5 if load_type == "flexao_lateral" else 4
            elif purpose in {"funcional_leve", "moveis", "chaveiro_rigido", "chaveiro_articulado"}:
                floor = 3
            if load_type == "impacto" or purpose == "externa":
                floor = max(floor, 4)
            if int(proposed_str) < floor:
                return (
                    f"Proposta rejeitada para wall_loops = {proposed_str}: a regra conservadora "
                    f"para uso '{purpose}' exige piso mínimo de {floor} paredes."
                )

        elif key == "top_shell_layers":
            floor = 0
            if purpose in {"esforco", "chaveiro_rigido"} or heat_exposure in {"calor_sol", "agua_externo"}:
                floor = 5
            elif purpose in {"funcional_leve", "chaveiro_articulado"}:
                floor = 4
            if int(proposed_str) < floor:
                return (
                    f"Proposta rejeitada para top_shell_layers = {proposed_str}: a regra conservadora "
                    f"exige piso mínimo de {floor} camadas de topo."
                )

        elif key == "bottom_shell_layers":
            floor = 4 if purpose == "chaveiro_rigido" else (3 if purpose in {"esforco", "funcional_leve", "externa"} else 0)
            if int(proposed_str) < floor:
                return (
                    f"Proposta rejeitada para bottom_shell_layers = {proposed_str}: a regra conservadora "
                    f"exige piso mínimo de {floor} camadas de base."
                )

        elif key == "sparse_infill_density":
            floor = 0.0
            if purpose == "esforco":
                floor = 40.0 if load_type == "compressao" else 30.0
            elif purpose == "chaveiro_rigido":
                floor = 25.0
            elif purpose in {"funcional_leve", "chaveiro_articulado"}:
                floor = 20.0
            if has_warp_sensitive:
                floor = max(floor, 20.0)
            if _as_float(proposed_str, 0.0) < floor - 1e-6:
                return (
                    f"Proposta rejeitada para sparse_infill_density = {proposed_str}: a regra conservadora "
                    f"exige piso mínimo de {floor:g}%."
                )

        elif key == "sparse_infill_pattern":
            if (is_articulated or load_type == "impacto") and proposed_str == "grid":
                return (
                    f"Proposta rejeitada para sparse_infill_pattern = {proposed_str}: padrão com cruzamento "
                    "não é permitido para articulações ou impacto na política conservadora."
                )

        elif key == "brim_type":
            if is_articulated and proposed_str != "no_brim":
                return (
                    f"Proposta rejeitada para brim_type = {proposed_str}: a regra conservadora "
                    "proíbe brim automático ou externo em peças articuladas/móveis para evitar travamento da camada 1."
                )

        elif key == "layer_height":
            proposed_h = _as_float(proposed_str, 0.2)
            if has_fit_clearance:
                max_clearance_h = round(0.5 * nozzle, 2)
                if proposed_h > max_clearance_h + 1e-6:
                    return (
                        f"Proposta rejeitada para layer_height = {proposed_str}: a regra conservadora "
                        f"de partes móveis/folgas limita a altura de camada a <= {max_clearance_h:g} mm."
                    )
            if priority == "qualidade":
                cur_h = _as_float(plan.process_settings.get("layer_height"), 0.2)
                if proposed_h > cur_h + 1e-6:
                    return (
                        f"Proposta rejeitada para layer_height = {proposed_str}: prioridade qualidade "
                        f"impede engrossar camada acima de {cur_h:g} mm."
                    )

        elif key == "ironing_type":
            if is_articulated and proposed_str != "no ironing":
                return (
                    f"Proposta rejeitada para ironing_type = {proposed_str}: alisamento pode fundir "
                    "folgas entre elos na política conservadora."
                )

        elif key == "outer_wall_speed":
            spd = _as_float(proposed_str, 160.0)
            if has_tpu and spd > 80.0 + 1e-6:
                return (
                    f"Proposta rejeitada para outer_wall_speed = {proposed_str}: a regra conservadora "
                    "limita TPU a <= 80 mm/s na parede externa."
                )
            if priority == "qualidade":
                target_outer = (
                    60.0 if purpose in {"decorativa", "chaveiro_rigido"}
                    else (70.0 if purpose == "chaveiro_articulado" else 80.0)
                )
                if spd > target_outer + 1e-6:
                    return (
                        f"Proposta rejeitada para outer_wall_speed = {proposed_str}: prioridade qualidade "
                        f"limita parede externa a <= {target_outer:g} mm/s."
                    )

    elif adv.scope == "filament" and adv.slot is not None and 1 <= adv.slot <= len(plan.filament_settings):
        cfg = plan.filament_settings[adv.slot - 1]
        mat = _polymer_family(cfg.get("filament_type", "")) or phys_mat
        if mat in _WARP_SENSITIVE_POLYMERS:
            min_fan = _as_int(cfg.get("fan_min_speed", "10"), 10)
            desired_fan = 25 if purpose in {"esforco", "funcional_leve"} else 35
            if mat in {"PA", "PC"}:
                desired_fan = min(desired_fan, 25)
            fan_cap = max(min_fan, 15, desired_fan)
            val_int = _as_int(proposed_str, 0)
            if adv.key == "fan_max_speed" and val_int > fan_cap:
                return (
                    f"Proposta rejeitada para fan_max_speed = {proposed_str}%: a regra conservadora "
                    f"para {mat} em câmara passiva limita a ventoinha da peça a <= {fan_cap}%."
                )
            if adv.key == "fan_min_speed" and val_int > fan_cap:
                return (
                    f"Proposta rejeitada para fan_min_speed = {proposed_str}%: a regra conservadora "
                    f"para {mat} limita a ventoinha mínima a <= {fan_cap}%."
                )
            oh_cap = max(min_fan, 55)
            if adv.key == "overhang_fan_speed" and val_int > oh_cap:
                return (
                    f"Proposta rejeitada para overhang_fan_speed = {proposed_str}%: a regra conservadora "
                    f"para {mat} limita a ventoinha em saliências a <= {oh_cap}%."
                )
            if adv.key == "additional_cooling_fan_speed" and val_int > 0:
                return (
                    f"Proposta rejeitada para additional_cooling_fan_speed = {proposed_str}%: "
                    f"a regra conservadora proíbe ventoinha auxiliar lateral para {mat}."
                )
            if adv.key == "close_fan_the_first_x_layers" and val_int < 3:
                return (
                    f"Proposta rejeitada para close_fan_the_first_x_layers = {proposed_str}: "
                    f"a regra conservadora para {mat} exige >= 3 camadas iniciais sem ventoinha."
                )
            geom = getattr(project, "geometry_summary", None)
            slow_floor = 8 if getattr(geom, "has_slender_parts", False) else 6
            if adv.key == "slow_down_layer_time" and val_int < slow_floor:
                return (
                    f"Proposta rejeitada para slow_down_layer_time = {proposed_str}s: "
                    f"a regra conservadora para {mat} exige piso mínimo de {slow_floor}s por camada."
                )

    return None


def enforce_advice_policy(
    project: ProjectInfo | None,
    plan: ConversionPlan,
    goal: PrintGoal | None,
    proposals: Iterable[Advice],
) -> PolicyResult:
    """Filtra propostas de IA, Professor e prioridades sob regras conservadoras únicas."""
    accepted: list[Advice] = []
    rejected: list[Advice] = []
    reasons: list[str] = []
    for adv in proposals:
        reason = _check_policy_violation(adv, project, plan, goal)
        if reason:
            rejected.append(adv)
            reasons.append(reason)
        else:
            accepted.append(adv)
    return PolicyResult(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        reasons=tuple(reasons),
    )


def build_policy_conflict_alert(reasons: Iterable[str], *, source_label: str = "IA") -> Advice:
    """Cria alerta explícito documentando propostas bloqueadas pela política local."""
    from .professor import Advice

    reason_list = [r for r in reasons if r]
    return Advice(
        scope="alert",
        slot=None,
        key="",
        current="",
        proposed="",
        title=f"Conflito com política conservadora ({source_label})",
        why="\n".join(reason_list),
        expected_effect="Mantido o piso/teto conservador local para evitar regressão de resistência, folga ou resfriamento.",
        what_to_check="Revise os valores rejeitados e confirme no ELEGOO Slicer se deseja ajustar manualmente.",
        evidence_class="estimado_regra_ia",
        requires_physical_test=False,
        confidence="alta",
        default_on=False,
    )
