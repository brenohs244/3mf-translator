"""Lições estruturadas do Professor (o que observei, por que importa, proposta, custo e como conferir)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .labels import (
    criticality_label,
    evidence_label,
    fit_label,
    load_type_label,
    purpose_label,
)
from .mapping import ConversionPlan
from .professor import Advice, PrintGoal, source_material_summary
from .project import ProjectInfo


@dataclass(frozen=True)
class Lesson:
    """Explicação didática derivada exclusivamente dos dados do projeto, perfil e conselhos existentes."""

    observed: str
    reason: str
    proposal: str
    tradeoff: str
    verification: str
    evidence_class: str


_ABS_FAMILY = frozenset({"ABS", "ASA", "PA", "PC"})


def _as_str(val: Any, default: str = "") -> str:
    if isinstance(val, (list, tuple)):
        return str(val[0]) if val else default
    if val is None:
        return default
    return str(val)


def _polymer_prefix(raw: str) -> str:
    upper = raw.strip().upper()
    for base in ("PETG", "TPU", "ASA", "ABS", "PLA", "PA", "PC"):
        if upper.startswith(base):
            return base
    return upper.split("-", 1)[0].split(" ", 1)[0]


def _used_target_cfgs(project: ProjectInfo, plan: ConversionPlan) -> list[tuple[int, dict[str, Any]]]:
    used = {str(s) for s in (getattr(project, "used_filament_slots", ()) or ()) if s and str(s) != "0"}
    cfgs = [
        (idx, cfg)
        for idx, cfg in enumerate(getattr(plan, "filament_settings", ()) or (), start=1)
        if not used or str(idx) in used
    ]
    return cfgs or list(enumerate(getattr(plan, "filament_settings", ()) or (), start=1))


def _advice_to_lesson(adv: Advice) -> Lesson:
    if adv.scope == "alert":
        observed = adv.title
        proposal = f"Revisar ponto de atenção: {adv.title}."
    else:
        observed = f"{adv.title} (valor atual no perfil: {adv.current})"
        proposal = f"Aplicar {adv.key}: {adv.current} → {adv.proposed}."
    return Lesson(
        observed=observed,
        reason=adv.why,
        proposal=proposal,
        tradeoff=adv.expected_effect or "Altera tempo, consumo ou acabamento local sem comprovar resistência física.",
        verification=adv.what_to_check or "Confira o resultado na prévia do ELEGOO Slicer e em peça de teste.",
        evidence_class=adv.evidence_class,
    )


def _build_cooling_mechanism_lesson(
    project: ProjectInfo,
    plan: ConversionPlan,
    advices: tuple[Advice, ...],
) -> Lesson | None:
    target_cfgs = _used_target_cfgs(project, plan)
    sensitive = [
        (idx, cfg, _polymer_prefix(_as_str(cfg.get("filament_type", ""))))
        for idx, cfg in target_cfgs
        if _polymer_prefix(_as_str(cfg.get("filament_type", ""))) in _ABS_FAMILY
    ]
    if not sensitive:
        return None

    idx, cfg, mat = sensitive[0]
    fan_max = _as_str(cfg.get("fan_max_speed", "?"), "?")
    oh_fan = _as_str(cfg.get("overhang_fan_speed", "?"), "?")
    aux_fan = _as_str(cfg.get("additional_cooling_fan_speed", "?"), "?")
    ex_fan = _as_str(cfg.get("during_print_exhaust_fan_speed", "?"), "?")
    chamber_ctrl = _as_str(plan.machine_settings.get("support_chamber_temp_control", "0"), "0")
    cooling_titles = [
        adv.title for adv in advices
        if adv.scope != "alert" and adv.key in {
            "fan_max_speed", "overhang_fan_speed", "additional_cooling_fan_speed",
            "during_print_exhaust_fan_speed", "close_fan_the_first_x_layers", "passive_preheat_seconds",
        }
    ]
    proposal = (
        "Ajustes previstos no perfil ECC2: " + "; ".join(cooling_titles[:4]) + "."
        if cooling_titles else
        f"Manter os limites atuais do perfil ECC2 para {mat} (ventoinha max {fan_max}%, AUX {aux_fan}%) sem aplicar percentual universal."
    )
    return Lesson(
        observed=(
            f"Slot {idx} em {mat} com câmara passiva na Centauri Carbon 2 (controle ativo={chamber_ctrl}): "
            f"ventoinha da peça max {fan_max}% (saliências {oh_fan}%), ventoinha auxiliar lateral {aux_fan}% e exaustão {ex_fan}%."
        ),
        reason=(
            f"Em {mat}, quatro fluxos de ar atuam de formas distintas (mecanismos documentados em guias Prusa/Fillamentum, "
            "sem receita fixa única para todo projeto): (1) a ventoinha da peça reduz deformação em pontes/detalhes finos, mas vento em excesso "
            "esfria a camada anterior e agrava empenamento e separação intercamadas; (2) a ventoinha auxiliar lateral gera jato assimétrico; "
            "(3) a câmara passiva não possui aquecedor ativo — pré-aquecer a mesa ajuda a estabilizar a base inicial, porém não cria câmara "
            "aquecida controlada; (4) a exaustão retira calor e vapores/odor do gabinete para o ambiente."
        ),
        proposal=proposal,
        tradeoff=(
            "Menos vento atenua choque térmico nas camadas, mas pode amolecer pontes e saliências pequenas; "
            "reduzir exaustão retém algo de calor passivo, mas aumenta odor/estireno se o cômodo não tiver ventilação."
        ),
        verification=(
            "Estabilize a máquina fechada, imprima uma peça pequena de teste primeiro, confira cantos da base e avalie coesão "
            "entre camadas fisicamente após esfriar."
        ),
        evidence_class="depende_teste_fisico",
    )


def _build_functional_lesson(
    plan: ConversionPlan,
    goal: PrintGoal,
    advices: tuple[Advice, ...],
) -> Lesson | None:
    if goal.purpose not in {"esforco", "funcional_leve", "externa", "chaveiro_rigido"} and goal.load_type in {"nao_sei", "decorativa"}:
        return None

    proc = plan.process_settings
    walls = _as_str(proc.get("wall_loops", "2"), "2")
    infill = _as_str(proc.get("sparse_infill_density", "15%"), "15%")
    struct_props = [
        f"{adv.key} → {adv.proposed}"
        for adv in advices
        if adv.scope != "alert" and adv.key in {"wall_loops", "top_shell_layers", "bottom_shell_layers", "sparse_infill_density", "sparse_infill_pattern"}
    ]
    if goal.load_type == "tracao_eixo_z":
        extra_z = (
            " Carga informada no eixo Z: forças perpendiculares às camadas concentram tensão na união entre camadas; "
            "aumentar apenas preenchimento não resolve tração em Z."
        )
        prop_z = " Avalie rotacionar a peça no ELEGOO Slicer para alinhar o esforço no plano XY."
    else:
        extra_z = " Aumentar apenas preenchimento não é solução universal; paredes externas absorvem melhor flexão no plano XY."
        prop_z = ""

    return Lesson(
        observed=(
            f"Uso '{purpose_label(goal.purpose)}', direção '{load_type_label(goal.load_type)}', criticidade '{criticality_label(goal.criticality)}'; "
            f"perfil base tem {walls} parede(s) e {infill} de preenchimento. Não sabemos a magnitude da carga (N/kg), ciclos nem temperatura contínua real."
        ),
        reason=(
            "Peças funcionais falham conforme a orientação entre camadas, concentração de tensão em furos/cantos e temperatura de amolecimento do polímero."
            + extra_z
        ),
        proposal=(
            ("Ponto de partida conservador: " + ", ".join(struct_props) + "." if struct_props else "Manter casca estrutural reforçada.")
            + prop_z
        ),
        tradeoff=(
            "Mais paredes e preenchimento elevam massa e tempo de impressão (estimados no fatiador), mas não comprovam suporte a carga nem substituem ensaio real."
        ),
        verification=(
            "Confira a orientação da carga em relação às linhas de camada no fatiador e realize ensaio físico representativo com margem de segurança antes do uso definitivo."
        ),
        evidence_class="depende_teste_fisico",
    )


def _build_clearance_lesson(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
    advices: tuple[Advice, ...],
) -> Lesson | None:
    is_articulated = goal.purpose in {"moveis", "chaveiro_articulado"} or goal.fit_clearance in {"partes_moveis", "encaixe_justo"}
    if not is_articulated:
        return None

    proc = plan.process_settings
    brim = _as_str(proc.get("brim_type", "auto_brim (padrão)"), "auto_brim (padrão)")
    layer_h = _as_str(proc.get("layer_height", "0.2"), "0.2")
    src_mats = source_material_summary(project)["label"]
    dst_mats = "/".join(
        dict.fromkeys(_as_str(cfg.get("filament_type", "?"), "?") for _, cfg in _used_target_cfgs(project, plan))
    )
    has_shrink = any(_polymer_prefix(_as_str(cfg.get("filament_type", ""))) in _ABS_FAMILY for _, cfg in _used_target_cfgs(project, plan))
    shrink_note = (
        f" A troca de {src_mats} para {dst_mats} introduz maior retração térmica após resfriar, alterando folgas projetadas."
        if has_shrink else ""
    )
    props = [
        f"{adv.key}={adv.proposed}" for adv in advices
        if adv.scope != "alert" and (
            adv.key in {"elefant_foot_compensation", "ironing_type", "sparse_infill_pattern"}
            or (adv.key == "brim_type" and adv.proposed == "no_brim")
        )
    ]
    return Lesson(
        observed=(
            f"Projeto exige atenção a folgas/encaixes ({fit_label(goal.fit_clearance)}): perfil traz brim='{brim}' e camada {layer_h} mm.{shrink_note}"
        ),
        reason=(
            "Brim automático/externo e esmagamento da 1ª camada (pé de elefante) costumam fundir elos print-in-place na mesa; "
            "suportes não removíveis dentro de juntas ou contração maior em ABS/ASA podem travar encaixes justos."
        ),
        proposal=(
            ("Ajustes para folga: " + ", ".join(props) + "." if props else "Manter brim desativado e compensação de pé de elefante ativa.")
        ),
        tradeoff=(
            "Sem brim, cantos pequenos ficam mais sensíveis a descolamento (exige placa PEI bem limpa e câmara estabilizada); "
            "folgas reais só são conhecidas após resfriar."
        ),
        verification=(
            "Inspecione as frestas entre partes na prévia da camada 1 e teste movimento/encaixe após resfriamento (use 'Gerar calibração 50 mm' para medir contração)."
        ),
        evidence_class="depende_teste_fisico",
    )


def _build_mixed_use_lesson(project: ProjectInfo, goal: PrintGoal) -> Lesson | None:
    obj_count = len(getattr(project, "objects", ()) or ())
    plate_count = len(getattr(project, "plates", ()) or ())
    if obj_count <= 1 and plate_count <= 1:
        return None
    return Lesson(
        observed=(
            f"O projeto possui {obj_count} objeto(s) em {plate_count} placa(s), avaliados sob um único objetivo global ('{purpose_label(goal.purpose)}')."
        ),
        reason=(
            "Este tradutor não infere a função mecânica de cada objeto pela aparência ou nome da malha: em arquivos com múltiplas peças, "
            "um único objetivo global pode aplicar reforço onde não precisa ou ser insuficiente para o item mais solicitado."
        ),
        proposal=(
            "Use este ajuste global apenas como ponto de partida e revise individualmente cada objeto na aba Objetos do ELEGOO Slicer."
        ),
        tradeoff=(
            "Alterações globais uniformes afetam todas as placas/peças igualmente até que você ajuste overrides específicos."
        ),
        verification=(
            "Abra o arquivo exportado no ELEGOO Slicer, confira a lista de Objetos por placa e confirme paredes/suportes de cada peça separadamente."
        ),
        evidence_class="verificado_3mf",
    )


def _build_decorative_lesson(plan: ConversionPlan, goal: PrintGoal, advices: tuple[Advice, ...]) -> Lesson | None:
    if goal.purpose != "decorativa":
        return None
    proc = plan.process_settings
    layer_h = _as_str(proc.get("layer_height", "0.2"), "0.2")
    sup_on = _as_str(proc.get("enable_support", "0"), "0") == "1"
    sup_z = _as_str(proc.get("support_top_z_distance", "0.2"), "0.2")
    sup_xy = _as_str(proc.get("support_object_xy_distance", "0.5"), "0.5")
    props = [
        f"{adv.key}={adv.proposed}" for adv in advices
        if adv.scope != "alert" and adv.key in {"layer_height", "outer_wall_speed", "seam_position", "wall_generator", "enable_support"}
    ]
    return Lesson(
        observed=(
            f"Peça decorativa em camada {layer_h} mm; suportes {'ativados' if sup_on else 'desativados'} "
            f"com folga Z={sup_z} mm e XY={sup_xy} mm no perfil."
        ),
        reason=(
            "Em peças visuais, altura de camada, posição de costura, velocidade de parede externa e folgas de suporte dominam a aparência "
            "(regras de acabamento, sem qualquer validação estrutural)."
        ),
        proposal=(
            ("Ajustes de acabamento considerados: " + ", ".join(props) + "." if props else "Revisar costura, camada e prévia de suportes no ELEGOO Slicer.")
        ),
        tradeoff=(
            "Camadas menores e parede externa mais lenta suavizam degraus e brilho, aumentando o tempo estimado no fatiador."
        ),
        verification=(
            "Confira marcas de costura, áreas apoiadas por suporte na prévia 3D e inspecione visualmente a peça impressa após remoção dos suportes."
        ),
        evidence_class="estimado_regra_ia",
    )


def build_lessons(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
    advices: tuple[Advice, ...],
) -> tuple[Lesson, ...]:
    """Constrói lições didáticas explicando dados observados, porquê, proposta, custo e conferência."""
    lessons: list[Lesson] = []

    for fn in (
        lambda: _build_cooling_mechanism_lesson(project, plan, advices),
        lambda: _build_functional_lesson(plan, goal, advices),
        lambda: _build_clearance_lesson(project, plan, goal, advices),
        lambda: _build_decorative_lesson(plan, goal, advices),
        lambda: _build_mixed_use_lesson(project, goal),
    ):
        item = fn()
        if item is not None:
            lessons.append(item)

    seen_reasons = {lesson.reason for lesson in lessons}
    for adv in advices:
        if len(lessons) >= 8:
            break
        if adv.why and adv.why not in seen_reasons:
            seen_reasons.add(adv.why)
            lessons.append(_advice_to_lesson(adv))

    return tuple(lessons)


def format_lessons(lessons: tuple[Lesson, ...]) -> str:
    """Formata lições em texto claro com os cinco pontos pedagógicos obrigatórios."""
    if not lessons:
        return ""
    lines = ["LIÇÕES DO PROFESSOR (COMO DECIDIR E CONFERIR):"]
    for idx, lesson in enumerate(lessons, 1):
        lines.extend([
            f"",
            f"{idx}. [{evidence_label(lesson.evidence_class)}]",
            f"   O que observei: {lesson.observed}",
            f"   Por que isso importa: {lesson.reason}",
            f"   O que proponho: {lesson.proposal}",
            f"   Qual o custo / limitação: {lesson.tradeoff}",
            f"   Como conferir: {lesson.verification}",
        ])
    return "\n".join(lines)
