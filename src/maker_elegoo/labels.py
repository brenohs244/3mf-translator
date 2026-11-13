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
    "support_interface_top_layers": ("Camadas de interface do suporte", ""),
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
    "filament_type": ("Material", ""),
}

PURPOSE_LABELS: dict[str, str] = {
    "decorativa": "Decorativa ou visual",
    "funcional_leve": "Funcional (uso leve)",
    "esforco": "Recebe força (esforço mecânico)",
    "moveis": "Partes móveis / encaixes",
    "externa": "Uso externo / sol / calor",
    "chaveiro_rigido": "Chaveiro / peça plana com relevo (acabamento)",
    "chaveiro_articulado": "Chaveiro articulado / print-in-place",
}

PRIORITY_LABELS: dict[str, str] = {
    "qualidade": "Qualidade visual",
    "equilibrio": "Equilíbrio (recomendado)",
    "velocidade": "Velocidade",
    "economia": "Economia de material",
}

_PURPOSE_BY_LABEL = {label: code for code, label in PURPOSE_LABELS.items()}
_PRIORITY_BY_LABEL = {label: code for code, label in PRIORITY_LABELS.items()}


def purpose_label(code: str) -> str:
    return PURPOSE_LABELS.get(code, code)


def purpose_code(label_or_code: str) -> str:
    return _PURPOSE_BY_LABEL.get(label_or_code, label_or_code if label_or_code in PURPOSE_LABELS else "decorativa")


def priority_label(code: str) -> str:
    return PRIORITY_LABELS.get(code, code)


def priority_code(label_or_code: str) -> str:
    return _PRIORITY_BY_LABEL.get(label_or_code, label_or_code if label_or_code in PRIORITY_LABELS else "equilibrio")


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
