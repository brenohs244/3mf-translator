"""Motor determinístico, limites de segurança e diagnóstico didático do Professor de Impressão."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any

from .labels import (
    confidence_label,
    criticality_label,
    evidence_label,
    fit_label,
    heat_exposure_label,
    load_type_label,
    priority_label,
    purpose_label,
)
from .mapping import ConversionPlan
from .project import ProjectInfo

PURPOSES = (
    "decorativa",
    "funcional_leve",
    "esforco",
    "moveis",
    "externa",
    "chaveiro_rigido",
    "chaveiro_articulado",
    "nao_sei",
)
PRIORITIES = ("qualidade", "equilibrio", "velocidade", "economia")
LOAD_TYPES = ("nao_sei", "decorativa", "flexao_lateral", "tracao_eixo_z", "compressao", "impacto")
CRITICALITIES = ("nao_sei", "baixa", "media", "alta")
FIT_CLEARANCES = ("nao_sei", "sem_encaixe", "encaixe_justo", "partes_moveis")
HEAT_EXPOSURES = ("nao_sei", "interno", "calor_sol", "agua_externo")
EVIDENCE_CLASSES = (
    "verificado_3mf",
    "verificado_fatiamento",
    "estimado_regra_ia",
    "depende_teste_fisico",
)

SAFE_PROCESS_KEYS = {
    "wall_loops",
    "wall_generator",
    "top_shell_layers",
    "bottom_shell_layers",
    "sparse_infill_density",
    "sparse_infill_pattern",
    "layer_height",
    "brim_type",
    "brim_width",
    "outer_wall_speed",
    "inner_wall_speed",
    "top_surface_speed",
    "seam_position",
    "ironing_type",
    "support_style",
    "support_top_z_distance",
    "elefant_foot_compensation",
}

SAFE_FILAMENT_KEYS = {
    "fan_max_speed",
    "fan_min_speed",
    "overhang_fan_speed",
    "additional_cooling_fan_speed",
    "during_print_exhaust_fan_speed",
}


@dataclass(frozen=True)
class PrintGoal:
    purpose: str
    priority: str
    load_type: str = "nao_sei"
    criticality: str = "nao_sei"
    fit_clearance: str = "nao_sei"
    heat_exposure: str = "nao_sei"
    physical_material: str = "nao_sei"


@dataclass(frozen=True)
class Advice:
    scope: str            # "process" | "filament" | "alert"
    slot: int | None      # 1-based para filament
    key: str              # Chave de configuração (vazio para alertas gerais)
    current: str
    proposed: str
    title: str
    why: str
    default_on: bool
    expected_effect: str = ""
    what_to_check: str = ""
    evidence_class: str = "estimado_regra_ia"
    requires_physical_test: bool = False
    confidence: str = "media"


def _as_str(val: Any) -> str:
    if isinstance(val, (list, tuple)):
        return str(val[0]) if val else ""
    return "" if val is None else str(val)


def _as_int(val: Any, default: int) -> int:
    try:
        return int(float(_as_str(val)))
    except (TypeError, ValueError):
        return default


def _as_float(val: Any, default: float) -> float:
    try:
        return float(_as_str(val).rstrip("%"))
    except (TypeError, ValueError):
        return default


def _base_polymer(material: str) -> str:
    upper = (material or "").strip().upper()
    if not upper:
        return "DESCONHECIDO"
    for polymer in ("PETG", "PLA", "ASA", "ABS", "TPU", "PA", "PC"):
        if re.search(rf"(?<![A-Z]){polymer}(?![A-Z])", upper):
            return polymer
    return upper.split()[0]


def _is_abs_asa_material(material: str) -> bool:
    return _base_polymer(material) in {"ABS", "ASA"}


def _is_composite_material(material: str) -> bool:
    upper = (material or "").upper()
    return any(tag in upper for tag in ("-CF", "-GF", " CF", " GF", "CARBON"))


def source_material_summary(project: ProjectInfo) -> dict[str, Any]:
    """Classifica materiais declarados apenas nos slots efetivamente usados no projeto."""
    used_slots = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    filaments = [
        f for f in getattr(project, "filaments", ())
        if not used_slots or str(f.slot) in used_slots
    ] or list(getattr(project, "filaments", ()))
    raw_names = [f.material.strip() or "Desconhecido" for f in filaments]
    polymers = [_base_polymer(name) for name in raw_names]
    unique_polymers = list(dict.fromkeys(polymers))
    label = " + ".join(dict.fromkeys(raw_names)) if raw_names else "Desconhecido"
    return {
        "used_materials": raw_names,
        "base_polymers": unique_polymers,
        "has_pla": "PLA" in unique_polymers,
        "has_petg": "PETG" in unique_polymers,
        "has_abs_asa": any(p in {"ABS", "ASA"} for p in unique_polymers),
        "is_mixed": len(unique_polymers) > 1,
        "label": label,
    }


def goal_confidence(goal: PrintGoal) -> tuple[str, list[str]]:
    """Calcula nível de confiança da recomendação e lista lacunas ('Não sei')."""
    reasons: list[str] = []
    if goal.purpose == "nao_sei":
        reasons.append("Uso principal da peça não foi informado ('Não sei').")
    if goal.physical_material in {"", "nao_sei"}:
        reasons.append("Filamento físico carregado na impressora não foi explicitamente confirmado.")

    needs_mechanics = goal.purpose in {
        "funcional_leve", "esforco", "moveis", "externa", "chaveiro_rigido", "chaveiro_articulado", "nao_sei"
    }
    if needs_mechanics:
        if goal.load_type == "nao_sei":
            reasons.append("Direção/tipo da carga mecânica está em 'Não sei'.")
        if goal.criticality == "nao_sei":
            reasons.append("Criticidade da falha está em 'Não sei'.")
        if goal.fit_clearance == "nao_sei":
            reasons.append("Existência de encaixes ou folgas está em 'Não sei'.")
        if goal.heat_exposure == "nao_sei":
            reasons.append("Exposição a calor/sol/umidade está em 'Não sei'.")

    if goal.purpose == "nao_sei" or len(reasons) >= 2:
        return "baixa", reasons
    if len(reasons) == 1:
        return "media", reasons
    return "alta", reasons


def validate_change(scope: str, key: str, value: str, plan: ConversionPlan, slot: int | None = None) -> bool:
    if scope == "process":
        # brim_type pode estar ausente do JSON base (ELEGOO usa auto_brim implícito), mas é chave válida do fatiador.
        if key not in SAFE_PROCESS_KEYS or (key != "brim_type" and key not in plan.process_settings):
            return False
        if key == "wall_loops":
            return value.isdigit() and 1 <= int(value) <= 8
        if key == "wall_generator":
            return value in {"classic", "arachne"}
        if key in {"top_shell_layers", "bottom_shell_layers"}:
            return value.isdigit() and 0 <= int(value) <= 12
        if key == "sparse_infill_density":
            if not value.endswith("%"):
                return False
            try:
                num = float(value[:-1])
                return math.isfinite(num) and 0 <= num <= 100
            except ValueError:
                return False
        if key == "sparse_infill_pattern":
            return value in {"gyroid", "rectilinear", "grid", "cubic"}
        if key == "layer_height":
            try:
                h = float(value)
                min_h = float(_as_str(plan.machine_settings.get("min_layer_height", "0.08")))
                max_h = float(_as_str(plan.machine_settings.get("max_layer_height", "0.28")))
                nozzle = float(_as_str(plan.machine_settings.get("nozzle_diameter", "0.4")))
                return math.isfinite(h) and min_h <= h <= max_h and h <= nozzle * 0.75
            except ValueError:
                return False
        if key == "brim_type":
            return value in {"auto_brim", "outer_only", "no_brim"}
        if key == "brim_width":
            try:
                w = float(value)
                return math.isfinite(w) and 0 <= w <= 15
            except ValueError:
                return False
        if key in {"outer_wall_speed", "inner_wall_speed", "top_surface_speed"}:
            try:
                spd = float(value)
                default = "160" if key == "outer_wall_speed" else "200"
                orig = float(_as_str(plan.process_settings.get(key, default)))
                return math.isfinite(spd) and 30 <= spd <= orig
            except ValueError:
                return False
        if key == "seam_position":
            return value in {"aligned", "back", "nearest", "random"}
        if key == "ironing_type":
            return value in {"no ironing", "top"}
        if key == "support_style":
            return value in {
                "default", "grid", "snug",
                "tree_auto", "tree_slim", "tree_strong", "tree_hybrid", "organic",
            }
        if key == "support_top_z_distance":
            try:
                dist = float(value)
                nozzle = float(_as_str(plan.machine_settings.get("nozzle_diameter", "0.4")))
                return math.isfinite(dist) and 0.08 <= dist <= min(0.28, round(0.75 * nozzle + 1e-6, 4))
            except ValueError:
                return False
        if key == "elefant_foot_compensation":
            try:
                comp = float(value)
                return math.isfinite(comp) and 0.0 <= comp <= 0.4
            except ValueError:
                return False
        return True

    if scope == "filament":
        if slot is None or slot < 1 or slot > len(plan.filament_settings):
            return False
        cfg = plan.filament_settings[slot - 1]
        if key not in SAFE_FILAMENT_KEYS or key not in cfg:
            return False
        try:
            val_int = int(value)
            orig_int = int(_as_str(cfg.get(key, "100")))
            if key == "fan_max_speed" and "fan_min_speed" in cfg:
                min_fan = _as_int(cfg.get("fan_min_speed", "0"), 0)
                if val_int < min_fan:
                    return False
            return 0 <= val_int <= orig_int
        except ValueError:
            return False

    return False


def _add_if_valid(advices: list[Advice], adv: Advice, plan: ConversionPlan) -> None:
    if adv.scope == "alert" or validate_change(adv.scope, adv.key, adv.proposed, plan, slot=adv.slot):
        advices.append(adv)


def _consolidate_advices(advices: list[Advice]) -> list[Advice]:
    """Remove sugestões duplicadas sobre a mesma chave mantendo a vencedora."""
    latest_by_key: dict[tuple[str, int | None, str], Advice] = {}
    for adv in advices:
        if adv.scope != "alert":
            latest_by_key[(adv.scope, adv.slot, adv.key)] = adv
    seen_keys: set[tuple[str, int | None, str]] = set()
    consolidated: list[Advice] = []
    for adv in advices:
        if adv.scope == "alert":
            consolidated.append(adv)
            continue
        identity = (adv.scope, adv.slot, adv.key)
        if identity in seen_keys:
            continue
        seen_keys.add(identity)
        consolidated.append(latest_by_key[identity])
    return consolidated


def _effective_object_support(project: ProjectInfo, proc: dict) -> tuple[bool, bool, str]:
    overrides = getattr(project, "object_overrides", ()) or ()
    obj_enabled = any(o.settings.get("enable_support") == "1" for o in overrides)
    global_enabled = _as_str(proc.get("enable_support", "0")) == "1"
    obj_types = [o.settings.get("support_type", "") for o in overrides if o.settings.get("support_type")]
    support_type = _as_str(proc.get("support_type")) or (obj_types[0] if obj_types else "")
    return (global_enabled or obj_enabled), obj_enabled and not global_enabled, support_type


def _min_effective_int(project: ProjectInfo, proc: dict, key: str, default: int) -> int:
    val = _as_int(proc.get(key, default), default)
    for o in getattr(project, "object_overrides", ()) or ():
        if key in o.settings:
            val = min(val, _as_int(o.settings[key], val))
    return val


def _min_effective_float(project: ProjectInfo, proc: dict, key: str, default: float) -> float:
    val = _as_float(proc.get(key, default), default)
    for o in getattr(project, "object_overrides", ()) or ():
        if key in o.settings:
            val = min(val, _as_float(o.settings[key], val))
    return val


def _propose_speed_cap(
    plan: ConversionPlan,
    key: str,
    limit: float,
    title: str,
    why: str,
    advices: list[Advice],
    *,
    expected_effect: str = "Reduzir variação de vazão e vibrações na superfície externa.",
    what_to_check: str = "Inspecione a peça impressa quanto a marcas horizontais ou falhas de preenchimento.",
    confidence: str = "media",
) -> None:
    proc = plan.process_settings
    if key not in proc:
        return
    cur = _as_float(proc.get(key), limit + 1)
    if cur > limit:
        _add_if_valid(
            advices,
            Advice(
                scope="process", slot=None, key=key,
                current=f"{cur:g}", proposed=f"{limit:g}",
                title=title, why=why, default_on=True,
                expected_effect=expected_effect,
                what_to_check=what_to_check,
                evidence_class="estimado_regra_ia",
                requires_physical_test=False,
                confidence=confidence,
            ),
            plan,
        )


def build_abs_asa_checklist(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
) -> list[str]:
    """Gera o checklist de 6 pontos para troca em direção a ABS/ASA na Centauri Carbon 2."""
    src_info = source_material_summary(project)
    src_label = src_info["label"]
    used_slots = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    abs_cfgs = [
        cfg for idx, cfg in enumerate(plan.filament_settings, 1)
        if (not used_slots or str(idx) in used_slots)
        and _is_abs_asa_material(_as_str(cfg.get("filament_type", "")))
    ] or list(plan.filament_settings)

    dst_mats = "/".join(dict.fromkeys(_as_str(c.get("filament_type", "ABS")) for c in abs_cfgs))
    raw_nozzle = "/".join(dict.fromkeys(_as_str(c.get("nozzle_temperature")) for c in abs_cfgs if _as_str(c.get("nozzle_temperature"))))
    raw_bed = "/".join(dict.fromkeys(_as_str(c.get("textured_plate_temp")) for c in abs_cfgs if _as_str(c.get("textured_plate_temp"))))
    nozzle_temps = f"{raw_nozzle} °C" if raw_nozzle else "padrão do perfil ELEGOO"
    bed_temps = f"{raw_bed} °C" if raw_bed else "padrão do perfil ELEGOO"
    fan_max = "/".join(dict.fromkeys(_as_str(c.get("fan_max_speed")) for c in abs_cfgs if _as_str(c.get("fan_max_speed"))))
    fan_txt = f"{fan_max}%" if fan_max else "padrão ELEGOO"
    exhaust = "/".join(dict.fromkeys(_as_str(c.get("during_print_exhaust_fan_speed", "70")) for c in abs_cfgs))
    chamber_ctrl = _as_str(plan.machine_settings.get("support_chamber_temp_control", "0"))
    src_nozzle = _as_str(project.source_settings.get("nozzle_temperature"))
    src_bed = _as_str(project.source_settings.get("textured_plate_temp"))
    src_nozzle_txt = f"{src_nozzle} °C" if src_nozzle else "n/d"
    src_bed_txt = f"{src_bed} °C" if src_bed else "n/d"

    return [
        (
            f"1. Contração e folgas ({src_label} → {dst_mats}): ABS/ASA costuma contrair na faixa típica de ~0,4%–0,8% "
            "(varia por marca/cor/geometria). Roscas, pinos e encaixes justos exigem peça de teste dimensional antes do lote."
        ),
        (
            "2. Empenamento (warping): cantos extensos ou peças altas podem levantar na base ao resfriar rápido; "
            "avalie brim externo ou abas (rabbit ears) apenas se não encostarem em articulações print-in-place."
        ),
        (
            f"3. Adesão à mesa: perfil ELEGOO selecionado parte de {bed_temps} na mesa texturizada PEI "
            "(confirme a faixa impressa no carretel do fabricante). Lave a placa PEI com detergente neutro ou limpe antes de iniciar."
        ),
        (
            f"4. Temperatura do material/perfil: origem indicava bico {src_nozzle_txt} / mesa {src_bed_txt}; "
            f"o perfil ELEGOO selecionado define bico {nozzle_temps} / mesa {bed_temps} como ponto de partida "
            "(este aplicativo não altera temperaturas automaticamente)."
        ),
        (
            f"5. Ambiente e câmara (controle ativo = {chamber_ctrl}): a Centauri Carbon 2 opera com câmara passiva "
            "(o software não mede a temperatura real interna). Feche porta e tampa superior, evite correntes de ar e "
            "pré-aqueça a mesa antes de iniciar."
        ),
        (
            f"6. Ventilação da peça ({fan_txt}) × Exaustão do ambiente ({exhaust}% → opcional 30%): "
            "a ventoinha da peça atua sobre o plástico depositado (menos fluxo tende a ajudar coesão entre camadas, mas "
            "aumenta risco de queda em saliências >45°); já a exaustão da câmara troca calor/vapores com o cômodo — "
            "reduzi-la busca reter calor passivo, porém eleva o odor/emissão de estireno no local (use apenas em ambiente bem ventilado)."
        ),
    ]


def advise_offline(project: ProjectInfo, plan: ConversionPlan, goal: PrintGoal) -> list[Advice]:
    advices: list[Advice] = []
    proc = plan.process_settings
    effective_support, obj_only_support, effective_support_type = _effective_object_support(project, proc)
    conf, conf_reasons = goal_confidence(goal)

    src_info = source_material_summary(project)
    used_slots_set = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    used_target_cfgs = [
        (idx, cfg) for idx, cfg in enumerate(plan.filament_settings, 1)
        if not used_slots_set or str(idx) in used_slots_set
    ] or list(enumerate(plan.filament_settings, 1))

    abs_slots = [
        (idx, cfg) for idx, cfg in used_target_cfgs
        if _is_abs_asa_material(_as_str(cfg.get("filament_type", "")))
    ]
    is_abs_asa = bool(abs_slots)
    is_composite_abs = all(_is_composite_material(_as_str(cfg.get("filament_type", ""))) for _, cfg in abs_slots) if abs_slots else False
    geom = getattr(project, "geometry_summary", None)
    has_heavy_overhang = bool(geom is not None and getattr(geom, "overhang_mm2", 0.0) >= 250.0)

    # 0. Alerta de confiança quando houver itens em 'Não sei'
    if conf_reasons:
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title=f"Confiança da recomendação: {confidence_label(conf).split(' (')[0]}",
            why=" ".join(conf_reasons),
            expected_effect="Informar que faltam dados do uso real; ajustes críticos permanecem dependentes de conferência.",
            what_to_check="Preencha carga, criticidade, encaixes, calor e filamento físico ou valide em peça de teste.",
            evidence_class="estimado_regra_ia",
            requires_physical_test=(conf == "baixa"),
            confidence=conf,
            default_on=False,
        ))

    # 1. Ajustes por Material (compatíveis com perfil e geometria, sem promessas absolutas)
    if is_abs_asa:
        for idx, cfg in abs_slots:
            mat = _as_str(cfg.get("filament_type", ""))
            min_fan = _as_int(cfg.get("fan_min_speed", "10"), 10)
            floor_fan = max(min_fan, 15)
            cur_fan = _as_int(cfg.get("fan_max_speed", "40"), 40)
            desired_fan = 25 if goal.purpose in {"esforco", "funcional_leve"} else 35
            target_fan = max(floor_fan, desired_fan)
            if "fan_max_speed" in cfg and cur_fan > target_fan:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="filament", slot=idx, key="fan_max_speed",
                        current=str(cur_fan), proposed=str(target_fan),
                        title=f"Reduzir teto de ventoinha da peça (Filamento {idx} - {mat})",
                        why=(
                            f"O perfil inicia com {cur_fan}% (mínimo do perfil {min_fan}%). Resfriamento forte no ABS/ASA "
                            "costuma agravar empenamento e perda de coesão entre camadas; a redução busca equilíbrio sem violar o mínimo do perfil."
                        ),
                        expected_effect="Menor choque térmico na peça; não substitui câmara aquecida nem comprova união sem teste.",
                        what_to_check="Observe pontes e saliências na prévia e em peça de teste quanto a deformação por calor.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )

            cur_overhang = _as_int(cfg.get("overhang_fan_speed", "80"), 80)
            base_oh = 40 if goal.purpose in {"esforco", "funcional_leve"} else 50
            if has_heavy_overhang:
                base_oh = max(base_oh, 55)
            target_overhang = max(min_fan, base_oh)
            if "overhang_fan_speed" in cfg and cur_overhang > target_overhang:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="filament", slot=idx, key="overhang_fan_speed",
                        current=str(cur_overhang), proposed=str(target_overhang),
                        title=f"Moderar ventoinha em saliências (Filamento {idx} - {mat})",
                        why=(
                            f"Reduz de {cur_overhang}% para {target_overhang}% considerando área inclinada >45° "
                            "(conflito direto: mais vento ajuda saliências a não caírem, mas resfria bruscamente o ABS/ASA e pode fragilizar a união local)."
                        ),
                        expected_effect="Atenuar choque térmico em saliências tentando manter apoio mínimo em pontes.",
                        what_to_check="Confira as regiões em balanço (>45°) após imprimir; ajuste na aba do filamento se houver queda.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=True,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )

            cur_aux = _as_int(cfg.get("additional_cooling_fan_speed", "0"), 0)
            if "additional_cooling_fan_speed" in cfg and cur_aux > 0:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="filament", slot=idx, key="additional_cooling_fan_speed",
                        current=str(cur_aux), proposed="0",
                        title=f"Desligar ventoinha auxiliar lateral (Filamento {idx})",
                        why="Jato de ar lateral cria resfriamento assimétrico forte, associado a empenamento e separação de camadas em ABS/ASA.",
                        expected_effect="Reduzir corrente de ar lateral dentro da câmara passiva.",
                        what_to_check="Confirme na visualização de G-code/prévia que o perfil não religa a ventoinha auxiliar.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )

            cur_ex = _as_int(cfg.get("during_print_exhaust_fan_speed", "70"), 70)
            if "during_print_exhaust_fan_speed" in cfg and cur_ex > 30:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="filament", slot=idx, key="during_print_exhaust_fan_speed",
                        current=str(cur_ex), proposed="30",
                        title=f"Opcional: reduzir exaustão do gabinete para 30% (Filamento {idx})",
                        why=(
                            "Diferente da ventoinha da peça, a exaustão retira ar quente e vapores da impressora para o cômodo. "
                            "Reduzir para 30% ajuda a reter calor passivo, MAS aumenta o odor e vapores de estireno no ambiente."
                        ),
                        expected_effect="Maior retenção de calor na câmara passiva com maior liberação de vapores se não houver duto/ventilação.",
                        what_to_check="Ative apenas se o local tiver boa ventilação externa/filtragem e respeite orientações de segurança.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=True,
                        confidence=conf,
                        default_on=False,
                    ),
                    plan,
                )

        # Conflito explícito Brim vs Articulações / Encaixes
        is_articulated = goal.purpose in {"moveis", "chaveiro_articulado"} or goal.fit_clearance == "partes_moveis"
        raw_brim = proc.get("brim_type")
        if is_articulated:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Conflito: Brim no ABS vs. Articulações",
                why=(
                    "O ABS tende a empenar sem borda (brim), porém a borda externa funde folgas e articulações print-in-place na 1ª camada. "
                    "O Brim externo não foi ativado por padrão."
                ),
                expected_effect="Preservar frestas livres entre elos, aceitando maior sensibilidade a descolamento sem câmara bem pré-aquecida.",
                what_to_check="Pré-aqueça a mesa, limpe a placa PEI e, se algum canto levantar em teste, adicione apenas orelhas (mouse ears) pontuais no Slicer.",
                evidence_class="depende_teste_fisico",
                requires_physical_test=True,
                confidence=conf,
                default_on=False,
            ))
        elif not is_composite_abs:
            fit_warn = (
                " Como há encaixe justo informado, confira e rebarbe a base caso o brim deixe resíduo na borda."
                if goal.fit_clearance == "encaixe_justo"
                else ""
            )
            if raw_brim != "outer_only":
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="brim_type",
                        current=str(raw_brim or "auto_brim (padrão)"), proposed="outer_only",
                        title="Ativar Brim Externo (Borda)",
                        why=f"Ajuda a conter o levantamento de cantos por contração térmica em ABS/ASA na câmara passiva.{fit_warn}",
                        expected_effect="Aumentar área de ancoragem periférica na 1ª camada (adiciona acabamento manual de rebarba na borda).",
                        what_to_check="Veja na prévia da 1ª camada se o brim não fecha furos funcionais ou encaixes inferiores.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            if "brim_width" in proc and _as_float(proc.get("brim_width", "5"), 5.0) < 5.0:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="brim_width",
                        current=str(proc.get("brim_width")), proposed="5",
                        title="Largura do Brim em 5 mm",
                        why="Borda estreita costuma soltar antes de segurar cantos extensos em ABS/ASA.",
                        expected_effect="Ampliar faixa de contato perimetral sem alterar o modelo.",
                        what_to_check="Verifique se cabe dentro da área útil da mesa após fatiamento.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )

        # Velocidade ajustada à prioridade sem prometer adesão mecânica
        outer_cap = 80.0 if goal.priority == "qualidade" else (120.0 if goal.priority == "velocidade" else 100.0)
        inner_cap = 120.0 if goal.priority == "qualidade" else (160.0 if goal.priority == "velocidade" else 150.0)
        _propose_speed_cap(
            plan, "outer_wall_speed", outer_cap,
            f"Moderar Velocidade Externa para ABS/ASA ({outer_cap:g} mm/s)",
            "Velocidades de PLA (160–200 mm/s) com pouca ventoinha tendem a piorar marcas e variação de extrusão em ABS/ASA.",
            advices,
            expected_effect="Aumentar tempo de contato térmico por cordão e suavizar cantos externos (aumenta tempo de impressão).",
            what_to_check="Avalie superfície externa e adesão intercamadas em uma peça de teste.",
            confidence=conf,
        )
        _propose_speed_cap(
            plan, "inner_wall_speed", inner_cap,
            f"Moderar Velocidade Interna para ABS/ASA ({inner_cap:g} mm/s)",
            "Mantém vazão volumétrica mais estável do perfil ELEGOO antes de transições de parede.",
            advices,
            expected_effect="Reduzir variação brusca de fluxo volumétrico entre núcleo e casca.",
            what_to_check="Confira no fatiamento se o tempo total permanece aceitável.",
            confidence=conf,
        )

        # Reforço de ponto de partida para ABS/ASA em peças não decorativas
        if goal.purpose != "decorativa":
            cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
            if "wall_loops" in proc and cur_walls < 3:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="wall_loops",
                        current=str(cur_walls), proposed="3",
                        title="Reforço Inicial de Paredes para ABS/ASA (≥ 3)",
                        why="Em câmara passiva, 3 perímetros ajudam a reter calor local e dar margem estrutural em relação a perfis padrão de PLA (não substitui orientação correta da carga).",
                        expected_effect="Aumentar espessura de casca e consumo de filamento; resistência real depende da direção do esforço e ensaio físico.",
                        what_to_check="Confirme o tempo/peso no fatiamento e teste a resistência na direção real de uso.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
            if "top_shell_layers" in proc and cur_top < 4:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="top_shell_layers",
                        current=str(cur_top), proposed="4",
                        title="Aumentar Camadas de Topo para ABS/ASA (≥ 4)",
                        why="Com menos ventoinha no ABS/ASA, pontes internas sobre o preenchimento podem afundar com poucas camadas superiores.",
                        expected_effect="Melhor fechamento de topos planos sobre o núcleo.",
                        what_to_check="Inspecione visualmente as superfícies horizontais superiores após imprimir.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            cur_infill = proc.get("sparse_infill_density", "15%")
            if "sparse_infill_density" in proc and _as_float(cur_infill, 15.0) < 20.0:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="sparse_infill_density",
                        current=str(cur_infill), proposed="20%",
                        title="Preenchimento Inicial 20% para ABS/ASA",
                        why="Aumenta pontos de apoio interno sem excesso de massa; em ABS, tensões de resfriamento pedem núcleo mais contínuo.",
                        expected_effect="Maior sustentação interna para o fechamento superior (maior tempo/material).",
                        what_to_check="Compare tempo e gramas antes de fatiar o lote completo.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            cur_pattern = proc.get("sparse_infill_pattern", "rectilinear")
            if "sparse_infill_pattern" in proc and cur_pattern != "gyroid":
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="sparse_infill_pattern",
                        current=str(cur_pattern), proposed="gyroid",
                        title="Padrão Gyroid para ABS/ASA",
                        why="Ondulação contínua sem cruzamentos na mesma camada evita colisão do bico comum no padrão grid durante contração.",
                        expected_effect="Menor risco de arrasto de bico no núcleo interno.",
                        what_to_check="Confira o desenho interno na prévia por camada.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )

        # Alerta específico de ambiente/câmara e de contração diferenciando PLA, PETG e Mista
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Câmara Passiva e Ambiente para ABS/ASA",
            why=(
                "A Centauri Carbon 2 possui câmara passiva (support_chamber_temp_control = 0) e este software não mede a temperatura real interna. "
                "Mantenha porta/tampa fechadas, mesa no valor do perfil ELEGOO (ou fabricante) e pré-aqueça antes de iniciar."
            ),
            expected_effect="Estabilizar gradiente térmico passivo durante a impressão.",
            what_to_check="Valide a aderência nas primeiras camadas e monitore cantos grandes.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

        has_shrink_context = (
            goal.purpose in {"moveis", "chaveiro_articulado"}
            or goal.fit_clearance in {"encaixe_justo", "partes_moveis"}
        )
        if has_shrink_context and (src_info["has_pla"] or src_info["has_petg"]):
            if src_info["is_mixed"]:
                origin_tag = "Misto PLA/PETG → ABS/ASA"
                origin_msg = "O projeto original mistura materiais distintos (" + src_info["label"] + ")."
            elif src_info["has_pla"]:
                origin_tag = "PLA → ABS/ASA"
                origin_msg = "O projeto original foi configurado para PLA."
            else:
                origin_tag = "PETG → ABS/ASA"
                origin_msg = (
                    "O projeto original foi configurado para PETG (menor contração e maior ductilidade que ABS/ASA)."
                )
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title=f"Atenção: Contração de Encaixes ({origin_tag})",
                why=(
                    f"{origin_msg} O ABS/ASA normalmente contrai cerca de 0,4%–0,8% ao esfriar (varia conforme fabricante), "
                    "podendo apertar pinos, roscas e folgas de movimento."
                ),
                expected_effect="Evitar inutilização de montagem por tolerância dimensional alterada.",
                what_to_check="Imprima primeiro um pino/anel de teste e confira o encaixe físico antes da peça inteira.",
                evidence_class="depende_teste_fisico",
                requires_physical_test=True,
                confidence=conf,
                default_on=False,
            ))

    # 2. Ajustes por Uso Real da Peça
    if goal.purpose == "esforco":
        cur_walls = _min_effective_int(project, proc, "wall_loops", 2)
        if "wall_loops" in proc and cur_walls < 4:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="4",
                    title="Aumentar Paredes Perimétricas (≥ 4)",
                    why="A casca perimetral contribui diretamente para rigidez local no plano das camadas; sozinha, porém, não comprova resistência mecânica.",
                    expected_effect="Elevar espessura da parede externa com acréscimo de tempo e filamento.",
                    what_to_check="Confirme a orientação em relação à força e faça ensaio físico na peça pronta.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_top = _min_effective_int(project, proc, "top_shell_layers", 5)
        if "top_shell_layers" in proc and cur_top < 5:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="top_shell_layers",
                    current=str(cur_top), proposed="5",
                    title="Reforçar Camadas de Topo (5)",
                    why="Amplia a espessura das faces horizontais sob contato ou apoio (resultado mecânico real depende de ensaio).",
                    expected_effect="Superfície superior mais espessa contra perfuração ou amassamento leve.",
                    what_to_check="Revise na prévia se a altura total de casca não conflita com furos rasos.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        infill_num = _min_effective_float(project, proc, "sparse_infill_density", 15.0)
        if "sparse_infill_density" in proc and infill_num < 30.0:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_density",
                    current=f"{infill_num:g}%", proposed="30%",
                    title="Aumentar Densidade de Preenchimento para 30%",
                    why="Reduz vazios internos sob compressão/fixação com parafusos (aumento de massa e tempo; sem promessa de carga).",
                    expected_effect="Núcleo mais denso sob faces de aperto ou compressão.",
                    what_to_check="Compare tempo e gramas antes de fatiar e valide a fixação fisicamente.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_pattern = proc.get("sparse_infill_pattern", "rectilinear")
        if "sparse_infill_pattern" in proc and cur_pattern != "gyroid":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_pattern",
                    current=str(cur_pattern), proposed="gyroid",
                    title="Padrão de Preenchimento Gyroid",
                    why="Distribui apoio em múltiplas direções sem linhas contínuas de cisalhamento típicas de padrões lineares.",
                    expected_effect="Preenchimento tridimensional uniforme com tempo moderado.",
                    what_to_check="Verifique se a peça pequena comporta células gyroid na prévia.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Orientação da Carga vs Camadas (Depende de Teste Físico)",
            why=(
                "Peças FDM são estruturalmente anisotrópicas e mais frágeis quando o esforço puxa perpendicularmente às camadas (eixo Z). "
                "A resistência final não é medida pelo fatiador."
            ),
            expected_effect="Evitar ruptura brusca entre camadas.",
            what_to_check="Posicione a peça de forma que o esforço principal atue paralelo às camadas (XY) e teste com carga real.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    elif goal.purpose == "funcional_leve":
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="3",
                    title="Elevar Paredes para Uso Funcional Leve (3)",
                    why="3 perímetros dão margem adicional de espessura para manuseio frequente sem elevar muito o peso (resistência não comprovada sem ensaio).",
                    expected_effect="Casca mais espessa que o padrão de 2 paredes com pequeno aumento de tempo.",
                    what_to_check="Avalie peso final e teste o encaixe/manuseio após imprimir.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )

    elif goal.purpose == "decorativa":
        cur_infill = proc.get("sparse_infill_density", "15%")
        infill_num = _as_float(cur_infill, 15.0)
        if "sparse_infill_density" in proc and infill_num > 15.0 and not is_abs_asa:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_density",
                    current=str(cur_infill), proposed="12%",
                    title="Reduzir Preenchimento em Peça Decorativa (12%)",
                    why="Para peças sem carga mecânica, 12% costuma sustentar o fechamento superior economizando material e tempo.",
                    expected_effect="Economia de filamento e menor tempo sem alterar o contorno externo.",
                    what_to_check="Confira na prévia se topos largos têm apoio suficiente.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if goal.priority == "qualidade":
            cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
            if "wall_loops" in proc and cur_walls < 3:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="wall_loops",
                        current=str(cur_walls), proposed="3",
                        title="3 Paredes para Acabamento Decorativo",
                        why="Reduz o risco de o padrão interno aparecer por transparência ou relevo na casca externa.",
                        expected_effect="Menor marcação do infill em filamentos claros.",
                        what_to_check="Observe a superfície lateral contra a luz após imprimir.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="wall_generator",
                        current=str(proc.get("wall_generator")), proposed="arachne",
                        title="Gerador de Parede Arachne (Detalhes Finos)",
                        why="Adapta a largura da linha em relevos estreitos, evitando vãos ou excesso de micro-preenchimento (gap infill).",
                        expected_effect="Melhor fidelidade geométrica em feições pequenas (sujeito a conferência visual).",
                        what_to_check="Compare linhas finas na prévia do ELEGOO Slicer.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
            _propose_speed_cap(
                plan, "inner_wall_speed", 120.0,
                "Moderar Velocidade da Parede Interna (120 mm/s)",
                "Ajuda a reduzir vibrações transmitidas à casca externa durante curvas e detalhes finos.",
                advices,
                confidence=conf,
            )
            _propose_speed_cap(
                plan, "top_surface_speed", 100.0,
                "Suavizar Velocidade de Topo (100 mm/s)",
                "Velocidade moderada favorece acabamento uniforme das superfícies superiores visíveis.",
                advices,
                confidence=conf,
            )
            if effective_support:
                if "tree" in effective_support_type.lower() or "support_style" in proc:
                    cur_style = str(proc.get("support_style", "default"))
                    if "support_style" in proc and cur_style not in {"tree_slim", "organic"}:
                        _add_if_valid(
                            advices,
                            Advice(
                                scope="process", slot=None, key="support_style",
                                current=cur_style, proposed="tree_slim",
                                title="Estilo de Suporte Árvore Fino (tree_slim)",
                                why="Árvores finas reduzem pontos de contato na malha decorativa e facilitam remoção.",
                                expected_effect="Menos cicatrizes em detalhes finos (exige conferência visual na prévia).",
                                what_to_check="Verifique na prévia se os galhos alcançam todas as ilhas suspensas sem quebrar.",
                                evidence_class="estimado_regra_ia",
                                requires_physical_test=False,
                                confidence=conf,
                                default_on=True,
                            ),
                            plan,
                        )
                if "support_top_z_distance" in proc and _as_float(proc.get("support_top_z_distance"), 0.2) > 0.16:
                    _add_if_valid(
                        advices,
                        Advice(
                            scope="process", slot=None, key="support_top_z_distance",
                            current=str(proc.get("support_top_z_distance")), proposed="0.16",
                            title="Ajustar Distância Z do Suporte (0.16 mm)",
                            why="Folga ligeiramente menor que 0.20 mm pode melhorar o aspecto sob saliências em PLA mantendo destacamento aceitável.",
                            expected_effect="Superfície sustentada menos áspera; se soldar demais no seu filamento, volte a 0.20 mm.",
                            what_to_check="Faça teste pequeno se houver grandes áreas horizontais apoiadas em suporte.",
                            evidence_class="estimado_regra_ia",
                            requires_physical_test=True,
                            confidence=conf,
                            default_on=True,
                        ),
                        plan,
                    )
                if obj_only_support:
                    advices.append(Advice(
                        scope="alert", slot=None, key="", current="", proposed="",
                        title="Suporte Definido Por Objeto no 3MF",
                        why="O suporte foi ativado apenas em objetos específicos dentro do arquivo; revise na aba Objetos do ELEGOO Slicer se necessário.",
                        expected_effect="Evitar remoção ou aplicação acidental de suportes locais.",
                        what_to_check="Abra a lista de Objetos no ELEGOO Slicer e confirme onde há suporte.",
                        evidence_class="verificado_3mf",
                        requires_physical_test=False,
                        confidence="alta",
                        default_on=False,
                    ))
        has_var_layer = any(
            entry.replace("\\", "/") == "Metadata/layer_heights_profile.txt"
            for entry in getattr(project, "archive_entries", ())
        )
        if has_var_layer:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Camada Variável Original Detectada (Revisar na UI)",
                why="Uma curva de altura de camada variável foi detectada no arquivo original e mantida no 3MF, porém o fatiador CLI não a aplica automaticamente — confira e reaplique ao abrir no ELEGOO Slicer.",
                expected_effect="Manter o usuário ciente da diferença entre prévia CLI e fatiamento interativo.",
                what_to_check="Clique em Variable Layer Height ao abrir o arquivo convertido no ELEGOO Slicer.",
                evidence_class="verificado_3mf",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))
        else:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Altura de Camada Variável (Dica)",
                why="Este conversor não ativa altura de camada variável por objeto automaticamente. Para suavizar topos arredondados em peças decorativas, use o botão Variable Layer Height ao revisar no ELEGOO Slicer.",
                expected_effect="Melhor transição em domos e cabeças se aplicado manualmente.",
                what_to_check="Avalie na prévia do ELEGOO Slicer se há 'degraus' visíveis no topo.",
                evidence_class="estimado_regra_ia",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))

    elif goal.purpose == "chaveiro_rigido":
        if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_generator",
                    current=str(proc.get("wall_generator")), proposed="arachne",
                    title="Gerador Arachne para Texto e Relevos",
                    why="Adapta a largura da linha em letras e contornos finos reduzindo falhas ou excesso de gap infill.",
                    expected_effect="Contornos de texto mais limpos na prévia.",
                    what_to_check="Amplie as letras na prévia do fatiador antes de imprimir.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="3",
                    title="Reforço de Paredes no Chaveiro (≥ 3)",
                    why="Contorna melhor o furo da argola metálica mantendo espessura maior quando já vier da origem.",
                    expected_effect="Mais material sólido ao redor do furo da argola.",
                    what_to_check="Puxe o furo após imprimir para testar resistência ao uso no molho de chaves.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
        if "top_shell_layers" in proc and cur_top < 5:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="top_shell_layers",
                    current=str(cur_top), proposed="5",
                    title="5 Camadas de Topo (Cobertura Uniforme)",
                    why="Ajuda a evitar marcas transparentes do preenchimento em chaveiros planos.",
                    expected_effect="Fechamento mais opaco e uniforme nas faces superiores.",
                    what_to_check="Inspecione o verso e a face principal após imprimir.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        infill_num = _as_float(proc.get("sparse_infill_density", "15%"), 15.0)
        if "sparse_infill_density" in proc and infill_num < 25.0:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_density",
                    current=str(proc.get("sparse_infill_density")), proposed="25%",
                    title="Preenchimento 25% no Corpo do Chaveiro",
                    why="Reduz flexão do corpo plano no bolso sem elevar muito o consumo em peças pequenas.",
                    expected_effect="Núcleo mais firme que 15%.",
                    what_to_check="Teste manualmente a rigidez após esfriar.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if "sparse_infill_pattern" in proc and proc.get("sparse_infill_pattern") != "gyroid":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_pattern",
                    current=str(proc.get("sparse_infill_pattern")), proposed="gyroid",
                    title="Preenchimento Gyroid",
                    why="Distribui apoio interno sem linhas retas de flexão preferencial.",
                    expected_effect="Núcleo isotrópico interno.",
                    what_to_check="Confira o tempo de impressão no fatiamento.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if goal.priority != "velocidade" and "ironing_type" in proc and proc.get("ironing_type") != "top":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="ironing_type",
                    current=str(proc.get("ironing_type")), proposed="top",
                    title="Alisamento (Ironing) no Topo",
                    why="Em chaveiros planos com relevo, passar o bico quente na última camada tende a suavizar linhas do topo (em peças 3D esculpidas pode deixar marcas; opcional).",
                    expected_effect="Tende a deixar superfícies planas mais lisas com acréscimo de tempo (calibração de fluxo influencia o resultado).",
                    what_to_check="Teste em uma unidade antes de produzir lote grande para ajustar taxa de fluxo se necessário.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=True,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        _propose_speed_cap(
            plan, "outer_wall_speed", 60.0,
            "Contorno Externo Moderado (60 mm/s)",
            "Velocidade baixa favorece precisão em letras e bordas estreitas de chaveiros.",
            advices,
            confidence=conf,
        )
        used_slots = getattr(project, "used_filament_slots", ()) or ()
        if len(project.filaments) <= 1 or len(used_slots) <= 1:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Dica de Relevo 2 Cores (Pausa por Camada)",
                why="Este chaveiro está monocromático: se houver texto/desenho em relevo, adicione uma pausa de troca de cor na camada exata do relevo pela prévia do ELEGOO Slicer.",
                expected_effect="Permitir destaque em 2 cores usando 1 carretel por vez.",
                what_to_check="Identifique na barra vertical da prévia a altura Z onde começa o texto em relevo.",
                evidence_class="estimado_regra_ia",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))

    elif goal.purpose == "chaveiro_articulado":
        if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_generator",
                    current=str(proc.get("wall_generator")), proposed="arachne",
                    title="Gerador Arachne para Elos e Pinos",
                    why="Ajusta largura de paredes em pinos finos para fechar contornos sem lacunas nem excesso de extrusão.",
                    expected_effect="Melhor definição dos elos na prévia.",
                    what_to_check="Verifique na prévia da camada se os pinos internos permanecem livres das paredes externas.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="3",
                    title="3 Paredes em Elos Articulados",
                    why="Pinos internos e alças finas de modelos flexi costumam sofrer ruptura com apenas 2 perímetros.",
                    expected_effect="Elos mais espessos (confira se não funde folgas muito pequenas).",
                    what_to_check="Articule todas as juntas após esfriar completamente.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
        if "top_shell_layers" in proc and cur_top < 5:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="top_shell_layers",
                    current=str(cur_top), proposed="5",
                    title="5 Camadas de Topo",
                    why="Ajuda a fechar a face superior dos gomos e do anel do chaveiro.",
                    expected_effect="Menos falhas em áreas curvas pequenas.",
                    what_to_check="Confira o fechamento do topo após imprimir.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_bot = _as_int(proc.get("bottom_shell_layers", "3"), 3)
        if "bottom_shell_layers" in proc and cur_bot < 4:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="bottom_shell_layers",
                    current=str(cur_bot), proposed="4",
                    title="4 Camadas de Base",
                    why="Reforça a face dos gomos em contato com a mesa.",
                    expected_effect="Base mais consistente sob atrito de bolso.",
                    what_to_check="Confira se a 1ª camada não esmagou os pinos internos.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        infill_num = _as_float(proc.get("sparse_infill_density", "15%"), 15.0)
        if "sparse_infill_density" in proc and infill_num < 20.0:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_density",
                    current=str(proc.get("sparse_infill_density")), proposed="20%",
                    title="Preenchimento 20% em Juntas",
                    why="Proporciona apoio interno equilibrado dentro dos elos.",
                    expected_effect="Menor colapso de pontes sobre pinos.",
                    what_to_check="Teste o movimento após impressão.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if "sparse_infill_pattern" in proc and proc.get("sparse_infill_pattern") != "gyroid":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_pattern",
                    current=str(proc.get("sparse_infill_pattern")), proposed="gyroid",
                    title="Preenchimento Gyroid",
                    why="Evita cruzamentos de bico que podem deslocar elos pequenos durante a impressão.",
                    expected_effect="Menos colisão do bico com gomos soltos na mesa.",
                    what_to_check="Observe as camadas intermediárias caso os gomos sejam muito leves.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        raw_brim = proc.get("brim_type")
        if not is_abs_asa and raw_brim != "no_brim":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="brim_type",
                    current=str(raw_brim or "auto_brim (padrão)"), proposed="no_brim",
                    title="Desativar Brim em Chaveiro Articulado",
                    why="Brim automático ou externo costuma fundir os elos na primeira camada e travar a articulação.",
                    expected_effect="Manter as frestas inferiores livres (exige placa PEI limpa para boa aderência).",
                    what_to_check="Confirme na prévia da camada 1 que cada elo está separado.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if "elefant_foot_compensation" in proc and _as_float(proc.get("elefant_foot_compensation", "0.1"), 0.1) < 0.15:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="elefant_foot_compensation",
                    current=str(proc.get("elefant_foot_compensation")), proposed="0.15",
                    title="Compensação Pé de Elefante (0.15 mm)",
                    why="Recua levemente o contorno da 1ª camada para reduzir chance de junta colada na mesa.",
                    expected_effect="Frestas um pouco mais abertas no contato com a mesa (se soltar da placa, reduza para 0.1).",
                    what_to_check="Verifique a fixação das menores peças na 1ª camada durante a impressão.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=True,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        if "ironing_type" in proc and proc.get("ironing_type") != "no ironing":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="ironing_type",
                    current=str(proc.get("ironing_type")), proposed="no ironing",
                    title="Desativar Ironing em Articulado",
                    why="O alisamento pode espalhar material sobre frestas estreitas entre os elos.",
                    expected_effect="Evitar rebaba superior travando o movimento.",
                    what_to_check="Confirme na visualização por tipo de linha.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        _propose_speed_cap(
            plan, "outer_wall_speed", 70.0,
            "Velocidade Moderada de Contorno (70 mm/s)",
            "Ajuda a manter precisão circular em pinos e dobradiças print-in-place.",
            advices,
            confidence=conf,
        )
        if effective_support:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Alerta: Suporte Ativo em Peça Articulada",
                why="Suportes habilitados podem preencher as folgas internas do chaveiro articulado e travar o movimento; verifique antes de imprimir.",
                expected_effect="Evitar travamento irreversível das juntas.",
                what_to_check="Desative suportes internos no ELEGOO Slicer se não houver balanços externos reais.",
                evidence_class="verificado_3mf",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Folgas e Escala de Chaveiro Articulado",
            why="Prefira escala >= 100%; reduzir um modelo articulado encolhe as folgas entre os elos e pode fundir as juntas.",
            expected_effect="Preservar tolerâncias originais de articulação.",
            what_to_check="Teste o movimento livre logo após esfriar.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    elif goal.purpose == "externa":
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="3",
                    title="Reforço Inicial de Paredes para Uso Externo (≥ 3)",
                    why="Mais perímetros reduzem caminhos diretos de umidade e aumentam espessura da casca.",
                    expected_effect="Maior barreira física externa (estanqueidade real depende de teste).",
                    what_to_check="Se precisar estanqueidade à água, avalie revestimento/ensaio físico.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
        if "top_shell_layers" in proc and cur_top < 4:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="top_shell_layers",
                    current=str(cur_top), proposed="4",
                    title="Aumentar Camadas de Topo para Uso Externo (≥ 4)",
                    why="Amplia a espessura superior exposta ao clima.",
                    expected_effect="Menor chance de microfuros no topo horizontal.",
                    what_to_check="Inspecione o fechamento superior sob sol/calor após teste.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        for _, cfg in used_target_cfgs:
            if _base_polymer(_as_str(cfg.get("filament_type"))) == "PLA":
                advices.append(Advice(
                    scope="alert", slot=None, key="", current="", proposed="",
                    title="Alerta: Resistência Térmica e UV (PLA)",
                    why="O PLA tende a amolecer por volta de 45–50 °C sob sol direto ou dentro de veículos. Para uso externo, avalie PETG ou ASA.",
                    expected_effect="Prevenir deformação térmica em campo.",
                    what_to_check="Substitua o filamento físico por PETG/ASA se houver exposição ao sol.",
                    evidence_class="depende_teste_fisico",
                    requires_physical_test=True,
                    confidence=conf,
                    default_on=False,
                ))
                break

    elif goal.purpose == "moveis":
        raw_brim = proc.get("brim_type")
        if not is_abs_asa and raw_brim != "no_brim":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="brim_type",
                    current=str(raw_brim or "auto_brim (padrão)"), proposed="no_brim",
                    title="Desativar Brim em Peças Articuladas",
                    why="Em peças com partes móveis ou print-in-place, a borda (brim) pode fundir folgas e travar as articulações.",
                    expected_effect="Evitar ligação indesejada entre partes na camada 1.",
                    what_to_check="Confira na prévia da 1ª camada que as folgas estão vazias.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Folgas e Partes Móveis",
            why="Mantenha a escala em 100% para preservar as folgas do projeto e confira a compensação de pé de elefante em teste.",
            expected_effect="Reduzir risco de juntas coladas.",
            what_to_check="Movimente cada parte móvel após resfriamento completo.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    # 2B. Regras contextuais adicionais (direção de carga, criticidade, encaixe, calor/sol)
    if goal.load_type == "tracao_eixo_z":
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Carga no Eixo Z: Limitação Estrutural da Impressão FDM",
            why=(
                "Você informou tração/puxão entre camadas (eixo Z). Aumentar apenas paredes ou preenchimento NÃO resolve a fragilidade "
                "intercamadas se a peça continuar orientada com esforço perpendicular às camadas."
            ),
            expected_effect="Evitar falsa sensação de segurança baseada só em densidade/paredes.",
            what_to_check="Rotacione a peça no ELEGOO Slicer para alinhar a carga no plano XY e execute ensaio de carga real.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    if goal.criticality == "alta":
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Criticidade Alta: Exige Peça de Teste e Ensaio Físico",
            why=(
                "Para uso crítico ou de alta criticidade (risco de segurança, quebra cara ou peça estrutural essencial), o fatiador não mede "
                "solda intercamadas nem resistência final."
            ),
            expected_effect="Estabelecer protocolo de validação antes do uso definitivo.",
            what_to_check="Imprima corpo de prova, valide dimensões e aplique teste de carga superior ao uso previsto.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    if goal.fit_clearance == "partes_moveis" and goal.purpose not in {"moveis", "chaveiro_articulado"}:
        if not is_abs_asa and proc.get("brim_type") != "no_brim":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="brim_type",
                    current=str(proc.get("brim_type") or "auto_brim (padrão)"), proposed="no_brim",
                    title="Desativar Brim devido a Partes Móveis Informadas",
                    why="Você informou partes móveis: borda na camada 1 pode travar articulações próximas à mesa.",
                    expected_effect="Preservar folga na 1ª camada.",
                    what_to_check="Confira folga inferior na prévia.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )

    if goal.heat_exposure in {"calor_sol", "agua_externo"} and goal.purpose != "externa":
        for _, cfg in used_target_cfgs:
            poly = _base_polymer(_as_str(cfg.get("filament_type")))
            if poly == "PLA":
                advices.append(Advice(
                    scope="alert", slot=None, key="", current="", proposed="",
                    title="Calor/Sol Informado com Filamento PLA",
                    why="PLA tende a deformar acima de ~45–50 °C (interior de carro ou sol direto). Considere PETG ou ASA.",
                    expected_effect="Evitar amolecimento rápido em uso real.",
                    what_to_check="Avalie trocar o filamento físico antes de imprimir ou faça teste térmico.",
                    evidence_class="depende_teste_fisico",
                    requires_physical_test=True,
                    confidence=conf,
                    default_on=False,
                ))
                break

    # 3. Ajustes por Prioridade (compatíveis com bico/perfil)
    nozzle = _as_float(plan.machine_settings.get("nozzle_diameter", "0.4"), 0.4)
    min_h = _as_float(plan.machine_settings.get("min_layer_height", "0.08"), 0.08)
    max_h = _as_float(plan.machine_settings.get("max_layer_height", "0.28"), 0.28)

    if goal.priority == "qualidade":
        if "layer_height" in proc:
            cur_h = _as_float(proc.get("layer_height"), 0.2)
            factor = 0.3 if goal.purpose == "decorativa" else 0.4
            target_h = max(min_h, round(factor * nozzle, 2))
            proposed_h = f"{target_h:g}"
            if cur_h > target_h + 0.01:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="layer_height",
                        current=f"{cur_h:g}", proposed=proposed_h,
                        title="Camadas Mais Finas (Qualidade)",
                        why="Camadas mais finas reduzem a altura visível dos degraus em curvas e detalhes finos, ao custo de maior tempo.",
                        expected_effect="Superfície com degraus menores em Z e tempo maior no fatiamento.",
                        what_to_check="Veja o novo tempo total estimado no fatiador após aplicar.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
        cur_seam = proc.get("seam_position", "aligned")
        if "seam_position" in proc and cur_seam != "back":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="seam_position",
                    current=str(cur_seam), proposed="back",
                    title="Posicionar Costura na Traseira",
                    why="Concentra o início/fim de camada na face traseira para tentar poupar a vista frontal da peça.",
                    expected_effect="Menor presença de linha de costura na frente (depende da orientação frontal).",
                    what_to_check="Confira os pontos brancos de costura na prévia do ELEGOO Slicer.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )
        target_outer = 60.0 if goal.purpose in {"decorativa", "chaveiro_rigido"} else (
            70.0 if goal.purpose == "chaveiro_articulado" else 80.0
        )
        cur_speed = _as_float(proc.get("outer_wall_speed", "160"), 160.0)
        if "outer_wall_speed" in proc and cur_speed > target_outer:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="outer_wall_speed",
                    current=f"{cur_speed:g}", proposed=f"{target_outer:g}",
                    title="Reduzir Velocidade de Parede Externa",
                    why="Velocidades externas menores costumam atenuar vibrações (ringing/ghosting) e melhorar uniformidade de brilho.",
                    expected_effect="Contorno visual mais uniforme com acréscimo de tempo.",
                    what_to_check="Compare cantos e texto na impressão real.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )

    elif goal.priority == "economia":
        cur_infill = proc.get("sparse_infill_density", "15%")
        infill_num = _as_float(cur_infill, 15.0)
        if "sparse_infill_density" in proc and infill_num > 10.0 and goal.purpose not in {
            "esforco", "chaveiro_rigido", "chaveiro_articulado"
        }:
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="sparse_infill_density",
                    current=str(cur_infill), proposed="10%",
                    title="Redução Econômica de Preenchimento (10%)",
                    why="Reduz consumo de material mantendo estrutura mínima para sustentar o fechamento superior em peças sem esforço.",
                    expected_effect="Menor gasto de gramas no fatiamento e menor rigidez interna.",
                    what_to_check="Verifique na prévia se áreas horizontais grandes não ficam sem apoio.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )

    elif goal.priority == "velocidade":
        if "layer_height" in proc:
            cur_h = _as_float(proc.get("layer_height"), 0.2)
            target_h = min(max_h, round(0.6 * nozzle, 2), round(0.75 * nozzle, 2))
            proposed_h = f"{target_h:g}"
            if cur_h < target_h - 0.01:
                _add_if_valid(
                    advices,
                    Advice(
                        scope="process", slot=None, key="layer_height",
                        current=f"{cur_h:g}", proposed=proposed_h,
                        title="Camadas Mais Altas (Velocidade)",
                        why="Menos camadas em Z reduzem bastante o tempo total estimado no fatiador, deixando degraus mais visíveis.",
                        expected_effect="Menor tempo total e menor definição vertical.",
                        what_to_check="Confira na prévia se detalhes finos não perderam nitidez.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=False,
                        confidence=conf,
                        default_on=True,
                    ),
                    plan,
                )
        cur_iron = proc.get("ironing_type", "no ironing")
        if "ironing_type" in proc and cur_iron != "no ironing":
            _add_if_valid(
                advices,
                Advice(
                    scope="process", slot=None, key="ironing_type",
                    current=str(cur_iron), proposed="no ironing",
                    title="Desativar Alisamento (Ironing)",
                    why="O alisamento acrescenta passadas lentas na última camada e eleva muito o tempo.",
                    expected_effect="Redução expressiva de tempo no topo.",
                    what_to_check="Verifique se o acabamento padrão sem ironing atende ao uso.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=False,
                    confidence=conf,
                    default_on=True,
                ),
                plan,
            )

    # 4. Alertas diagnósticos aprendidos em projetos reais
    global_infill = _as_float(proc.get("sparse_infill_density", "15%"), 15.0)
    low_infill_objs = [
        o.settings.get("sparse_infill_density", "")
        for o in (getattr(project, "object_overrides", ()) or ())
        if "sparse_infill_density" in o.settings and _as_float(o.settings["sparse_infill_density"], 100.0) <= 8.0
    ]
    if global_infill <= 8.0 or low_infill_objs:
        shown = low_infill_objs[0] if low_infill_objs else f"{global_infill:g}%"
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Preenchimento Muito Baixo (≤ 8%)",
            why=f"O projeto traz preenchimento de {shown}, o que pode causar buracos ou afundamento (pillowing) em topos horizontais caso não seja intencional.",
            expected_effect="Evitar topo afundado em áreas planas.",
            what_to_check="Inspecione o fechamento superior na prévia por camada.",
            evidence_class="verificado_3mf",
            requires_physical_test=False,
            confidence="alta",
            default_on=False,
        ))

    if any("suporte manual no arquivo sem pintagem/enforcers" in feat.lower()
           for feat in getattr(project, "advanced_features", ())):
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Suporte Manual Sem Áreas Marcadas",
            why="O arquivo usa suporte manual, mas não contém enforcers nem regiões pintadas — o fatiador não gerará suportes até que você pinte as áreas no ELEGOO Slicer.",
            expected_effect="Evitar impressão sem suportes necessários.",
            what_to_check="Abra no ELEGOO Slicer e pinte os suportes ou troque para árvore automática.",
            evidence_class="verificado_3mf",
            requires_physical_test=False,
            confidence="alta",
            default_on=False,
        ))

    for plate in project.plates:
        slots = getattr(plate, "used_filament_slots", ()) or tuple(s for s in plate.filament_slots if s and s != "0")
        unique_slots = {s for s in slots if s and s != "0"}
        if len(unique_slots) > 4:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title=f"Mais de 4 Cores Simultâneas (Placa {plate.number})",
                why=f"A Placa {plate.number} exige {len(unique_slots)} cores ({', '.join(sorted(unique_slots))}). O sistema Canvas/AMS da ECC2 gerencia até 4 carretéis automáticos; cores extras exigem troca manual ou consolidação de paleta.",
                expected_effect="Compatibilizar troca de cores com hardware da CC2.",
                what_to_check="Planeje pausa/troca manual ou reduza cores antes de imprimir a placa.",
                evidence_class="verificado_3mf",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))
            break

    src_elefant = project.source_settings.get("elefant_foot_compensation")
    if (src_elefant is not None and _as_float(src_elefant, 1.0) == 0.0
            and goal.purpose != "chaveiro_articulado"
            and _as_float(proc.get("elefant_foot_compensation", "0"), 0.0) > 0.0):
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Compensação de Pé de Elefante Zerada na Origem",
            why=f"O arquivo original usava 0 mm de pé de elefante (comum em montagens e encaixes justos), enquanto o perfil ECC2 aplicou {proc.get('elefant_foot_compensation')} mm.",
            expected_effect="Diferença sutil na folga da primeira camada.",
            what_to_check="Confira encaixes da base após a impressão de teste.",
            evidence_class="verificado_3mf",
            requires_physical_test=True,
            confidence=conf,
            default_on=False,
        ))

    if geom is not None and getattr(geom, "triangle_count", 0) > 0:
        if geom.triangle_count > 500_000:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Malha Muito Densa (Simplificar Modelo)",
                why=f"A peça tem {geom.triangle_count:,} triângulos. Acima de 500 mil triângulos o fatiamento fica lento: se notar lentidão, use 'Simplificar modelo' (Mesh Simplification) no ELEGOO Slicer.",
                expected_effect="Acelerar preparação mantendo a malha original intacta no tradutor.",
                what_to_check="Avalie o tempo de carregamento no ELEGOO Slicer.",
                evidence_class="verificado_3mf",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))
        if geom.has_slender_parts and proc.get("brim_type") == "no_brim":
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Peça Esguia ou Pequena com Risco de Descolar",
                why=f"Detectada peça estreita ou alta com pouco apoio na mesa ({geom.contact_mm2:.0f} mm²). Avalie ativar Brim (outer_only) no fatiador para evitar tombamento.",
                expected_effect="Prevenir perda da peça por descolamento lateral.",
                what_to_check="Acompanhe a 1ª camada e estabilidade em altura.",
                evidence_class="verificado_3mf",
                requires_physical_test=True,
                confidence=conf,
                default_on=False,
            ))
        if geom.overhang_mm2 >= 250.0 and not effective_support:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Saliências > 45° Sem Suporte Ativo",
                why=f"Cerca de {geom.overhang_mm2:.0f} mm² da malha possuem inclinação acima de 45° sem suporte habilitado. Revise a prévia para confirmar se suportes são necessários.",
                expected_effect="Evitar fios soltos em áreas sem apoio inferior.",
                what_to_check="Inspecione as faces inferiores em balanço na prévia 3D.",
                evidence_class="verificado_3mf",
                requires_physical_test=True,
                confidence=conf,
                default_on=False,
            ))
        if (not geom.has_slender_parts and geom.contact_mm2 >= 800.0
                and not is_abs_asa and goal.purpose == "decorativa"
                and proc.get("brim_type") in {"auto_brim", "outer_only"}):
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Base Larga em PLA (Brim Opcional)",
                why=f"A peça tem boa área de contato ({geom.contact_mm2:.0f} mm²) em PLA: na mesa texturizada da ECC2 normalmente não precisa de brim (use no_brim se preferir base limpa).",
                expected_effect="Reduzir necessidade de rebarba manual na base.",
                what_to_check="Confirme aderência visual nos cantos da 1ª camada.",
                evidence_class="verificado_3mf",
                requires_physical_test=False,
                confidence="alta",
                default_on=False,
            ))

    return _consolidate_advices(advices)


def merge_with_offline_alerts(ai_advices: list[Advice], offline_advices: list[Advice]) -> list[Advice]:
    """Combina sugestões da IA com alertas diagnósticos determinísticos locais sem duplicar títulos."""
    merged = list(ai_advices)
    seen_titles = {adv.title.strip().lower() for adv in merged if adv.scope == "alert"}
    for adv in offline_advices:
        if adv.scope == "alert":
            norm = adv.title.strip().lower()
            if norm not in seen_titles:
                seen_titles.add(norm)
                merged.append(adv)
    return merged


def apply_advice(plan: ConversionPlan, approved: list[Advice]) -> ConversionPlan:
    new_process = dict(plan.process_settings)
    new_filaments = [dict(f) for f in plan.filament_settings]
    forced_keys = list(getattr(plan, "forced_process_keys", ()) or ())

    for adv in approved:
        if adv.scope == "process":
            if validate_change("process", adv.key, adv.proposed, plan):
                new_process[adv.key] = adv.proposed
                if adv.key not in forced_keys:
                    forced_keys.append(adv.key)
        elif adv.scope == "filament" and adv.slot is not None:
            if validate_change("filament", adv.key, adv.proposed, plan, adv.slot):
                cfg = new_filaments[adv.slot - 1]
                cfg[adv.key] = [adv.proposed]

    return replace(
        plan,
        process_settings=new_process,
        filament_settings=tuple(new_filaments),
        forced_process_keys=tuple(forced_keys),
    )


def needs_user_intervention(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
    advices: list[Advice] | tuple[Advice, ...] = (),
    *,
    physical_confirmed: bool = True,
) -> tuple[bool, list[str]]:
    """Define se há ambiguidade, incompatibilidade ou risco que exige decisão do usuário."""
    reasons: list[str] = []
    if not physical_confirmed:
        reasons.append("Filamento físico carregado na impressora ainda não foi confirmado.")

    conf, conf_reasons = goal_confidence(goal)
    if conf == "baixa":
        reasons.extend(conf_reasons)

    if any(adv.scope != "alert" for adv in advices):
        reasons.append("Há ajustes recomendados de perfil/filamento para revisar antes de fatiar.")

    for adv in advices:
        if adv.scope == "alert" and (
            adv.requires_physical_test
            or adv.evidence_class in {"verificado_3mf", "depende_teste_fisico"}
        ):
            reasons.append(adv.title)

    # Dedup preserving order
    unique = list(dict.fromkeys(reasons))
    return bool(unique), unique


def build_preconversion_card(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
    *,
    physical_confirmed: bool,
    advices: list[Advice] | tuple[Advice, ...] = (),
) -> str:
    """Cartão curto pré-conversão mostrado ao iniciante antes de fatiar."""
    src_info = source_material_summary(project)
    used_slots = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    dst_mats = [
        _as_str(cfg.get("filament_type", "Desconhecido"))
        for idx, cfg in enumerate(plan.filament_settings, 1)
        if not used_slots or str(idx) in used_slots
    ] or [_as_str(cfg.get("filament_type", "Desconhecido")) for cfg in plan.filament_settings] or ["Desconhecido"]
    dst_label = "/".join(dict.fromkeys(dst_mats))

    phys_status = (
        f"Confirmado ({goal.physical_material if goal.physical_material != 'nao_sei' else dst_label})"
        if physical_confirmed
        else "PENDENTE (nunca presumir igual ao 3MF — confirme abaixo)"
    )

    slot_count = len(used_slots) if used_slots else len(project.filaments)
    plate_count = len(getattr(project, "plates", ())) or 1
    single_plate_multi = any(
        len({s for s in (getattr(p, "used_filament_slots", ()) or getattr(p, "filament_slots", ())) if s and s != "0"}) >= 2
        for p in getattr(project, "plates", ())
    )
    color_mode = "troca automática/pausa na placa" if single_plate_multi else ("troca entre placas" if plate_count > 1 and slot_count > 1 else "cor única")

    conf, _ = goal_confidence(goal)
    needs_decision, decision_reasons = needs_user_intervention(
        project, plan, goal, advices, physical_confirmed=physical_confirmed
    )
    risks_txt = "; ".join(decision_reasons[:4]) if decision_reasons else "Nenhum risco crítico identificado."

    changes = [
        f"camada {plan.process_settings.get('layer_height', '?')} mm",
        f"{len(plan.replaced)} ajustes da origem substituídos pelo perfil ELEGOO",
    ]
    if src_info["label"].upper() != dst_label.upper():
        changes.insert(0, f"troca de material {src_info['label']} → {dst_label}")

    lines = [
        "CARTÃO PRÉ-CONVERSÃO",
        f"• {evidence_label('verificado_3mf')}: Origem {src_info['label']} · {plate_count} placa(s), {slot_count} filamento(s) usado(s) ({color_mode})",
        f"• Filamento físico na impressora: {phys_status}",
        f"• Perfis ELEGOO sugeridos: {plan.machine.name} · {plan.process.name} · {', '.join(dict.fromkeys(p.name for p in plan.filaments))}",
        f"• {evidence_label('estimado_regra_ia')} (Confiança {confidence_label(conf).split(' (')[0]}): " + " · ".join(changes),
        f"• Riscos / decisões exigidas: {risks_txt}" + (" [Requer confirmação]" if needs_decision else ""),
        f"• {evidence_label('verificado_fatiamento')}: será executado ao clicar em 'Traduzir para minha ELEGOO'.",
        f"• {evidence_label('depende_teste_fisico')}: Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica.",
    ]
    return "\n".join(lines)


def build_print_summary(
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
    advices: list[Advice] | tuple[Advice, ...] = (),
    *,
    sliced_summary: str = "",
) -> str:
    """Monta quadro-resumo honesto com as 4 classes de evidência e sem garantias não medidas."""
    preview_plan = apply_advice(plan, [adv for adv in advices if adv.default_on])
    proc = preview_plan.process_settings

    src_info = source_material_summary(project)
    used_slots = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    dst_mats = [
        _as_str(cfg.get("filament_type", "Desconhecido"))
        for idx, cfg in enumerate(preview_plan.filament_settings, 1)
        if not used_slots or str(idx) in used_slots
    ] or [_as_str(cfg.get("filament_type", "Desconhecido")) for cfg in preview_plan.filament_settings] or ["Desconhecido"]

    src_summary = src_info["label"]
    dst_summary = "/".join(dict.fromkeys(dst_mats))
    is_abs_asa = any(_is_abs_asa_material(m) for m in dst_mats)
    conf, _ = goal_confidence(goal)

    if is_abs_asa:
        fans = [
            f"{_as_int(cfg.get('fan_max_speed', '35'), 35)}%"
            for idx, cfg in enumerate(preview_plan.filament_settings, 1)
            if (not used_slots or str(idx) in used_slots)
            and _is_abs_asa_material(_as_str(cfg.get("filament_type", "")))
        ]
        fan_txt = "/".join(dict.fromkeys(fans)) if fans else "perfil ELEGOO"
        has_aux = any(
            "additional_cooling_fan_speed" in cfg
            for idx, cfg in enumerate(preview_plan.filament_settings, 1)
            if not used_slots or str(idx) in used_slots
        )
        aux_txt = " e ventoinha auxiliar em 0%" if has_aux else ""
        cooling_line = (
            f"Hipótese de regra: teto de ventoinha da peça em {fan_txt}{aux_txt} para tentar conter "
            "choque térmico/empenamento em câmara passiva (requer peça de teste para validar união intercamadas)."
        )
    else:
        cooling_line = (
            "Resfriamento do perfil ELEGOO mantido como ponto de partida (padrão para pontes e saliências; conferir visualmente)."
        )

    walls = _as_str(proc.get("wall_loops", "2"))
    top_layers = _as_str(proc.get("top_shell_layers", "3"))
    infill = _as_str(proc.get("sparse_infill_density", "15%"))
    pattern = _as_str(proc.get("sparse_infill_pattern", "grid"))
    layer_h = _as_str(proc.get("layer_height", "0.2"))

    slicing_line = sliced_summary or "Estimativas de tempo e gramas serão obtidas após fatiamento real no ELEGOO Slicer."
    lines = [
        f"• Material: {src_summary} → {dst_summary}",
        f"• Uso, contexto e prioridade: {purpose_label(goal.purpose)} · {priority_label(goal.priority)} · Carga: {load_type_label(goal.load_type)}",
        f"• {evidence_label('verificado_3mf')}: {len(project.plates)} placa(s) · {len(project.objects)} objeto(s) · camada original {project.source_settings.get('layer_height', '?')} mm.",
        f"• {evidence_label('verificado_fatiamento')}: {slicing_line}",
        f"• {evidence_label('estimado_regra_ia')} (Confiança {confidence_label(conf).split(' (')[0]}): {cooling_line} Ponto de partida estrutural: {walls} paredes · topo {top_layers} camadas · preenchimento {infill} ({pattern}) · camada {layer_h} mm.",
    ]
    if is_abs_asa:
        checklist = build_abs_asa_checklist(project, preview_plan, goal)
        lines.append("• Checklist ABS/ASA (perfil ELEGOO + fabricante):")
        lines.extend(f"    {item}" for item in checklist)
    lines.append(
        f"• {evidence_label('depende_teste_fisico')}: temperatura real da câmara passiva, união entre camadas, folgas após contração e resistência final. "
        "Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica."
    )
    lines.append(
        "• O que conferir no ELEGOO Slicer: posição/apoio na mesa, direção da carga em relação às camadas, suportes, pintura e prévia da 1ª camada."
    )
    return "\n".join(lines)
