"""Motor determinístico e limites do Professor de Impressão."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from typing import Any

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
)
PRIORITIES = ("qualidade", "equilibrio", "velocidade", "economia")

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

    elif scope == "filament":
        if slot is None or slot < 1 or slot > len(plan.filament_settings):
            return False
        cfg = plan.filament_settings[slot - 1]
        if key not in SAFE_FILAMENT_KEYS or key not in cfg:
            return False
        try:
            val_int = int(value)
            orig_int = int(_as_str(cfg.get(key, "100")))
            return 0 <= val_int <= orig_int  # Apenas reduz ou mantém ventilação
        except ValueError:
            return False

    return False


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


def _propose_speed_cap(proc: dict, key: str, limit: float, title: str, why: str, advices: list[Advice]) -> None:
    if key not in proc:
        return
    cur = _as_float(proc.get(key), limit + 1)
    if cur > limit:
        advices.append(Advice(
            scope="process", slot=None, key=key,
            current=f"{cur:g}", proposed=f"{limit:g}",
            title=title, why=why, default_on=True,
        ))


def advise_offline(project: ProjectInfo, plan: ConversionPlan, goal: PrintGoal) -> list[Advice]:
    advices: list[Advice] = []
    proc = plan.process_settings
    effective_support, obj_only_support, effective_support_type = _effective_object_support(project, proc)

    # Identificar filamentos
    is_abs_asa = any(
        _as_str(cfg.get("filament_type", "")).upper() in {"ABS", "ASA"}
        for cfg in plan.filament_settings
    )
    is_original_pla = any(f.material.upper() == "PLA" for f in project.filaments)

    # 1. Ajustes por Material (Segurança & Fusão de Camadas)
    if is_abs_asa:
        for idx, cfg in enumerate(plan.filament_settings, 1):
            mat = _as_str(cfg.get("filament_type", "")).upper()
            if mat in {"ABS", "ASA"}:
                # Ventoinha máxima
                cur_fan = _as_int(cfg.get("fan_max_speed", "40"), 40)
                target_fan = 25 if goal.purpose in {"esforco", "funcional_leve"} else 35
                if "fan_max_speed" in cfg and cur_fan > target_fan:
                    advices.append(Advice(
                        scope="filament", slot=idx, key="fan_max_speed",
                        current=str(cur_fan), proposed=str(target_fan),
                        title=f"Reduzir ventoinha da peça (Filamento {idx} - {mat})",
                        why="O ABS/ASA necessita de resfriamento brando. Ventoinha alta enfraquece a fusão térmica entre as camadas e torna a peça quebradiça.",
                        default_on=True
                    ))

                # Ventoinha de saliências (overhang)
                cur_overhang = _as_int(cfg.get("overhang_fan_speed", "80"), 80)
                target_overhang = 40 if goal.purpose in {"esforco", "funcional_leve"} else 50
                if "overhang_fan_speed" in cfg and cur_overhang > target_overhang:
                    advices.append(Advice(
                        scope="filament", slot=idx, key="overhang_fan_speed",
                        current=str(cur_overhang), proposed=str(target_overhang),
                        title=f"Moderar ventoinha de saliências (Filamento {idx} - {mat})",
                        why="Ventoinha a 80% em saliências pode causar choque térmico e delaminação local no ABS/ASA; reduzir melhora a solda mantendo apoio.",
                        default_on=True
                    ))

                # Ventoinha auxiliar
                cur_aux = _as_int(cfg.get("additional_cooling_fan_speed", "0"), 0)
                if "additional_cooling_fan_speed" in cfg and cur_aux > 0:
                    advices.append(Advice(
                        scope="filament", slot=idx, key="additional_cooling_fan_speed",
                        current=str(cur_aux), proposed="0",
                        title=f"Desligar ventoinha auxiliar lateral (Filamento {idx})",
                        why="Fluxos de ar laterais causam choque térmico e delaminação severa em ABS/ASA.",
                        default_on=True
                    ))

                # Exaustão (opcional desmarcada por padrão)
                cur_ex = _as_int(cfg.get("during_print_exhaust_fan_speed", "70"), 70)
                if "during_print_exhaust_fan_speed" in cfg and cur_ex > 30:
                    advices.append(Advice(
                        scope="filament", slot=idx, key="during_print_exhaust_fan_speed",
                        current=str(cur_ex), proposed="30",
                        title=f"Reduzir exaustão da câmara para 30% (Filamento {idx})",
                        why="Manter a exaustão baixa conserva o calor dentro da impressora reduzindo o empenamento. ATENÇÃO: pode aumentar o odor de plástico no ambiente; certifique-se de que o local é ventilado.",
                        default_on=False
                    ))

        # Brim para ABS
        raw_brim = proc.get("brim_type")
        if raw_brim != "outer_only":
            advices.append(Advice(
                scope="process", slot=None, key="brim_type",
                current=str(raw_brim or "auto_brim (padrão)"), proposed="outer_only",
                title="Ativar Brim Externo (Borda)",
                why="O ABS sofre forte contração térmica nos cantos. Uma borda externa garante ancoragem à mesa texturizada.",
                default_on=True
            ))
        if "brim_width" in proc and _as_float(proc.get("brim_width", "5"), 5.0) < 5.0:
            advices.append(Advice(
                scope="process", slot=None, key="brim_width",
                current=str(proc.get("brim_width")), proposed="5",
                title="Aumentar Largura do Brim para 5 mm",
                why="Borda de pelo menos 5 mm ajuda a segurar cantos de peças em ABS/ASA contra empenamento.",
                default_on=True
            ))

        # Alertas de uso de ABS
        advices.append(Advice(
            scope="alert", slot=None, key="",
            current="", proposed="",
            title="Câmara e Ambiente para ABS",
            why="A Centauri Carbon 2 opera com câmara passiva. Mantenha tampa e porta bem fechadas, e pré-aqueça a mesa a 90°C por 10 minutos antes de iniciar.",
            default_on=False
        ))

        if is_original_pla and goal.purpose == "moveis":
            advices.append(Advice(
                scope="alert", slot=None, key="",
                current="", proposed="",
                title="Atenção: Contração de Encaixes (PLA → ABS)",
                why="O projeto original foi modelado para PLA. O ABS contrai entre 0.5% e 0.8% ao esfriar, o que pode apertar partes móveis e roscas.",
                default_on=False
            ))

    # 2. Ajustes por Uso da Peça (Propósito Mecânico)
    if goal.purpose == "esforco":
        # Paredes
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 4:
            advices.append(Advice(
                scope="process", slot=None, key="wall_loops",
                current=str(cur_walls), proposed="4",
                title="Reforço de Paredes Perimétricas",
                why="Em peças sob esforço mecânico, a rigidez e força estrutural vêm primariamente da espessura das paredes externas, e não do núcleo.",
                default_on=True
            ))
        # Topo / Base
        cur_top = _as_int(proc.get("top_shell_layers", "5"), 5)
        if "top_shell_layers" in proc and cur_top < 5:
            advices.append(Advice(
                scope="process", slot=None, key="top_shell_layers",
                current=str(cur_top), proposed="5",
                title="Reforço de Camadas de Topo",
                why="Garante rigidez contra compressão e flexão nos planos horizontais.",
                default_on=True
            ))
        # Preenchimento
        cur_infill = proc.get("sparse_infill_density", "15%")
        infill_num = _as_float(cur_infill, 15.0)
        if "sparse_infill_density" in proc and infill_num < 30.0:
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_density",
                current=str(cur_infill), proposed="30%",
                title="Aumentar Densidade de Preenchimento",
                why="Núcleo mais denso para suportar cargas distribuídas sem esmagamento interno.",
                default_on=True
            ))
        cur_pattern = proc.get("sparse_infill_pattern", "rectilinear")
        if "sparse_infill_pattern" in proc and cur_pattern != "gyroid":
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_pattern",
                current=str(cur_pattern), proposed="gyroid",
                title="Padrão de Preenchimento Giroscópico (Gyroid)",
                why="O padrão giroscópio dissipa tensões uniformemente em todas as direções (3D), evitando linhas de fratura comuns em padrões lineares ou grade.",
                default_on=True
            ))
        advices.append(Advice(
            scope="alert", slot=None, key="",
            current="", proposed="",
            title="Orientação da Carga vs Camadas",
            why="Peças FDM são naturalmente mais frágeis no sentido do eixo Z (solda entre camadas). Posicione a peça de modo que o esforço não tente abrir as camadas.",
            default_on=False
        ))

    elif goal.purpose == "funcional_leve":
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            advices.append(Advice(
                scope="process", slot=None, key="wall_loops",
                current=str(cur_walls), proposed="3",
                title="Aumentar Paredes para Uso Funcional",
                why="3 perímetros garantem solidez adequada para manuseio frequente sem peso excessivo.",
                default_on=True
            ))

    elif goal.purpose == "decorativa":
        cur_infill = proc.get("sparse_infill_density", "15%")
        infill_num = _as_float(cur_infill, 15.0)
        if "sparse_infill_density" in proc and infill_num > 15.0 and not is_abs_asa:
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_density",
                current=str(cur_infill), proposed="12%",
                title="Otimizar Preenchimento para Peça Decorativa",
                why="A peça não sofrerá forças mecânicas; 12% é suficiente para sustentar o topo, economizando tempo e filamento.",
                default_on=True
            ))
        if goal.priority == "qualidade":
            cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
            if "wall_loops" in proc and cur_walls < 3:
                advices.append(Advice(
                    scope="process", slot=None, key="wall_loops",
                    current=str(cur_walls), proposed="3",
                    title="3 Paredes para Acabamento Decorativo",
                    why="Evita que marcas do preenchimento apareçam na casca externa da miniatura ou estátua.",
                    default_on=True,
                ))
            if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
                advices.append(Advice(
                    scope="process", slot=None, key="wall_generator",
                    current=str(proc.get("wall_generator")), proposed="arachne",
                    title="Gerador de Parede Arachne (Detalhes Finos)",
                    why="Adapta a largura da linha automaticamente para não perder relevos finos, olhos, roupas e texturas.",
                    default_on=True,
                ))
            _propose_speed_cap(
                proc, "inner_wall_speed", 120.0,
                "Moderar Velocidade da Parede Interna",
                "Reduz vibrações transmitidas à casca externa durante curvas e detalhes finos.",
                advices,
            )
            _propose_speed_cap(
                proc, "top_surface_speed", 100.0,
                "Suavizar Velocidade de Topo",
                "Melhora o fechamento e acabamento das superfícies superiores visíveis.",
                advices,
            )
            if effective_support:
                if "tree" in effective_support_type.lower() or "support_style" in proc:
                    cur_style = str(proc.get("support_style", "default"))
                    if "support_style" in proc and cur_style not in {"tree_slim", "organic"}:
                        advices.append(Advice(
                            scope="process", slot=None, key="support_style",
                            current=cur_style, proposed="tree_slim",
                            title="Estilo de Suporte Árvore Fino (tree_slim)",
                            why="Suportes em árvore finos tocam menos área na peça decorativa e saem com menos marcas.",
                            default_on=True,
                        ))
                if "support_top_z_distance" in proc and _as_float(proc.get("support_top_z_distance"), 0.2) > 0.16:
                    if validate_change("process", "support_top_z_distance", "0.16", plan):
                        advices.append(Advice(
                            scope="process", slot=None, key="support_top_z_distance",
                            current=str(proc.get("support_top_z_distance")), proposed="0.16",
                            title="Ajustar Distância Z do Suporte (0.16 mm)",
                            why="Melhora o acabamento abaixo de saliências sem soldar o suporte no PLA.",
                            default_on=True,
                        ))
                if obj_only_support:
                    advices.append(Advice(
                        scope="alert", slot=None, key="", current="", proposed="",
                        title="Suporte Definido Por Objeto no 3MF",
                        why="O suporte foi ativado apenas em objetos específicos dentro do arquivo; revise na aba Objetos do ELEGOO Slicer se necessário.",
                        default_on=False,
                    ))
        has_var_layer = any(
            entry.replace("\\", "/") == "Metadata/layer_heights_profile.txt"
            for entry in getattr(project, "archive_entries", ())
        )
        if has_var_layer:
            advices.append(Advice(
                scope="alert", slot=None, key="",
                current="", proposed="",
                title="Camada Variável Original Detectada (Revisar na UI)",
                why="Uma curva de altura de camada variável foi detectada no arquivo original e mantida no 3MF, porém o fatiador CLI não a aplica automaticamente — confira e reaplique ao abrir no ELEGOO Slicer.",
                default_on=False
            ))
        else:
            advices.append(Advice(
                scope="alert", slot=None, key="",
                current="", proposed="",
                title="Altura de Camada Variável (Dica)",
                why="Este conversor não ativa altura de camada variável por objeto automaticamente. Para suavizar topos arredondados em peças decorativas, use o botão Variable Layer Height ao revisar no ELEGOO Slicer.",
                default_on=False
            ))

    elif goal.purpose == "chaveiro_rigido":
        if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
            advices.append(Advice(
                scope="process", slot=None, key="wall_generator",
                current=str(proc.get("wall_generator")), proposed="arachne",
                title="Gerador Arachne para Texto e Relevos",
                why="Captura letras e contornos finos de chaveiros sem deixar vãos nem excesso de micro-preenchimento (gap infill).",
                default_on=True,
            ))
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            advices.append(Advice(
                scope="process", slot=None, key="wall_loops",
                current=str(cur_walls), proposed="3",
                title="Reforço de Paredes no Chaveiro (≥ 3)",
                why="Reforça bordas e o furo da argola contra quebra no uso diário (mantém valores maiores caso já existam).",
                default_on=True,
            ))
        cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
        if "top_shell_layers" in proc and cur_top < 5:
            advices.append(Advice(
                scope="process", slot=None, key="top_shell_layers",
                current=str(cur_top), proposed="5",
                title="5 Camadas de Topo (Cobertura Uniforme)",
                why="Garante topo fechado, opaco e sem marcas do preenchimento em chaveiros planos.",
                default_on=True,
            ))
        infill_num = _as_float(proc.get("sparse_infill_density", "15%"), 15.0)
        if "sparse_infill_density" in proc and infill_num < 25.0:
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_density",
                current=str(proc.get("sparse_infill_density")), proposed="25%",
                title="Preenchimento 25% para Resistência no Bolso",
                why="Dá rigidez estrutural ao corpo e furo da argola sem pesar.",
                default_on=True,
            ))
        if "sparse_infill_pattern" in proc and proc.get("sparse_infill_pattern") != "gyroid":
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_pattern",
                current=str(proc.get("sparse_infill_pattern")), proposed="gyroid",
                title="Preenchimento Gyroid",
                why="Distribui melhor a torção quando o chaveiro sofre esforço no bolso ou mochila.",
                default_on=True,
            ))
        if goal.priority != "velocidade" and "ironing_type" in proc and proc.get("ironing_type") != "top":
            advices.append(Advice(
                scope="process", slot=None, key="ironing_type",
                current=str(proc.get("ironing_type")), proposed="top",
                title="Alisamento (Ironing) no Topo",
                why="Deixa faces superiores planas e fundos de chaveiro com acabamento liso quase injetado.",
                default_on=True,
            ))
        _propose_speed_cap(
            proc, "outer_wall_speed", 60.0,
            "Contorno Externo Preciso (60 mm/s)",
            "Garante bordas nítidas em cantos e letras de chaveiros.",
            advices,
        )
        used_slots = getattr(project, "used_filament_slots", ()) or ()
        if len(project.filaments) <= 1 or len(used_slots) <= 1:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Dica de Relevo 2 Cores (Pausa por Camada)",
                why="Este chaveiro está monocromático: se houver texto/desenho em relevo, adicione uma pausa de troca de cor na camada exata do relevo pela prévia do ELEGOO Slicer.",
                default_on=False,
            ))

    elif goal.purpose == "chaveiro_articulado":
        if "wall_generator" in proc and proc.get("wall_generator") != "arachne":
            advices.append(Advice(
                scope="process", slot=None, key="wall_generator",
                current=str(proc.get("wall_generator")), proposed="arachne",
                title="Gerador Arachne para Elos e Pinos",
                why="Melhora a precisão dimensional em elos estreitos e reduz falhas de fechamento nas juntas.",
                default_on=True,
            ))
        cur_walls = _as_int(proc.get("wall_loops", "2"), 2)
        if "wall_loops" in proc and cur_walls < 3:
            advices.append(Advice(
                scope="process", slot=None, key="wall_loops",
                current=str(cur_walls), proposed="3",
                title="3 Paredes em Elos Articulados",
                why="Pinos internos e elos de chaveiros flexi quebram fácil com menos de 3 perímetros.",
                default_on=True,
            ))
        cur_top = _as_int(proc.get("top_shell_layers", "3"), 3)
        if "top_shell_layers" in proc and cur_top < 5:
            advices.append(Advice(
                scope="process", slot=None, key="top_shell_layers",
                current=str(cur_top), proposed="5",
                title="5 Camadas de Topo",
                why="Reforça a face superior dos gomos e do anel do chaveiro.",
                default_on=True,
            ))
        cur_bot = _as_int(proc.get("bottom_shell_layers", "3"), 3)
        if "bottom_shell_layers" in proc and cur_bot < 4:
            advices.append(Advice(
                scope="process", slot=None, key="bottom_shell_layers",
                current=str(cur_bot), proposed="4",
                title="4 Camadas de Base",
                why="Aumenta a durabilidade dos elos na face de contato com a mesa.",
                default_on=True,
            ))
        infill_num = _as_float(proc.get("sparse_infill_density", "15%"), 15.0)
        if "sparse_infill_density" in proc and infill_num < 20.0:
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_density",
                current=str(proc.get("sparse_infill_density")), proposed="20%",
                title="Preenchimento 20% em Juntas",
                why="Equilíbrio ideal para pinos internos de chaveiros flexíveis resistirem a torção.",
                default_on=True,
            ))
        if "sparse_infill_pattern" in proc and proc.get("sparse_infill_pattern") != "gyroid":
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_pattern",
                current=str(proc.get("sparse_infill_pattern")), proposed="gyroid",
                title="Preenchimento Gyroid",
                why="Suporta flexões repetidas sem delaminação.",
                default_on=True,
            ))
        raw_brim = proc.get("brim_type")
        if not is_abs_asa and raw_brim != "no_brim":
            advices.append(Advice(
                scope="process", slot=None, key="brim_type",
                current=str(raw_brim or "auto_brim (padrão)"), proposed="no_brim",
                title="Desativar Brim em Chaveiro Articulado",
                why="Brim automático ou externo funde os elos da primeira camada e inutiliza a articulação.",
                default_on=True,
            ))
        if "elefant_foot_compensation" in proc and _as_float(proc.get("elefant_foot_compensation", "0.1"), 0.1) < 0.15:
            advices.append(Advice(
                scope="process", slot=None, key="elefant_foot_compensation",
                current=str(proc.get("elefant_foot_compensation")), proposed="0.15",
                title="Compensação Pé de Elefante (0.15 mm)",
                why="Afasta levemente o contorno da 1ª camada para impedir que juntas e pinos colem na mesa.",
                default_on=True,
            ))
        if "ironing_type" in proc and proc.get("ironing_type") != "no ironing":
            advices.append(Advice(
                scope="process", slot=None, key="ironing_type",
                current=str(proc.get("ironing_type")), proposed="no ironing",
                title="Desativar Ironing em Articulado",
                why="O alisamento pode espalhar material sobre frestas estreitas entre os elos.",
                default_on=True,
            ))
        _propose_speed_cap(
            proc, "outer_wall_speed", 70.0,
            "Velocidade Moderada de Contorno (70 mm/s)",
            "Mantém precisão circular nos elos e dobradiças print-in-place.",
            advices,
        )
        if effective_support:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Alerta: Suporte Ativo em Peça Articulada",
                why="Suportes habilitados podem preencher as folgas internas do chaveiro articulado e travar o movimento; verifique antes de imprimir.",
                default_on=False,
            ))
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Folgas e Escala de Chaveiro Articulado",
            why="Prefira escala >= 100%; reduzir um modelo articulado encolhe as folgas entre os elos e pode fundir as juntas.",
            default_on=False,
        ))

    elif goal.purpose == "externa":
        # Checar se filamento é PLA
        for cfg in plan.filament_settings:
            if _as_str(cfg.get("filament_type")).upper() == "PLA":
                advices.append(Advice(
                    scope="alert", slot=None, key="",
                    current="", proposed="",
                    title="Alerta: Resistência Térmica e UV (PLA)",
                    why="O PLA amolece e deforma por volta de 45°C–50°C sob sol direto ou dentro de veículos. Para uso externo, considere utilizar PETG ou ASA.",
                    default_on=False
                ))
                break

    elif goal.purpose == "moveis":
        raw_brim = proc.get("brim_type")
        if not is_abs_asa and raw_brim != "no_brim":
            advices.append(Advice(
                scope="process", slot=None, key="brim_type",
                current=str(raw_brim or "auto_brim (padrão)"), proposed="no_brim",
                title="Desativar Brim em Peças Articuladas",
                why="Em peças com partes móveis ou print-in-place, a borda (brim) pode fundir folgas e travar as articulações.",
                default_on=True
            ))
        advices.append(Advice(
            scope="alert", slot=None, key="",
            current="", proposed="",
            title="Folgas e Partes Móveis",
            why="Mantenha a escala em 100% para preservar as folgas do projeto e confira a compensação de pé de elefante caso as primeiras camadas fiquem coladas.",
            default_on=False
        ))

    # 3. Ajustes por Prioridade
    nozzle = _as_float(plan.machine_settings.get("nozzle_diameter", "0.4"), 0.4)
    min_h = _as_float(plan.machine_settings.get("min_layer_height", "0.08"), 0.08)
    max_h = _as_float(plan.machine_settings.get("max_layer_height", "0.28"), 0.28)

    if goal.priority == "qualidade":
        if "layer_height" in proc:
            cur_h = _as_float(proc.get("layer_height"), 0.2)
            factor = 0.3 if goal.purpose == "decorativa" else 0.4
            target_h = max(min_h, round(factor * nozzle, 2))
            proposed_h = f"{target_h:g}"
            if cur_h > target_h + 0.01 and validate_change("process", "layer_height", proposed_h, plan):
                advices.append(Advice(
                    scope="process", slot=None, key="layer_height",
                    current=f"{cur_h:g}", proposed=proposed_h,
                    title="Camadas Mais Finas (Qualidade)",
                    why="Reduz a altura da camada para suavizar degraus em curvas e detalhes finos, aumentando o tempo de impressão.",
                    default_on=True
                ))
        cur_seam = proc.get("seam_position", "aligned")
        if "seam_position" in proc and cur_seam != "back":
            advices.append(Advice(
                scope="process", slot=None, key="seam_position",
                current=str(cur_seam), proposed="back",
                title="Costura Oculta na Traseira",
                why="Posiciona as transições de início de camada na parte posterior da peça, mantendo a face frontal lisa e visualmente limpa.",
                default_on=True
            ))
        target_outer = 60.0 if goal.purpose in {"decorativa", "chaveiro_rigido"} else (
            70.0 if goal.purpose == "chaveiro_articulado" else 80.0
        )
        cur_speed = _as_float(proc.get("outer_wall_speed", "160"), 160.0)
        if "outer_wall_speed" in proc and cur_speed > target_outer:
            advices.append(Advice(
                scope="process", slot=None, key="outer_wall_speed",
                current=f"{cur_speed:g}", proposed=f"{target_outer:g}",
                title="Reduzir Velocidade de Parede Externa",
                why="Menor velocidade reduz vibrações ('ringing/ghosting') e melhora a precisão superficial.",
                default_on=True
            ))

    elif goal.priority == "economia":
        cur_infill = proc.get("sparse_infill_density", "15%")
        infill_num = _as_float(cur_infill, 15.0)
        if "sparse_infill_density" in proc and infill_num > 10.0 and goal.purpose not in {
            "esforco", "chaveiro_rigido", "chaveiro_articulado"
        }:
            advices.append(Advice(
                scope="process", slot=None, key="sparse_infill_density",
                current=str(cur_infill), proposed="10%",
                title="Redução Econômica de Preenchimento",
                why="Preenchimento de 10% consome menos material preservando o fechamento superior.",
                default_on=True
            ))

    elif goal.priority == "velocidade":
        if "layer_height" in proc:
            cur_h = _as_float(proc.get("layer_height"), 0.2)
            target_h = min(max_h, round(0.6 * nozzle, 2), round(0.75 * nozzle, 2))
            proposed_h = f"{target_h:g}"
            if cur_h < target_h - 0.01 and validate_change("process", "layer_height", proposed_h, plan):
                advices.append(Advice(
                    scope="process", slot=None, key="layer_height",
                    current=f"{cur_h:g}", proposed=proposed_h,
                    title="Camadas Mais Altas (Velocidade)",
                    why="Menos camadas reduzem bastante o tempo total mantendo boa resistência, com linhas horizontais um pouco mais visíveis.",
                    default_on=True
                ))
        cur_iron = proc.get("ironing_type", "no ironing")
        if "ironing_type" in proc and cur_iron != "no ironing":
            advices.append(Advice(
                scope="process", slot=None, key="ironing_type",
                current=str(cur_iron), proposed="no ironing",
                title="Desativar Alisamento (Ironing)",
                why="Alisamento aumenta consideravelmente o tempo de impressão na última camada.",
                default_on=True
            ))

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
            default_on=False,
        ))

    if any("suporte manual no arquivo sem pintagem/enforcers" in feat.lower()
           for feat in getattr(project, "advanced_features", ())):
        advices.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Suporte Manual Sem Áreas Marcadas",
            why="O arquivo usa suporte manual, mas não contém enforcers nem regiões pintadas — o fatiador não gerará suportes até que você pinte as áreas no ELEGOO Slicer.",
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
            why=f"O arquivo original usava 0 mm de pé de elefante (comum em montagens e encaixes justos), enquanto o perfil ECC2 aplicou {proc.get('elefant_foot_compensation')} mm. Confira as folgas após imprimir.",
            default_on=False,
        ))

    geom = getattr(project, "geometry_summary", None)
    if geom is not None and getattr(geom, "triangle_count", 0) > 0:
        if geom.triangle_count > 500_000:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Malha Muito Densa (Simplificar Modelo)",
                why=f"A peça tem {geom.triangle_count:,} triângulos. Acima de 500 mil triângulos o fatiamento fica lento: se notar lentidão, use 'Simplificar modelo' (Mesh Simplification) no ELEGOO Slicer.",
                default_on=False,
            ))
        if geom.has_slender_parts and proc.get("brim_type") == "no_brim":
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Peça Esguia ou Pequena com Risco de Descolar",
                why=f"Detectada peça estreita ou alta com pouco apoio na mesa ({geom.contact_mm2:.0f} mm²). Avalie ativar Brim (outer_only) no fatiador para evitar tombamento.",
                default_on=False,
            ))
        if geom.overhang_mm2 >= 250.0 and not effective_support:
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Saliências > 45° Sem Suporte Ativo",
                why=f"Cerca de {geom.overhang_mm2:.0f} mm² da malha possuem inclinação acima de 45° sem suporte habilitado. Revise a prévia para confirmar se suportes são necessários.",
                default_on=False,
            ))
        if (not geom.has_slender_parts and geom.contact_mm2 >= 800.0
                and not is_abs_asa and goal.purpose == "decorativa"
                and proc.get("brim_type") in {"auto_brim", "outer_only"}):
            advices.append(Advice(
                scope="alert", slot=None, key="", current="", proposed="",
                title="Base Larga em PLA (Brim Opcional)",
                why=f"A peça tem boa área de contato ({geom.contact_mm2:.0f} mm²) em PLA: na mesa texturizada da ECC2 normalmente não precisa de brim (use no_brim se preferir base limpa).",
                default_on=False,
            ))

    return _consolidate_advices(advices)


def apply_advice(plan: ConversionPlan, approved: list[Advice]) -> ConversionPlan:
    new_process = dict(plan.process_settings)
    new_filaments = [dict(f) for f in plan.filament_settings]

    for adv in approved:
        if adv.scope == "process":
            if validate_change("process", adv.key, adv.proposed, plan):
                new_process[adv.key] = adv.proposed
        elif adv.scope == "filament" and adv.slot is not None:
            if validate_change("filament", adv.key, adv.proposed, plan, adv.slot):
                cfg = new_filaments[adv.slot - 1]
                cfg[adv.key] = [adv.proposed]

    return replace(
        plan,
        process_settings=new_process,
        filament_settings=tuple(new_filaments),
    )
