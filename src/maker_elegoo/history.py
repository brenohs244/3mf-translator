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
    filament_brand: str = ""
    profile_name: str = ""
    measured_bar_mm: float | None = None
    fitted_clearance_mm: float | None = None


@dataclass(frozen=True)
class ValidatedRecipeSummary:
    """Receita física aprovada localmente pelo usuário em impressões anteriores."""

    polymer: str
    filament_brand: str
    profile_name: str
    nozzle_mm: str
    approved_count: int
    avg_shrinkage_pct: float | None
    recommended_filament_shrink: str | None
    best_clearance_mm: float | None
    sample_params: dict[str, str]


def history_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return settings_path().parent / "print_feedback_history.json"


def _parse_opt_float(val: object) -> float | None:
    if val in (None, ""):
        return None
    try:
        num = float(val)  # type: ignore[arg-type]
        return num if num == num else None
    except (TypeError, ValueError):
        return None


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
                filament_brand=str(item.get("filament_brand", ""))[:80],
                profile_name=str(item.get("profile_name", ""))[:80],
                measured_bar_mm=_parse_opt_float(item.get("measured_bar_mm")),
                fitted_clearance_mm=_parse_opt_float(item.get("fitted_clearance_mm")),
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
        filament_brand=record.filament_brand[:80],
        profile_name=record.profile_name[:80],
        measured_bar_mm=record.measured_bar_mm,
        fitted_clearance_mm=record.fitted_clearance_mm,
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


def find_validated_recipes(
    records: list[FeedbackRecord] | tuple[FeedbackRecord, ...],
    target_material: str,
    *,
    nozzle_mm: str | None = None,
    purpose: str | None = None,
    filament_brand: str = "",
) -> list[ValidatedRecipeSummary]:
    """Agrupa impressões aprovadas localmente por polímero/marca/bico/perfil."""
    from .calibration import compute_shrinkage_stats

    target_poly = _base_polymer(target_material)
    brand_lower = filament_brand.strip().lower()
    groups: dict[tuple[str, str, str, str], list[FeedbackRecord]] = {}

    for rec in records:
        if rec.visual_result != "aprovado":
            continue
        poly = _base_polymer(rec.target_material)
        if target_poly and poly != target_poly:
            continue
        if nozzle_mm and rec.nozzle_mm and rec.nozzle_mm != nozzle_mm:
            continue
        if brand_lower and rec.filament_brand and brand_lower not in rec.filament_brand.lower() and rec.filament_brand.lower() not in brand_lower:
            continue
        key = (poly, rec.filament_brand.strip(), rec.profile_name.strip(), rec.nozzle_mm.strip() or "0.4")
        groups.setdefault(key, []).append(rec)

    summaries: list[ValidatedRecipeSummary] = []
    for (poly, brand, prof, nozzle), items in groups.items():
        bars = [r.measured_bar_mm for r in items if r.measured_bar_mm is not None]
        clearances = [r.fitted_clearance_mm for r in items if r.fitted_clearance_mm is not None]
        avg_shrink: float | None = None
        rec_shrink: str | None = None
        if bars:
            avg_bar = sum(bars) / len(bars)
            try:
                stats = compute_shrinkage_stats(avg_bar)
                avg_shrink = stats.shrinkage_pct
                rec_shrink = stats.recommended_filament_shrink
            except ValueError:
                pass
        best_clear = min(clearances) if clearances else None
        latest_params = dict(items[-1].applied_params)
        purpose_hits = sum(1 for r in items if purpose and r.purpose == purpose)
        summaries.append((
            (bool(brand), purpose_hits, len(items), avg_shrink is not None),
            ValidatedRecipeSummary(
                polymer=poly,
                filament_brand=brand,
                profile_name=prof,
                nozzle_mm=nozzle,
                approved_count=len(items),
                avg_shrinkage_pct=avg_shrink,
                recommended_filament_shrink=rec_shrink,
                best_clearance_mm=best_clear,
                sample_params=latest_params,
            ),
        ))

    summaries.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in summaries]


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

    extra: list[Advice] = []
    nozzle_raw = plan.machine_settings.get("nozzle_diameter", ["0.4"])
    nozzle_str = str(nozzle_raw[0] if isinstance(nozzle_raw, (list, tuple)) else nozzle_raw)
    for slot_idx, cfg in enumerate(plan.filament_settings, 1):
        mat_raw = cfg.get("filament_type", [""])
        mat_str = str(mat_raw[0] if isinstance(mat_raw, (list, tuple)) else mat_raw)
        recipes = find_validated_recipes(records, mat_str, nozzle_mm=nozzle_str, purpose=goal.purpose)
        if not recipes:
            continue
        best = recipes[0]
        brand_txt = f" ({best.filament_brand})" if best.filament_brand else ""
        detail_parts = [f"{k}={v}" for k, v in list(best.sample_params.items())[:4]]
        if best.avg_shrinkage_pct is not None:
            detail_parts.append(f"contração medida ~{best.avg_shrinkage_pct:.2f}%")
        if best.best_clearance_mm is not None:
            detail_parts.append(f"menor folga livre {best.best_clearance_mm:.2f} mm")
        extra.append(Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title=f"Receita validada fisicamente pelo usuário ({best.polymer}{brand_txt})",
            why=(
                f"Você já aprovou {best.approved_count} impressão(ões) local(is) com bico {best.nozzle_mm} mm"
                + (f" ({best.profile_name})" if best.profile_name else "")
                + (": " + ", ".join(detail_parts) if detail_parts else "")
                + ". Referência da sua própria impressora — lote e umidade ainda podem variar."
            ),
            expected_effect="Reaproveitar parâmetros que funcionaram fisicamente neste equipamento.",
            what_to_check="Confirme se o lote/marca do carretel atual é o mesmo da receita.",
            evidence_class="depende_teste_fisico",
            requires_physical_test=False,
            confidence="alta",
            default_on=False,
        ))
        if best.avg_shrinkage_pct is not None and abs(best.avg_shrinkage_pct) >= 0.15:
            scale_pct = round(10000.0 / (100.0 - best.avg_shrinkage_pct), 2)
            extra.append(Advice(
                scope="alert",
                slot=None,
                key="",
                current="100%",
                proposed=f"{scale_pct:.2f}%",
                title=f"Contração medida no histórico ({best.polymer}{brand_txt}): considere Escala {scale_pct:.2f}%",
                why=(
                    f"Suas medições salvas na barra de 50 mm mostram contração média de {best.avg_shrinkage_pct:.2f}% "
                    f"(equivalente a {best.recommended_filament_shrink} no perfil). Como o CLI do ELEGOO Slicer não aplica `filament_shrink` isolado nos percursos, "
                    f"use 'Detalhes avançados → Tamanho → Escala (%) = {scale_pct:.2f}%' quando precisão XY for crítica."
                ),
                expected_effect="Reescala a malha de entrada de forma verificável no G-code.",
                what_to_check="Meça uma nova peça de calibração após ajustar a escala se trocar de lote.",
                evidence_class="estimado_regra_ia",
                requires_physical_test=True,
                confidence="media",
                default_on=False,
            ))
        if (best.best_clearance_mm is not None and best.best_clearance_mm >= 0.25
                and goal.fit_clearance in {"encaixe_justo", "partes_moveis"}):
            cur_hole = str(plan.process_settings.get("xy_hole_compensation", "0"))
            try:
                hole_val = float(cur_hole)
            except ValueError:
                hole_val = 0.0
            if hole_val < 0.05 and "xy_hole_compensation" in plan.process_settings:
                extra.append(Advice(
                    scope="process",
                    slot=None,
                    key="xy_hole_compensation",
                    current=cur_hole,
                    proposed="0.08",
                    title=f"Alívio em furos/encaixes pela calibração local ({best.polymer}{brand_txt})",
                    why=(
                        f"Na peça de folgas anterior apenas a janela >= {best.best_clearance_mm:.2f} mm deslizou livre. "
                        "Adicionar +0.08 mm em `xy_hole_compensation` abre furos sem alterar dimensões externas."
                    ),
                    expected_effect="Folga ligeiramente mais solta em pinos e furos na 1ª tentativa (verificada em G-code).",
                    what_to_check="Valide com pino de teste antes de imprimir montagens completas.",
                    evidence_class="estimado_regra_ia",
                    requires_physical_test=True,
                    confidence="media",
                    default_on=False,
                ))

    issues: dict[str, int] = {}
    for rec in matching:
        if rec.visual_result != "aprovado":
            issues[rec.visual_result] = issues.get(rec.visual_result, 0) + 1
    if not issues and not extra:
        return list(advices)
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
        title_key = item.title.lower()
        if title_key not in existing_titles:
            existing_titles.add(title_key)
            merged.append(item)
    return merged
