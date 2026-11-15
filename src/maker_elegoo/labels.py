"""Tradução e formatação amigável de chaves, unidades e durações para o usuário."""

from __future__ import annotations

LABELS: dict[str, tuple[str, str]] = {
    "nozzle_temperature": ("Temperatura do bico", "°C"),
    "nozzle_temperature_initial_layer": ("Temperatura inicial do bico", "°C"),
    "textured_plate_temp": ("Temperatura da mesa texturizada", "°C"),
    "hot_plate_temp": ("Temperatura da mesa lisa", "°C"),
    "fan_max_speed": ("Ventoinha de resfriamento da peça (máx)", "%"),
    "fan_min_speed": ("Ventoinha de resfriamento da peça (mín)", "%"),
    "overhang_fan_speed": ("Ventoinha de saliências (overhang)", "%"),
    "additional_cooling_fan_speed": ("Ventoinha auxiliar lateral", "%"),
    "during_print_exhaust_fan_speed": ("Ventoinha de exaustão/câmara", "%"),
    "filament_max_volumetric_speed": ("Vazão volumétrica máxima", "mm³/s"),
    "wall_loops": ("Paredes", ""),
    "wall_generator": ("Gerador de parede", ""),
    "top_shell_layers": ("Camadas de topo", ""),
    "bottom_shell_layers": ("Camadas de base", ""),
    "sparse_infill_density": ("Densidade de preenchimento", ""),
    "sparse_infill_pattern": ("Padrão de preenchimento", ""),
    "layer_height": ("Altura de camada", "mm"),
    "enable_support": ("Suportes", ""),
    "support_type": ("Tipo de suporte", ""),
    "support_style": ("Estilo de suporte", ""),
    "support_top_z_distance": ("Distância Z do topo do suporte", "mm"),
    "support_bottom_z_distance": ("Distância Z da base do suporte", "mm"),
    "support_object_xy_distance": ("Distância XY entre suporte e peça", "mm"),
    "support_interface_top_layers": ("Camadas de interface do suporte (topo)", ""),
    "support_interface_bottom_layers": ("Camadas de interface do suporte (base)", ""),
    "support_interface_spacing": ("Espaçamento da interface do suporte", "mm"),
    "support_threshold_angle": ("Ângulo limite do suporte", "°"),
    "enable_prime_tower": ("Torre de purga (prime tower)", ""),
    "brim_width": ("Largura do brim (borda)", "mm"),
    "brim_type": ("Tipo de brim", ""),
    "seam_position": ("Posição da costura", ""),
    "ironing_type": ("Passar a ferro (ironing)", ""),
    "outer_wall_speed": ("Velocidade da parede externa", "mm/s"),
    "inner_wall_speed": ("Velocidade da parede interna", "mm/s"),
    "top_surface_speed": ("Velocidade da superfície superior", "mm/s"),
    "elefant_foot_compensation": ("Compensação pé de elefante", "mm"),
    "xy_contour_compensation": ("Compensação XY externa (contorno)", "mm"),
    "xy_hole_compensation": ("Compensação XY de furos", "mm"),
    "filament_type": ("Material", ""),
    "filament_shrink": ("Compensação de contração do filamento", ""),
    "passive_preheat_seconds": ("Pré-aquecimento passivo da câmara", "s"),
}

PURPOSE_LABELS: dict[str, str] = {
    "decorativa": "Decorativa ou visual",
    "funcional_leve": "Funcional (uso leve)",
    "esforco": "Recebe força (esforço mecânico)",
    "moveis": "Partes móveis / encaixes",
    "externa": "Uso externo / sol / calor",
    "chaveiro_rigido": "Chaveiro / peça plana com relevo (acabamento)",
    "chaveiro_articulado": "Chaveiro articulado / print-in-place",
    "nao_sei": "Não sei informar (confiança reduzida)",
}

PRIORITY_LABELS: dict[str, str] = {
    "qualidade": "Qualidade visual",
    "equilibrio": "Equilíbrio (recomendado)",
    "velocidade": "Velocidade",
    "economia": "Economia de material",
}

LOAD_TYPE_LABELS: dict[str, str] = {
    "nao_sei": "Não sei informar",
    "decorativa": "Sem carga mecânica (apenas visual)",
    "flexao_lateral": "Flexão / esforço paralelo às camadas (XY)",
    "tracao_eixo_z": "Tração / puxão entre camadas (eixo Z)",
    "compressao": "Compressão / esmagamento",
    "impacto": "Impacto / encaixe repetido / vibração",
}

CRITICALITY_LABELS: dict[str, str] = {
    "nao_sei": "Não sei informar",
    "baixa": "Baixa (falha não gera risco/prejuízo)",
    "media": "Média (uso funcional cotidiano)",
    "alta": "Alta (carga crítica, segurança ou peça essencial)",
}

FIT_LABELS: dict[str, str] = {
    "nao_sei": "Não sei informar",
    "sem_encaixe": "Sem encaixe ou partes móveis",
    "encaixe_justo": "Roscas, travas ou encaixes justos",
    "partes_moveis": "Partes móveis / articuladas no local",
}

HEAT_EXPOSURE_LABELS: dict[str, str] = {
    "nao_sei": "Não sei informar",
    "interno": "Ambiente interno (até ~40 °C)",
    "calor_sol": "Calor, sol direto ou interior de carro",
    "agua_externo": "Área externa (sol + chuva/umidade)",
}

EVIDENCE_LABELS: dict[str, str] = {
    "verificado_3mf": "Verificado no 3MF",
    "verificado_fatiamento": "Verificado pelo fatiamento",
    "estimado_regra_ia": "Estimado por regra/IA",
    "depende_teste_fisico": "Depende de teste físico",
}

CONFIDENCE_LABELS: dict[str, str] = {
    "alta": "Alta (cenário informado; resultado final exige peça de teste)",
    "media": "Média",
    "baixa": "Baixa (há itens em 'Não sei' ou sem confirmação física)",
}

_PURPOSE_BY_LABEL = {label: code for code, label in PURPOSE_LABELS.items()}
_PRIORITY_BY_LABEL = {label: code for code, label in PRIORITY_LABELS.items()}
_LOAD_BY_LABEL = {label: code for code, label in LOAD_TYPE_LABELS.items()}
_CRITICALITY_BY_LABEL = {label: code for code, label in CRITICALITY_LABELS.items()}
_FIT_BY_LABEL = {label: code for code, label in FIT_LABELS.items()}
_HEAT_BY_LABEL = {label: code for code, label in HEAT_EXPOSURE_LABELS.items()}


def purpose_label(code: str) -> str:
    return PURPOSE_LABELS.get(code, code)


def purpose_code(label_or_code: str) -> str:
    return _PURPOSE_BY_LABEL.get(label_or_code, label_or_code if label_or_code in PURPOSE_LABELS else "decorativa")


def priority_label(code: str) -> str:
    return PRIORITY_LABELS.get(code, code)


def priority_code(label_or_code: str) -> str:
    return _PRIORITY_BY_LABEL.get(label_or_code, label_or_code if label_or_code in PRIORITY_LABELS else "equilibrio")


def load_type_label(code: str) -> str:
    return LOAD_TYPE_LABELS.get(code, code)


def load_type_code(label_or_code: str) -> str:
    return _LOAD_BY_LABEL.get(label_or_code, label_or_code if label_or_code in LOAD_TYPE_LABELS else "nao_sei")


def criticality_label(code: str) -> str:
    return CRITICALITY_LABELS.get(code, code)


def criticality_code(label_or_code: str) -> str:
    return _CRITICALITY_BY_LABEL.get(label_or_code, label_or_code if label_or_code in CRITICALITY_LABELS else "nao_sei")


def fit_label(code: str) -> str:
    return FIT_LABELS.get(code, code)


def fit_code(label_or_code: str) -> str:
    return _FIT_BY_LABEL.get(label_or_code, label_or_code if label_or_code in FIT_LABELS else "nao_sei")


def heat_exposure_label(code: str) -> str:
    return HEAT_EXPOSURE_LABELS.get(code, code)


def heat_exposure_code(label_or_code: str) -> str:
    return _HEAT_BY_LABEL.get(label_or_code, label_or_code if label_or_code in HEAT_EXPOSURE_LABELS else "nao_sei")


def evidence_label(code: str) -> str:
    return EVIDENCE_LABELS.get(code, code)


def confidence_label(code: str) -> str:
    return CONFIDENCE_LABELS.get(code, code)


def describe_change(key: str, before: str, after: str) -> str:
    name, unit = LABELS.get(key, (key, ""))
    suffix = f" {unit}" if unit else ""
    return f"{name}: {before} → {after}{suffix}"


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "indisponível"
    total_sec = max(0, int(round(seconds)))
    minutes = (total_sec + 59) // 60
    hours = minutes // 60
    rem_min = minutes % 60
    if hours > 0:
        return f"{hours}h {rem_min:02d}min"
    return f"{rem_min}min"
