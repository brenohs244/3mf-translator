"""Compara objetivos de impressão usando cópias e fatiamento local."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .converter import ConversionResult, convert_project
from .labels import evidence_label, format_duration, load_type_label, priority_label, purpose_label
from .mapping import ConversionPlan
from .professor import PrintGoal, advise_offline, apply_advice
from .project import ProjectInfo
from .slicer import SlicerCLI, next_available_destination


OBJECTIVES = {
    "original": {},
    "qualidade": {},
    "velocidade": {},
    "equilibrio": {"sparse_infill_density": "20%", "wall_loops": "3"},
    "economia": {"sparse_infill_density": "10%"},
}

OBJECTIVE_TITLES = {
    "original": "ORIGINAL (perfil ELEGOO convertido)",
    "qualidade": "QUALIDADE (camada menor)",
    "velocidade": "VELOCIDADE (camada maior)",
    "equilibrio": "EQUILÍBRIO (meio-termo entre qualidade e tempo)",
    "economia": "ECONOMIA (preenchimento reduzido)",
}


@dataclass(frozen=True)
class Variant:
    objective: str
    result: ConversionResult
    changed: dict[str, str]


def _first_float(val: object, default: float) -> float:
    if isinstance(val, (list, tuple)):
        val = val[0] if val else default
    try:
        return float(str(val))
    except (TypeError, ValueError):
        return default


def compare_objectives(project: ProjectInfo, plan: ConversionPlan, destination_dir: Path,
                       slicer: SlicerCLI, *, goal: PrintGoal | Any = None) -> tuple[Variant, ...]:
    """Fatia variantes separadas. Sem métricas, não ordena nem recomenda."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    mach = getattr(plan, "machine_settings", {}) or {}
    nozzle = _first_float(mach.get("nozzle_diameter", "0.4"), 0.4)
    min_h = _first_float(mach.get("min_layer_height", "0.08"), 0.08)
    max_h = min(_first_float(mach.get("max_layer_height", "0.28"), 0.28), round(0.75 * nozzle, 2))
    has_full_plan = goal is not None and bool(getattr(plan, "filament_settings", None))
    variants = []
    for objective, changes in OBJECTIVES.items():
        if has_full_plan:
            if objective == "original":
                variant_plan = plan
                allowed: dict[str, str] = {}
            else:
                variant_goal = PrintGoal(
                    purpose=getattr(goal, "purpose", "nao_sei"),
                    priority=objective,
                    load_type=getattr(goal, "load_type", "nao_sei"),
                    criticality=getattr(goal, "criticality", "nao_sei"),
                    fit_clearance=getattr(goal, "fit_clearance", "nao_sei"),
                    heat_exposure=getattr(goal, "heat_exposure", "nao_sei"),
                    physical_material=getattr(goal, "physical_material", "nao_sei"),
                )
                advices = advise_offline(project, plan, variant_goal)
                approved = [adv for adv in advices if adv.scope != "alert" and adv.default_on]
                variant_plan = apply_advice(plan, approved)
                settings = dict(variant_plan.process_settings)
                if objective in {"qualidade", "velocidade"} and "layer_height" in settings:
                    if settings.get("layer_height") == plan.process_settings.get("layer_height"):
                        try:
                            current = float(settings["layer_height"])
                            factor = 0.8 if objective == "qualidade" else 1.2
                            proposed = round(min(max_h, max(min_h, current * factor)), 2)
                            if min_h <= proposed <= max_h:
                                settings["layer_height"] = f"{proposed:g}"
                                variant_plan = replace(variant_plan, process_settings=settings)
                        except (TypeError, ValueError):
                            pass
                allowed = {
                    k: str(v) for k, v in variant_plan.process_settings.items()
                    if plan.process_settings.get(k) != v
                }
        else:
            allowed = {key: value for key, value in changes.items() if key in plan.process_settings}
            if objective in {"qualidade", "velocidade"} and "layer_height" in plan.process_settings:
                try:
                    current = float(plan.process_settings["layer_height"])
                    factor = 0.8 if objective == "qualidade" else 1.2
                    proposed = round(min(max_h, max(min_h, current * factor)), 2)
                    if min_h <= proposed <= max_h:
                        allowed["layer_height"] = f"{proposed:g}"
                except (TypeError, ValueError):
                    pass
            settings = dict(plan.process_settings)
            settings.update(allowed)
            variant_plan = replace(plan, process_settings=settings)

        destination = next_available_destination(destination_dir / f"{project.path.stem}_{objective}.3mf")
        result = convert_project(project, variant_plan, destination, slicer)
        variants.append(Variant(objective, result, allowed))
    return tuple(variants)


def _format_grams(value: float | None) -> str:
    if value is None:
        return "indisponível"
    return f"{value:.2f} g"


def _recommended_objective(variants: tuple[Variant, ...], goal: Any) -> str:
    available = {v.objective for v in variants if v.result.validation and v.result.validation.success}
    priority = getattr(goal, "priority", "equilibrio") if goal else "equilibrio"
    purpose = getattr(goal, "purpose", "nao_sei") if goal else "nao_sei"
    if priority in available:
        return priority
    if purpose == "decorativa" and "qualidade" in available:
        return "qualidade"
    if "equilibrio" in available:
        return "equilibrio"
    if "original" in available:
        return "original"
    return variants[0].objective if variants else "original"


def format_objective_comparison(
    variants: tuple[Variant, ...],
    *,
    goal: Any = None,
    history_records: tuple[Any, ...] | list[Any] = (),
) -> str:
    """Formata todas as alternativas por placa antes de sugerir ponto de partida, sem alegar resistência sem teste."""
    lines = [
        "COMPARAÇÃO DE ALTERNATIVAS (POR PLACA)",
        f"• {evidence_label('verificado_3mf')}: comparação gerada sobre o mesmo projeto convertido (geometria inalterada).",
        f"• {evidence_label('verificado_fatiamento')}: tempos e gramas abaixo foram medidos no G-code real de cada placa:",
    ]

    for item in variants:
        title = OBJECTIVE_TITLES.get(item.objective, item.objective.upper())
        validation = item.result.validation
        changed_txt = ", ".join(f"{k}={v}" for k, v in item.changed.items()) if item.changed else "nenhum (perfil base ELEGOO)"
        lines.extend(["", f"[{title}]"])
        lines.append(f"  Status: {item.result.message}")
        lines.append(f"  Parâmetros alterados: {changed_txt}")
        if validation is not None:
            lines.append(
                f"  Total estimado: {format_duration(validation.estimated_seconds)} · {_format_grams(validation.filament_grams)}"
            )
            plate_metrics = getattr(validation, "plate_metrics", ()) or ()
            for pm in plate_metrics:
                lines.append(
                    f"    - Placa {pm.plate}: {format_duration(pm.estimated_seconds)} · {_format_grams(pm.filament_grams)}"
                )
        else:
            lines.append("  Total estimado: indisponível (sem fatiamento válido)")
        lines.append(f"  Arquivo: {item.result.destination}")

    rec = _recommended_objective(variants, goal)
    rec_display = (
        "Original (original)"
        if rec == "original"
        else f"{priority_label(rec).split(' (')[0]} ({rec})"
    )
    purpose_txt = purpose_label(getattr(goal, "purpose", "nao_sei")) if goal else "Não informado"
    prio_txt = priority_label(getattr(goal, "priority", "equilibrio")) if goal else "Equilíbrio"
    load_code = getattr(goal, "load_type", "nao_sei") if goal else "nao_sei"
    load_txt = load_type_label(load_code)

    lines.extend([
        "",
        f"• {evidence_label('estimado_regra_ia')}: ponto de partida destacado -> {rec_display} "
        f"(alinhado ao objetivo: {purpose_txt} · prioridade: {prio_txt} · carga: {load_txt}).",
        "  Aviso técnico: resistência mecânica não comprovada — mais paredes ou preenchimento alteram massa e tempo, "
        "mas a resistência real depende da orientação da carga em relação às camadas e de ensaio físico.",
    ])

    if load_code == "tracao_eixo_z":
        lines.append(
            "  Direção da carga (Eixo Z): nenhuma variante automática corrige tração perpendicular às camadas; "
            "avalie rotacionar a peça no ELEGOO Slicer para alinhar o esforço no plano XY."
        )
    elif goal and getattr(goal, "purpose", "") == "esforco":
        lines.append(
            f"  Direção da carga considerada ({load_txt}): confira na prévia 3D se a orientação favorece camadas contínuas ao longo do esforço."
        )

    if history_records:
        warping_issues = sum(
            1 for r in history_records
            if getattr(r, "visual_result", "") == "empenou_soltou" or getattr(r, "warped", False) or getattr(r, "detached_bed", False)
        )
        fit_issues = sum(
            1 for r in history_records
            if getattr(r, "visual_result", "") in {"folga_apertada", "articulacao_colou"} or not getattr(r, "fit_ok", True)
        )
        if warping_issues or fit_issues:
            lines.append(
                f"  Histórico local registrado: {warping_issues} ocorrência(s) de empenamento/descolamento e "
                f"{fit_issues} ocorrência(s) de folga/encaixe apertado em impressões anteriores."
            )

    lines.append(
        f"• {evidence_label('depende_teste_fisico')}: Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica. "
        "Compare tempo/gramas entre as 5 variantes acima e valide a escolhida com peça de teste real."
    )
    return "\n".join(lines)

