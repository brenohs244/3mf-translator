"""Compara objetivos de impressão usando cópias e fatiamento local."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .advice_policy import enforce_advice_policy
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
    changes_by_scope: dict[str, dict[str, str]] = field(default_factory=dict)


def _first_float(val: object, default: float) -> float:
    if isinstance(val, (list, tuple)):
        val = val[0] if val else default
    try:
        return float(str(val))
    except (TypeError, ValueError):
        return default


def _first_str(val: object) -> str:
    if isinstance(val, (list, tuple)):
        return str(val[0]) if val else ""
    if val is None:
        return ""
    return str(val)


def _diff_plan_changes(base_plan: Any, variant_plan: Any) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    base_proc = getattr(base_plan, "process_settings", {}) or {}
    var_proc = getattr(variant_plan, "process_settings", {}) or {}
    proc_diff = {
        str(k): _first_str(v)
        for k, v in var_proc.items()
        if _first_str(base_proc.get(k)) != _first_str(v)
    }

    fil_diff: dict[str, str] = {}
    base_fils = getattr(base_plan, "filament_settings", ()) or ()
    var_fils = getattr(variant_plan, "filament_settings", ()) or ()
    for idx, (orig_f, new_f) in enumerate(zip(base_fils, var_fils), start=1):
        for k, new_v in (new_f or {}).items():
            new_s = _first_str(new_v)
            if _first_str((orig_f or {}).get(k)) != new_s:
                fil_diff[f"Slot {idx}.{k}"] = new_s

    mach_diff: dict[str, str] = {}
    base_mach = getattr(base_plan, "machine_settings", {}) or {}
    var_mach = getattr(variant_plan, "machine_settings", {}) or {}
    for k, new_v in var_mach.items():
        new_s = _first_str(new_v)
        if _first_str(base_mach.get(k)) != new_s:
            mach_diff[str(k)] = "pré-aquecimento passivo ajustado" if k == "machine_start_gcode" else new_s

    by_scope = {
        scope: diff
        for scope, diff in (("process", proc_diff), ("filament", fil_diff), ("machine", mach_diff))
        if diff
    }
    return proc_diff, by_scope


def compare_objectives(project: ProjectInfo, plan: ConversionPlan, destination_dir: Path,
                       slicer: SlicerCLI, *, goal: PrintGoal | Any = None) -> tuple[Variant, ...]:
    """Fatia variantes separadas sob a política única. Sem métricas válidas, não recomenda."""
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
            else:
                variant_goal = PrintGoal(
                    purpose=getattr(goal, "purpose", "nao_sei"),
                    priority=objective,
                    load_type=getattr(goal, "load_type", "nao_sei"),
                    criticality=getattr(goal, "criticality", "nao_sei"),
                    fit_clearance=getattr(goal, "fit_clearance", "nao_sei"),
                    heat_exposure=getattr(goal, "heat_exposure", "nao_sei"),
                    physical_material=getattr(goal, "physical_material", "nao_sei"),
                    material_mode=getattr(goal, "material_mode", "carregado"),
                )
                advices = advise_offline(project, plan, variant_goal)
                proposals = tuple(adv for adv in advices if adv.scope != "alert" and adv.default_on)
                policy_res = enforce_advice_policy(project, plan, variant_goal, proposals)
                variant_plan = apply_advice(plan, list(policy_res.accepted))
            allowed, by_scope = _diff_plan_changes(plan, variant_plan)
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
            by_scope = {"process": dict(allowed)} if allowed else {}

        destination = next_available_destination(destination_dir / f"{project.path.stem}_{objective}.3mf")
        result = convert_project(project, variant_plan, destination, slicer)
        variants.append(Variant(objective, result, allowed, changes_by_scope=by_scope))
    return tuple(variants)


def _is_finite_metric(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(num) and num >= 0.0


def is_recommendable(variant: Variant) -> bool:
    """Exige sucesso integral da conversão, geometria preservada, fatiamento aprovado e métricas finitas."""
    res = getattr(variant, "result", None)
    if res is None or not getattr(res, "success", False):
        return False
    geom = getattr(res, "geometry", None)
    if geom is not None and not getattr(geom, "unchanged", False):
        return False
    val = getattr(res, "validation", None)
    if val is None or not getattr(val, "success", False):
        return False
    if not (_is_finite_metric(getattr(val, "estimated_seconds", None)) and _is_finite_metric(getattr(val, "filament_grams", None))):
        return False
    plate_metrics = getattr(val, "plate_metrics", ()) or ()
    for pm in plate_metrics:
        if not (_is_finite_metric(getattr(pm, "estimated_seconds", None)) and _is_finite_metric(getattr(pm, "filament_grams", None))):
            return False
    return True


def _format_grams(value: float | None) -> str:
    if not _is_finite_metric(value):
        return "indisponível"
    return f"{float(value):.2f} g"


def _recommended_objective(variants: tuple[Variant, ...], goal: Any) -> str | None:
    eligible = [v.objective for v in variants if is_recommendable(v)]
    if not eligible:
        return None
    available = set(eligible)
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
    return eligible[0]


def _variant_signature(variant: Variant) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    if variant.changes_by_scope:
        return tuple(
            (scope, tuple(sorted(entries.items())))
            for scope, entries in sorted(variant.changes_by_scope.items())
            if entries
        )
    if variant.changed:
        return (("process", tuple(sorted(variant.changed.items()))),)
    return ()


def _format_variant_changes(variant: Variant) -> str:
    if variant.changes_by_scope:
        scope_names = {"process": "processo", "filament": "filamento", "machine": "máquina"}
        parts: list[str] = []
        for scope in ("process", "filament", "machine"):
            entries = variant.changes_by_scope.get(scope)
            if entries:
                joined = ", ".join(f"{k}={v}" for k, v in entries.items())
                parts.append(f"{scope_names[scope]}: {joined}")
        if parts:
            return " | ".join(parts)
    if variant.changed:
        return ", ".join(f"{k}={v}" for k, v in variant.changed.items())
    return "nenhum (perfil base ELEGOO)"


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
        f"• {evidence_label('verificado_fatiamento')}: tempos e gramas abaixo são estimativas do fatiador geradas a partir do G-code de cada placa (não medições físicas de impressão):",
    ]

    seen_signatures: dict[tuple, str] = {}
    for item in variants:
        sig = _variant_signature(item)
        duplicate_of = seen_signatures.get(sig)
        if duplicate_of is None:
            seen_signatures[sig] = item.objective

        title = OBJECTIVE_TITLES.get(item.objective, item.objective.upper())
        validation = item.result.validation
        changed_txt = _format_variant_changes(item)
        eligible = is_recommendable(item)
        lines.extend(["", f"[{title}]"])
        lines.append(f"  Status: {item.result.message}")
        lines.append(f"  Parâmetros alterados: {changed_txt}")
        if duplicate_of is not None:
            lines.append(
                f"  Observação: parâmetros efetivos idênticos à alternativa '{duplicate_of}' "
                "pelas restrições de perfil/política — sem diferença real esperada entre elas."
            )
        if eligible and validation is not None:
            lines.append(
                f"  Total estimado (slicer): {format_duration(validation.estimated_seconds)} · {_format_grams(validation.filament_grams)}"
            )
            plate_metrics = getattr(validation, "plate_metrics", ()) or ()
            for pm in plate_metrics:
                lines.append(
                    f"    - Placa {pm.plate} (estimativa): {format_duration(pm.estimated_seconds)} · {_format_grams(pm.filament_grams)}"
                )
        else:
            geom = getattr(item.result, "geometry", None)
            if geom is not None and not getattr(geom, "unchanged", True):
                reason = "geometria alterada após conversão"
            elif validation is None or not getattr(validation, "success", False):
                reason = "sem fatiamento válido"
            else:
                reason = "métricas ausentes ou não finitas no fatiamento"
            lines.append(f"  Total estimado: indisponível (não elegível para comparação — {reason})")
        lines.append(f"  Arquivo: {item.result.destination}")

    rec = _recommended_objective(variants, goal)
    purpose_txt = purpose_label(getattr(goal, "purpose", "nao_sei")) if goal else "Não informado"
    prio_txt = priority_label(getattr(goal, "priority", "equilibrio")) if goal else "Equilíbrio"
    load_code = getattr(goal, "load_type", "nao_sei") if goal else "nao_sei"
    load_txt = load_type_label(load_code)

    if rec is None:
        lines.extend([
            "",
            f"• {evidence_label('estimado_regra_ia')}: Nenhuma alternativa validada — todas as variantes falharam, "
            "tiveram geometria alterada ou ficaram sem estimativas válidas do fatiador.",
        ])
    else:
        rec_display = (
            "Original (original)"
            if rec == "original"
            else f"{priority_label(rec).split(' (')[0]} ({rec})"
        )
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

