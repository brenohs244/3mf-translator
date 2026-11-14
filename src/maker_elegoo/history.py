"""Histórico local opcional de resultados visuais/funcionais após impressão física."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .settings import settings_path

if TYPE_CHECKING:
    from .mapping import ConversionPlan
    from .professor import Advice, PrintGoal
    from .project import ProjectInfo

VISUAL_RESULTS: dict[str, str] = {
    "aprovado": "Aprovado visual e funcionalmente",
    "acabamento_ruim": "Acabamento ruim / marcas de velocidade",
    "empenou_soltou": "Empenou ou descolou da mesa",
    "articulacao_colou": "Articulação / encaixe travou ou colou",
    "fragil_quebrou": "Quebrou / delaminou sob esforço",
    "folga_apertada": "Folga apertada após resfriamento",
}


@dataclass(frozen=True)
class FeedbackRecord:
    """Registro estritamente local do resultado observado após imprimir."""

    timestamp: str
    project_label: str
    source_material: str
    target_material: str
    nozzle_mm: str
    purpose: str
    priority: str
    load_type: str
    visual_result: str
    applied_params: dict[str, str]
    notes: str = ""


def history_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return settings_path().parent / "print_feedback_history.json"


def load_feedback_history(path: Path | None = None) -> list[FeedbackRecord]:
    target = history_path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    records: list[FeedbackRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        params = item.get("applied_params")
        records.append(
            FeedbackRecord(
                timestamp=str(item.get("timestamp", "")),
                project_label=str(item.get("project_label", ""))[:80],
                source_material=str(item.get("source_material", "")),
                target_material=str(item.get("target_material", "")),
                nozzle_mm=str(item.get("nozzle_mm", "0.4")),
                purpose=str(item.get("purpose", "decorativa")),
                priority=str(item.get("priority", "equilibrio")),
                load_type=str(item.get("load_type", "nao_sei")),
                visual_result=str(item.get("visual_result", "aprovado")),
                applied_params={str(k): str(v) for k, v in params.items()} if isinstance(params, dict) else {},
                notes=str(item.get("notes", ""))[:300],
            )
        )
    return records


def append_feedback_record(record: FeedbackRecord, path: Path | None = None) -> list[FeedbackRecord]:
    target = history_path(path)
    records = load_feedback_history(target)
    stamped = record if record.timestamp else FeedbackRecord(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        project_label=record.project_label[:80],
        source_material=record.source_material,
        target_material=record.target_material,
        nozzle_mm=record.nozzle_mm,
        purpose=record.purpose,
        priority=record.priority,
        load_type=record.load_type,
        visual_result=record.visual_result,
        applied_params=dict(record.applied_params),
        notes=record.notes[:300],
    )
    records.append(stamped)
    records = records[-100:]  # Limita tamanho local mantendo os 100 registros mais recentes.
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return records


def clear_feedback_history(path: Path | None = None) -> None:
    target = history_path(path)
    if target.exists():
        target.unlink()


def _base_polymer(material: str) -> str:
    upper = material.upper()
    for token in ("ABS", "ASA", "PETG", "PLA", "TPU", "PA", "PC"):
        if token in upper:
            return token
    return upper.strip()


def adjust_advices_from_history(
    advices: list["Advice"],
    project: "ProjectInfo",
    plan: "ConversionPlan",
    goal: "PrintGoal",
    records: list[FeedbackRecord] | tuple[FeedbackRecord, ...],
) -> list["Advice"]:
    """Contextualiza alertas e recomendações usando apenas feedback salvo localmente."""
    from .professor import Advice

    if not records:
        return list(advices)

    target_polymers = {
        _base_polymer(str(cfg.get("filament_type", [""])[0] if isinstance(cfg.get("filament_type"), (list, tuple)) else cfg.get("filament_type", "")))
        for cfg in plan.filament_settings
    }
    matching = [
        rec for rec in records
        if _base_polymer(rec.target_material) in target_polymers or rec.purpose == goal.purpose
    ]
    if not matching:
        return list(advices)

    issues: dict[str, int] = {}
    for rec in matching:
        if rec.visual_result != "aprovado":
            issues[rec.visual_result] = issues.get(rec.visual_result, 0) + 1
    if not issues:
        return list(advices)

    extra: list[Advice] = []
    if issues.get("empenou_soltou"):
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Histórico local: risco recorrente de empenamento/descolamento",
            why=(
                f"{issues['empenou_soltou']} impressão(ões) anterior(es) neste ambiente/material "
                "relatou(aram) empenamento ou descolamento da mesa."
            ),
            expected_effect="Alertar para reforçar limpeza da placa, pré-aquecimento ou brim/abas.",
            what_to_check="Faça peça de teste pequena antes da peça final e confira a 1ª camada.",
            evidence_class="estimado_regra_ia",
            requires_physical_test=True,
            confidence="media",
            default_on=False,
        ))
    if issues.get("articulacao_colou"):
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Histórico local: travamento anterior em articulações",
            why=f"{issues['articulacao_colou']} impressão(ões) anterior(es) travou(aram) folgas/encaixes.",
            expected_effect="Evitar repetir brim/excesso de fluxo na 1ª camada sem testar folga antes.",
            what_to_check="Teste um trecho curto/anel de folga ou ajuste compensação de pé de elefante.",
            evidence_class="estimado_regra_ia",
            requires_physical_test=True,
            confidence="media",
            default_on=False,
        ))
    if issues.get("fragil_quebrou"):
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Histórico local: falha mecânica anterior registrada",
            why=(
                f"{issues['fragil_quebrou']} registro(s) anterior(es) relatou(aram) quebra ou delaminação. "
                "Apenas aumentar paredes/infill não resolve tração perpendicular às camadas."
            ),
            expected_effect="Evitar presumir resistência sem rever orientação da peça e ensaio físico.",
            what_to_check="Gire a peça para alinhar a carga ao plano XY e faça teste de carga real.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence="baixa",
            default_on=False,
        ))
    if issues.get("acabamento_ruim"):
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Histórico local: acabamento superficial abaixo do esperado",
            why=f"{issues['acabamento_ruim']} registro(s) anterior(es) indicou(aram) perda visual de superfície.",
            expected_effect="Reforçar uso de prioridade 'Qualidade visual' e conferência de velocidade externa.",
            what_to_check="Compare torre/peça teste com parede externa reduzida antes do lote.",
            evidence_class="estimado_regra_ia",
            requires_physical_test=True,
            confidence="media",
            default_on=False,
        ))
    if issues.get("folga_apertada"):
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Histórico local: folga apertada após resfriamento",
            why=f"{issues['folga_apertada']} registro(s) relatou(aram) encaixe apertado após contração.",
            expected_effect="Lembrar calibração de compensação XY / escala leve após teste físico.",
            what_to_check="Imprima apenas o pino/rosca de teste e meça com paquímetro/encaixe real.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=True,
            confidence="media",
            default_on=False,
        ))

    existing_titles = {a.title.lower() for a in advices}
    merged = list(advices)
    for item in extra:
        if item.title.lower() not in existing_titles:
            merged.append(item)
    return merged
