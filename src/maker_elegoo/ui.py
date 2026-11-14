"""Interface desktop para inspeção, seleção de perfis e conversão."""

from __future__ import annotations

import queue
import json
import base64
import subprocess
import tempfile
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
from zipfile import ZipFile

from .ai import (AIError, Suggestion, apply_suggestions, build_manual_prompt,
                 parse_manual_response, suggest_equivalences)
from .ai_client import GeminiClient, GeminiClientError, advise_gemini
from .converter import ConversionResult, convert_project
from .codex_cli import run_codex
from .codex_evidence import (build_codex_evidence,
                             validate_codex_recommendations, verify_process_recommendation)
from .credentials import clear_gemini_key, get_gemini_key, save_gemini_key
from .history import (
    VISUAL_RESULTS,
    FeedbackRecord,
    append_feedback_record,
    adjust_advices_from_history,
    clear_feedback_history,
    load_feedback_history,
)
from .labels import (
    CRITICALITY_LABELS,
    FIT_LABELS,
    HEAT_EXPOSURE_LABELS,
    LOAD_TYPE_LABELS,
    PRIORITY_LABELS,
    PURPOSE_LABELS,
    confidence_label,
    criticality_code,
    criticality_label,
    describe_change,
    evidence_label,
    fit_code,
    fit_label,
    format_duration,
    heat_exposure_code,
    heat_exposure_label,
    load_type_code,
    load_type_label,
    priority_code,
    priority_label,
    purpose_code,
    purpose_label,
)
from .mapping import ConversionPlan, build_conversion, suggest_process
from .orientation import FRONTS, load_scene, render_front_views
from .orientation_service import (OrientationAnalysis, apply_orientation,
                                  evaluate_orientations)
from .optimization import compare_objectives, format_objective_comparison
from .professor import (
    Advice,
    PrintGoal,
    advise_offline,
    apply_advice,
    build_preconversion_card,
    build_print_summary,
    goal_confidence,
    merge_with_offline_alerts,
    needs_user_intervention,
)
from .profiles import Profile, ProfileError, SlicerInstall, discover_slicer, list_profiles, resolve_profile
from .project import ProjectInfo, inspect_project
from .scale import RescaleResult, ScaleError, analyze_scale_risk, rescale_3mf
from .settings import load_settings, save_settings
from .slicer import SlicerCLI, next_available_destination


def format_plate_color_guide(plates: tuple | list, filaments: tuple | list) -> list[str]:
    if not plates:
        return []
    fil_by_slot = {str(getattr(f, "slot", i)): f for i, f in enumerate(filaments, 1)}
    lines = ["", "Guia por Placa & Troca de Cores:"]
    for plate in plates:
        slots = tuple(dict.fromkeys(
            s for s in ((getattr(plate, "used_filament_slots", ()) or getattr(plate, "filament_slots", ())))
            if s and s != "0"
        ))
        slot_desc = []
        for slot in slots:
            info = fil_by_slot.get(str(slot))
            if info and hasattr(info, "material"):
                slot_desc.append(f"{slot} ({info.material} {info.color})")
            elif info and hasattr(info, "name"):
                slot_desc.append(f"{slot} ({info.name})")
            else:
                slot_desc.append(str(slot))
        paint_tag = " [pintura multicolorida]" if getattr(plate, "has_paint_color", False) else ""
        color_text = ", ".join(slot_desc) if slot_desc else "padrão (slot 1)"
        lines.append(f"  Placa {plate.number}: {plate.instance_count} instância(s) · Cores: {color_text}{paint_tag}")
        if len(slots) > 4:
            lines.append(f"    ⚠ Atenção: {len(slots)} cores na mesma placa (Canvas ECC2 aceita 4 automáticas; extras exigem troca manual).")
    return lines


def format_project_summary(project: ProjectInfo) -> str:
    lines = [f"Arquivo: {project.path.name}",
             f"Origem: {project.source_settings.get('printer_model', 'desconhecida')}"]
    layer = project.source_settings.get("layer_height")
    if layer:
        lines.append(f"Altura de camada original: {layer} mm")
    lines.extend([
        f"{len(project.plates)} placas · {len(project.objects)} objetos · {len(project.filaments)} filamentos",
        "Filamentos:",
    ])
    used = set(getattr(project, "used_filament_slots", ()) or ())
    for filament in project.filaments:
        unused_note = " (não usado nas placas)" if used and str(filament.slot) not in used else ""
        lines.append(f"  {filament.slot}. {filament.material} {filament.color} ({filament.profile or 'sem perfil'}){unused_note}")
    lines.extend(format_plate_color_guide(project.plates, project.filaments))
    geom = getattr(project, "geometry_summary", None)
    if geom is not None and getattr(geom, "triangle_count", 0) > 0:
        lines.append(
            f"Geometria: {geom.triangle_count:,} triângulos · "
            f"{geom.size_x:.1f} × {geom.size_y:.1f} × {geom.size_z:.1f} mm · "
            f"Apoio: {geom.contact_mm2:.0f} mm² · Overhang >45°: {geom.overhang_mm2:.0f} mm²"
        )
        if geom.has_slender_parts:
            lines.append("  ⚠ Parte pequena/esguia detectada: atenção à adesão na mesa.")
    advanced = getattr(project, "advanced_features", ())
    if advanced:
        lines.extend(["Recursos avançados detectados (confira após abrir no Slicer):",
                      *(f"  • {item}" for item in advanced)])
    if project.warnings:
        lines.extend(["Avisos:", *(f"  • {warning}" for warning in project.warnings)])
    return "\n".join(lines)


def format_conversion_report(result: ConversionResult, plan: ConversionPlan,
                             *, professor_advices: tuple | list = (),
                             rescale_info: RescaleResult | None = None) -> str:
    lines = ["CONVERSÃO CONCLUÍDA" if result.success else "CONVERSÃO COM FALHA",
             result.message, "", f"Destino: {result.destination}",
             f"Máquina: {plan.machine.name}", f"Processo: {plan.process.name}",
             "Filamentos:"]
    lines.extend(f"  {index}. {profile.name}" for index, profile in enumerate(plan.filaments, 1))
    if rescale_info is not None:
        ox, oy, oz = rescale_info.original_size_mm
        nx, ny, nz = rescale_info.new_size_mm
        lines.extend([
            "",
            f"Redimensionamento uniforme: {rescale_info.scale_factor * 100:.1f}% "
            f"({ox:.1f}×{oy:.1f}×{oz:.1f} mm → {nx:.1f}×{ny:.1f}×{nz:.1f} mm)",
        ])
        if rescale_info.removed_variable_layer:
            lines.append("  • Curva antiga de altura variável removida por mudança de altura Z.")
        lines.extend(f"  • Aviso de escala: {w}" for w in rescale_info.risk.warnings)
    applied = [item for item in professor_advices if item.scope != "alert"]
    alerts = [item for item in professor_advices if item.scope == "alert"]
    if applied:
        lines.extend(["", "O Professor ajustou:"])
        for item in applied:
            lines.append(f"  • {describe_change(item.key, item.current, item.proposed)}")
            if item.why:
                lines.append(f"    Por quê: {item.why}")
            if getattr(item, "expected_effect", ""):
                lines.append(f"    Efeito esperado: {item.expected_effect}")
            if getattr(item, "what_to_check", ""):
                lines.append(f"    O que conferir: {item.what_to_check}")
    if alerts:
        lines.extend(["", "Atenção (avisos do Professor):"])
        for item in alerts:
            phys_tag = " [Depende de teste físico]" if getattr(item, "requires_physical_test", False) else ""
            lines.append(f"  • {item.title}{phys_tag}: {item.why}")
            if getattr(item, "what_to_check", ""):
                lines.append(f"    O que conferir: {item.what_to_check}")
    lines.extend(["", f"Parâmetros de processo transferidos: {len(plan.transferred)}",
                  f"Campos sem equivalência confirmada: {len(result.unmapped)}"])
    if result.geometry:
        lines.append("Malhas: " + ("preservadas (tolerância de 0,0001 mm)" if result.geometry.unchanged
                                     else "diferenças detectadas; confira antes de imprimir"))
    if result.output_project:
        lines.extend(["", "Placas e instâncias (origem → saída):"])
        for original, converted in zip(getattr(result, "source_plates", ()) or (), result.output_project.plates):
            lines.append(f"  Placa {original.number}: {original.instance_count} → {converted.instance_count}")
            if original.object_ids and converted.object_ids:
                lines.append(f"    IDs de objetos: {', '.join(original.object_ids)} → {', '.join(converted.object_ids)}")
        lines.extend(format_plate_color_guide(result.output_project.plates, result.output_project.filaments))
        lines.extend(["", "Filamentos (perfil selecionado → saída):"])
        for original, converted in zip(plan.filaments, result.output_project.filaments):
            lines.append(f"  {converted.slot}. {original.name} → {converted.material} {converted.color}")
        lines.append("Pintura, suportes manuais e modificadores: conferência visual necessária no Slicer.")
    if result.validation:
        lines.append(f"Fatiamento: {result.validation.plate_count} placas verificadas")
        if result.validation.estimated_seconds is not None:
            lines.append(f"Tempo total estimado: {format_duration(result.validation.estimated_seconds)}")
        if result.validation.filament_grams is not None:
            lines.append(f"Material estimado: {result.validation.filament_grams:.2f} g")
        for pm in (getattr(result.validation, "plate_metrics", ()) or ()):
            grams_txt = f"{pm.filament_grams:.2f} g" if pm.filament_grams is not None else "n/d"
            lines.append(f"  Placa {pm.plate}: {format_duration(pm.estimated_seconds)} · {grams_txt}")
        lines.extend(f"Aviso do fatiador: {warning}" for warning in result.validation.warnings)
    if plan.material_findings:
        lines.extend(["", "Mudanças de material/perfil:"])
        lines.extend(f"  Filamento {item.slot}: {describe_change(item.key, item.source, item.target)}"
                     for item in plan.material_findings)
    speed_warnings = []
    for key in ("outer_wall_speed", "inner_wall_speed", "top_surface_speed"):
        src_raw = plan.replaced.get(key)
        dst_raw = plan.process_settings.get(key)
        if src_raw is None or dst_raw is None:
            continue
        try:
            src_val = float(str(src_raw[0] if isinstance(src_raw, (list, tuple)) else src_raw))
            dst_val = float(str(dst_raw[0] if isinstance(dst_raw, (list, tuple)) else dst_raw))
        except (TypeError, ValueError, IndexError):
            continue
        if dst_val - src_val >= 30.0 and dst_val >= src_val * 1.25:
            speed_warnings.append(
                f"  • {describe_change(key, f'{src_val:g}', f'{dst_val:g}')} "
                "(o perfil ELEGOO é mais rápido que o original; se notar perda de acabamento, use a prioridade 'Qualidade visual')"
            )
    if speed_warnings:
        lines.extend(["", "Atenção (aumento de velocidade do perfil ELEGOO):", *speed_warnings])
    if result.unmapped:
        lines.extend(["", "Detalhes técnicos (campos não mapeados - primeiros 30):"])
        lines.extend(f"  • {key}" for key in list(sorted(result.unmapped))[:30])

    # 4 classes obrigatórias de evidência em toda conclusão
    slice_evidence = (
        f"{result.validation.plate_count} placa(s) fatiada(s) no ELEGOO Slicer "
        f"({format_duration(result.validation.estimated_seconds)})"
        if result.validation and result.validation.success
        else "fatiamento não validado / falhou"
    )
    geom_evidence = (
        "malhas preservadas (tolerância 0,0001 mm)"
        if result.geometry and result.geometry.unchanged
        else "estrutura de placas e parâmetros extraídos do arquivo"
    )
    lines.extend([
        "",
        "Classes de evidência:",
        f"  • {evidence_label('verificado_3mf')}: {geom_evidence}; {len(plan.transferred)} campos transferidos.",
        f"  • {evidence_label('verificado_fatiamento')}: {slice_evidence}.",
        f"  • {evidence_label('estimado_regra_ia')}: {len(applied)} ajuste(s) sugerido(s) aplicados; {len(plan.material_findings)} troca(s) de material.",
        f"  • {evidence_label('depende_teste_fisico')}: {len(alerts)} aviso(s)/checagem(ns). Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica.",
    ])
    lines.extend(["", "Confira a posição das peças, cores, suportes e prévia no ELEGOO Slicer antes de imprimir."])
    return "\n".join(lines)


def _resolve_existing_destination(
    destination: Path,
    *,
    ask_action=messagebox.askyesnocancel,
    parent=None,
) -> Path | None:
    """Trata destino já existente oferecendo sobrescrever, gerar sufixo ou cancelar."""
    destination = Path(destination)
    if not destination.exists():
        return destination
    suggested = next_available_destination(destination)
    choice = ask_action(
        "Destino existente",
        f"O arquivo '{destination.name}' já existe.\n\n"
        f"Sim = Sobrescrever arquivo existente\n"
        f"Não = Salvar com novo nome ({suggested.name})\n"
        "Cancelar = Abortar conversão",
        parent=parent,
    )
    if choice is None:
        return None
    if choice is False:
        return suggested
    destination.unlink()
    return destination


def format_orientation_analysis(analysis: OrientationAnalysis) -> str:
    def describe(entry):
        candidate, result = entry.candidate, entry.result
        validation = result.validation
        lines = [f"{candidate.label}: {'fatiamento validado' if result.success else 'falha no fatiamento'}",
                 f"  Apoio estimado: {candidate.contact_mm2:.0f} mm²; risco frontal estimado: {candidate.front_overhang_mm2:.0f} mm²"]
        if validation and validation.estimated_seconds is not None:
            minutes = round(validation.estimated_seconds / 60)
            lines.append(f"  Tempo estimado: {minutes // 60}h {minutes % 60:02d}min")
        else:
            lines.append("  Tempo estimado: indisponível")
        if validation and validation.filament_grams is not None:
            lines.append(f"  Filamento estimado: {validation.filament_grams:.2f} g")
        else:
            lines.append("  Filamento estimado: indisponível")
        if not result.success:
            lines.append(f"  Motivo: {result.message}")
        return lines

    lines = [f"Frente selecionada: {analysis.front}",
             f"Recomendação: {analysis.recommended.label}", analysis.reason, "",
             "Posição atual:", *describe(analysis.current)]
    for entry in analysis.alternatives:
        lines.extend(["", "Alternativa:", *describe(entry)])
    if analysis.rejected:
        lines.extend(["", "Posições descartadas na triagem geométrica:"])
        lines.extend(f"  {item.label}: {item.reason}; apoio estimado {item.contact_mm2:.0f} mm²"
                     for item in analysis.rejected)
    lines.extend(["", "Confira rosto, suportes e prévia no ELEGOO Slicer antes de imprimir."])
    return "\n".join(lines)


class MakerElegooApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Maker → ELEGOO")
        self.geometry("980x760")
        self.minsize(740, 600)
        self.preferences = load_settings()
        self.project: ProjectInfo | None = None
        self.install: SlicerInstall | None = None
        self.result: ConversionResult | None = None
        self.last_plan: ConversionPlan | None = None
        self.ai_approved: list[Suggestion] = []
        self.machine_profiles: list[Profile] = []
        self.process_profiles: list[Profile] = []
        self.filament_profiles: list[Profile] = []
        self.filament_vars: list[tk.StringVar] = []
        self.worker_queue: queue.Queue = queue.Queue()
        self.ai_queue: queue.Queue = queue.Queue()
        self.professor_queue: queue.Queue = queue.Queue()
        self.orientation_queue: queue.Queue = queue.Queue()
        self.comparison_queue: queue.Queue = queue.Queue()
        self.orientation_cancel = threading.Event()
        self.orientation_dialog: tk.Toplevel | None = None
        self.orientation_analysis: OrientationAnalysis | None = None
        self.orientation_plan: ConversionPlan | None = None
        self.orientation_generation = 0
        self._pending_scale_advices: list[Advice] = []

        self.file_var = tk.StringVar()
        self.nozzle_var = tk.StringVar(value=self.preferences["nozzle"])
        self.machine_var = tk.StringVar(value=self.preferences["machine"])
        self.process_var = tk.StringVar()
        self.physical_material_var = tk.StringVar(value="Não sei informar")
        self.physical_filament_confirmed_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Selecione um projeto 3MF para começar")
        self.ai_provider_var = tk.StringVar(value="Codex")
        self.mode_var = tk.StringVar(value=self.preferences.get("mode", "offline"))
        self.purpose_var = tk.StringVar(value=purpose_label(self.preferences.get("purpose", "decorativa")))
        self.priority_var = tk.StringVar(value=priority_label(self.preferences.get("priority", "equilibrio")))
        self.load_type_var = tk.StringVar(value=load_type_label(self.preferences.get("load_type", "nao_sei")))
        self.criticality_var = tk.StringVar(value=criticality_label(self.preferences.get("criticality", "nao_sei")))
        self.fit_clearance_var = tk.StringVar(value=fit_label(self.preferences.get("fit_clearance", "nao_sei")))
        self.heat_exposure_var = tk.StringVar(value=heat_exposure_label(self.preferences.get("heat_exposure", "nao_sei")))
        self.save_history_var = tk.BooleanVar(value=self.preferences.get("save_print_history", "0") == "1")
        self.advanced_visible = tk.BooleanVar(value=False)
        self.confidence_var = tk.StringVar(value="Confiança: Baixa")
        self.preconversion_var = tk.StringVar(
            value="Escolha um projeto 3MF e confirme o filamento físico carregado na ELEGOO."
        )
        self.ai_model_var = tk.StringVar(value=self.preferences.get("ai_model", "gemini-3.8-flash"))
        self.scale_mode_var = tk.StringVar(value="Original (100%)")
        self.scale_value_var = tk.StringVar(value="")
        self._refreshing_profiles = False
        self._build_layout()
        self.nozzle_var.trace_add("write", lambda *_: self._refresh_profiles())
        self.process_var.trace_add("write", lambda *_: self._profiles_changed())
        for var in (
            self.mode_var,
            self.purpose_var,
            self.priority_var,
            self.load_type_var,
            self.criticality_var,
            self.fit_clearance_var,
            self.heat_exposure_var,
            self.save_history_var,
            self.ai_model_var,
        ):
            var.trace_add("write", lambda *_: self._on_goal_or_pref_changed())
        self.scale_mode_var.trace_add("write", lambda *_: self._on_scale_mode_changed())
        self._refresh_profiles()
        self._update_context_preview()
        self._worker_after = self.after(150, self._poll_worker)
        self._ai_after = self.after(150, self._poll_ai)
        self._professor_after = self.after(150, self._poll_professor)
        self._orientation_after = self.after(150, self._poll_orientation)
        self._comparison_after = self.after(150, self._poll_comparison)

    def destroy(self):
        self.orientation_cancel.set()
        for name in ("_worker_after", "_ai_after", "_professor_after", "_orientation_after", "_comparison_after"):
            callback = getattr(self, name, None)
            if callback is not None:
                self.after_cancel(callback)
        super().destroy()

    def _build_layout(self):
        menu = tk.Menu(self)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Configurar Chave Google Gemini", command=self._configure_gemini_key)
        tools_menu.add_command(label="Ajuste guiado sem API (copiar/colar JSON)", command=self._manual_ai)
        tools_menu.add_command(label="Analisar orientação de figura", command=self._orientation_open)
        tools_menu.add_command(label="Prévia de compatibilidade", command=self._preview_compatibility)
        tools_menu.add_command(label="Salvar relatório", command=self._save_report)
        tools_menu.add_command(label="Comparar objetivos de impressão", command=self._compare_objectives)
        tools_menu.add_command(label="Comparar placas antes/depois", command=self._show_plate_comparison)
        tools_menu.add_command(label="Registrar resultado da impressão (histórico local)", command=self._open_feedback_dialog)
        menu.add_cascade(label="Ferramentas", menu=tools_menu)
        self.configure(menu=menu)
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        self._outer_frame = outer
        ttk.Label(outer, text="Maker → ELEGOO", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Traduza projetos MakerWorld para sua Centauri Carbon 2 com validação real e orientações honestas.",
        ).pack(anchor="w", pady=(2, 10))

        source = ttk.LabelFrame(outer, text="1  Projeto 3MF de origem", padding=10)
        source.pack(fill="x", pady=(0, 8))
        source.columnconfigure(0, weight=1)
        ttk.Entry(source, textvariable=self.file_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(source, text="Escolher 3MF", command=self._choose_file).grid(row=0, column=1)
        ttk.Button(source, text="Analisar", command=self._inspect_file).grid(row=0, column=2, padx=(8, 0))

        printer_simple = ttk.LabelFrame(outer, text="2  Sua ELEGOO e Filamento Físico", padding=10)
        printer_simple.pack(fill="x", pady=(0, 8))
        printer_simple.columnconfigure(3, weight=1)
        ttk.Label(printer_simple, text="Bico instalado:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.nozzle_combo = ttk.Combobox(printer_simple, textvariable=self.nozzle_var, state="readonly", width=7)
        self.nozzle_combo.grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Label(printer_simple, text="Filamento na impressora:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.physical_material_combo = ttk.Combobox(
            printer_simple,
            textvariable=self.physical_material_var,
            state="readonly",
            values=("Não sei informar", "PLA", "PETG", "ABS", "ASA", "ABS-CF", "ASA-CF", "TPU"),
            width=18,
        )
        self.physical_material_combo.grid(row=0, column=3, sticky="w")
        self.physical_material_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_physical_filament_changed())
        self.physical_confirm_chk = ttk.Checkbutton(
            printer_simple,
            text="Confirmo que este filamento físico está carregado (nunca presumir pelo 3MF)",
            variable=self.physical_filament_confirmed_var,
            command=self._on_physical_filament_changed,
        )
        self.physical_confirm_chk.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        consultant = ttk.LabelFrame(outer, text="3  Professor de Impressão e Cartão Pré-Conversão", padding=10)
        consultant.pack(fill="x", pady=(0, 8))
        consultant.columnconfigure(1, weight=1)
        consultant.columnconfigure(3, weight=1)

        ttk.Label(consultant, text="Uso da Peça:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.purpose_combo = ttk.Combobox(consultant, textvariable=self.purpose_var, state="readonly",
                                          values=tuple(PURPOSE_LABELS.values()))
        self.purpose_combo.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(consultant, text="Prioridade:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.priority_combo = ttk.Combobox(consultant, textvariable=self.priority_var, state="readonly",
                                           values=tuple(PRIORITY_LABELS.values()))
        self.priority_combo.grid(row=0, column=3, sticky="ew")

        ttk.Label(consultant, text="Carga principal:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.load_type_combo = ttk.Combobox(consultant, textvariable=self.load_type_var, state="readonly",
                                            values=tuple(LOAD_TYPE_LABELS.values()))
        self.load_type_combo.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 10))
        ttk.Label(consultant, text="Criticidade:").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        self.criticality_combo = ttk.Combobox(consultant, textvariable=self.criticality_var, state="readonly",
                                              values=tuple(CRITICALITY_LABELS.values()))
        self.criticality_combo.grid(row=1, column=3, sticky="ew", pady=(6, 0))

        ttk.Label(consultant, text="Encaixes / Folgas:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.fit_clearance_combo = ttk.Combobox(consultant, textvariable=self.fit_clearance_var, state="readonly",
                                                values=tuple(FIT_LABELS.values()))
        self.fit_clearance_combo.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(0, 10))
        ttk.Label(consultant, text="Calor / Sol / Água:").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        self.heat_exposure_combo = ttk.Combobox(consultant, textvariable=self.heat_exposure_var, state="readonly",
                                                values=tuple(HEAT_EXPOSURE_LABELS.values()))
        self.heat_exposure_combo.grid(row=2, column=3, sticky="ew", pady=(6, 0))

        self.confidence_label = ttk.Label(consultant, textvariable=self.confidence_var, foreground="#333333")
        self.confidence_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 2))
        self.preconversion_label = ttk.Label(
            consultant,
            textvariable=self.preconversion_var,
            wraplength=900,
            justify="left",
            foreground="#1F3A52",
        )
        self.preconversion_label.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(2, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 8))
        self.convert_button = ttk.Button(actions, text="Traduzir para minha ELEGOO", command=self._convert)
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Abrir no ELEGOO Slicer", command=self._open_result, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))
        self.feedback_button = ttk.Button(actions, text="Registrar resultado da impressão", command=self._open_feedback_dialog)
        self.feedback_button.pack(side="left", padx=(8, 0))
        self.advanced_toggle_btn = ttk.Button(actions, text="Mostrar detalhes avançados ▾", command=self._toggle_advanced)
        self.advanced_toggle_btn.pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        # Painel retrátil de Detalhes Avançados (recolhido por padrão, mas todos controles instanciados)
        self.advanced_frame = ttk.LabelFrame(outer, text="Detalhes avançados (perfis, filamentos por slot, escala e IA)", padding=10)
        target = ttk.Frame(self.advanced_frame)
        target.pack(fill="x", pady=(0, 6))
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="Impressora").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.machine_combo = ttk.Combobox(target, textvariable=self.machine_var, state="readonly")
        self.machine_combo.grid(row=0, column=1, sticky="ew")
        self.machine_combo.bind("<<ComboboxSelected>>", lambda *_: self._refresh_dependents())
        ttk.Label(target, text="Processo").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self.process_combo = ttk.Combobox(target, textvariable=self.process_var, state="readonly")
        self.process_combo.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(target, text="Localizar ELEGOO Slicer", command=self._choose_slicer).grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self.filament_frame = ttk.Frame(target)
        self.filament_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.filament_frame.columnconfigure(1, weight=1)

        adv_opts = ttk.Frame(self.advanced_frame)
        adv_opts.pack(fill="x", pady=(4, 0))
        adv_opts.columnconfigure(1, weight=1)
        adv_opts.columnconfigure(3, weight=1)
        ttk.Label(adv_opts, text="Modo Professor:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        mode_box = ttk.Frame(adv_opts)
        mode_box.grid(row=0, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(mode_box, text="100% Offline (Regras Locais)", variable=self.mode_var, value="offline").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(mode_box, text="Professor IA (Google Gemini)", variable=self.mode_var, value="ai").pack(side="left", padx=(0, 10))
        ttk.Button(mode_box, text="Chave Gemini...", command=self._configure_gemini_key).pack(side="left")
        ttk.Checkbutton(
            mode_box,
            text="Salvar histórico local de impressões neste PC",
            variable=self.save_history_var,
        ).pack(side="left", padx=(10, 0))

        ttk.Label(adv_opts, text="Tamanho:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.scale_mode_combo = ttk.Combobox(
            adv_opts,
            textvariable=self.scale_mode_var,
            state="readonly",
            values=("Original (100%)", "Escala (%)", "Altura Z (mm)"),
        )
        self.scale_mode_combo.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 10))
        ttk.Label(adv_opts, text="Valor:").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        scale_val_box = ttk.Frame(adv_opts)
        scale_val_box.grid(row=1, column=3, sticky="ew", pady=(6, 0))
        self.scale_value_entry = ttk.Entry(scale_val_box, textvariable=self.scale_value_var, width=10, state="disabled")
        self.scale_value_entry.pack(side="left")
        ttk.Label(scale_val_box, text="ex.: 80 (mm) ou 50 (%)", foreground="#555555").pack(side="left", padx=(8, 0))

        adv_actions = ttk.Frame(self.advanced_frame)
        adv_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(adv_actions, text="Comparar 5 alternativas", command=self._compare_objectives).pack(side="left")
        self.orientation_button = ttk.Button(adv_actions, text="Orientação de figura", command=self._orientation_open, state="disabled")
        self.orientation_button.pack(side="left", padx=(8, 0))
        self.ai_button = ttk.Button(adv_actions, text="Analisar orientação/suportes (Codex / IA)", command=self._analyze_ai, state="disabled")
        self.ai_button.pack(side="left", padx=(8, 0))
        ttk.Combobox(adv_actions, textvariable=self.ai_provider_var, values=("Codex", "Gemini"),
                     state="readonly", width=8).pack(side="left", padx=(5, 0))

        self.report_frame = ttk.LabelFrame(outer, text="4  Análise e relatório", padding=8)
        self.report_frame.pack(fill="both", expand=True)
        self.report = scrolledtext.ScrolledText(self.report_frame, wrap="word", font=("Consolas", 10), state="disabled")
        self.report.pack(fill="both", expand=True)
        self._set_report("O arquivo original permanece intacto. O G-code de validação é temporário e nunca é enviado à impressora.")

    def _set_report(self, content: str):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", content)
        self.report.configure(state="disabled")

    def _save_report(self):
        content = self.report.get("1.0", "end-1c")
        destination = filedialog.asksaveasfilename(
            title="Salvar relatório local", defaultextension=".txt",
            filetypes=[("Texto", "*.txt")])
        if destination:
            Path(destination).write_text(content, encoding="utf-8")

    def _preview_compatibility(self):
        if not self.project or not self.install:
            messagebox.showinfo("Dados incompletos", "Analise um 3MF e selecione os perfis primeiro.")
            return
        try:
            machine, process, filaments = self._selected_profiles()
            plan = build_conversion(self.project, self.install, machine, process, filaments)
        except (ValueError, IndexError, StopIteration, ProfileError) as exc:
            messagebox.showerror("Prévia", str(exc))
            return
        lines = ["PRÉVIA DE COMPATIBILIDADE", format_project_summary(self.project), "",
                 f"Transferidos: {len(plan.transferred)}", *
                 (f"  {key} = {value}" for key, value in sorted(plan.transferred.items())),
                 f"Substituídos pelo perfil ELEGOO: {len(plan.replaced)}", *
                 (f"  {key}" for key in sorted(plan.replaced)),
                 f"Sem equivalência confirmada: {len(plan.unmapped)}", *
                 (f"  {key}" for key in sorted(plan.unmapped))]
        self._set_report("\n".join(lines))

    def _compare_objectives(self):
        if not self.project or not self.install:
            messagebox.showinfo("Dados incompletos", "Analise um 3MF e selecione os perfis primeiro.")
            return
        folder = filedialog.askdirectory(title="Pasta nova para as variantes")
        if not folder:
            return
        try:
            machine, process, filaments = self._selected_profiles()
            plan = build_conversion(self.project, self.install, machine, process, filaments)
        except (ValueError, IndexError, StopIteration, ProfileError) as exc:
            messagebox.showerror("Comparação", str(exc))
            return
        project, install = self.project, self.install
        self.status_var.set("Fatiando variantes...")

        def work():
            try:
                variants = compare_objectives(project, plan, Path(folder), SlicerCLI(install.executable))
                self.comparison_queue.put((variants, None))
            except Exception as exc:
                self.comparison_queue.put((None, exc))

        threading.Thread(target=work, daemon=True).start()

    def _show_plate_comparison(self):
        if not self.project or not self.result or not self.result.output_project:
            messagebox.showinfo("Comparação", "Converta um projeto para comparar as placas.")
            return
        window = tk.Toplevel(self)
        window.title("Placas: origem e saída")
        window.geometry("850x700")
        previews = ttk.Frame(window)
        previews.pack(fill="x", padx=12, pady=8)
        window._plate_images = []
        for row, plate in enumerate(self.project.plates):
            for column, (label, project) in enumerate((("Origem", self.project),
                                                        ("ELEGOO", self.result.output_project))):
                ttk.Label(previews, text=f"Placa {plate.number} · {label}").grid(row=2 * row, column=column, padx=12)
                try:
                    with ZipFile(project.path) as archive:
                        name = f"Metadata/plate_{plate.number}.png"
                        if name in archive.namelist() and archive.getinfo(name).file_size <= 5_000_000:
                            photo = tk.PhotoImage(data=base64.b64encode(archive.read(name)).decode("ascii"))
                            factor = max(1, (max(photo.width(), photo.height()) + 249) // 250)
                            photo = photo.subsample(factor)
                            window._plate_images.append(photo)
                            ttk.Label(previews, image=photo).grid(row=2 * row + 1, column=column, padx=12)
                        else:
                            ttk.Label(previews, text="Prévia indisponível").grid(row=2 * row + 1, column=column)
                except (OSError, tk.TclError):
                    ttk.Label(previews, text="Prévia indisponível").grid(row=2 * row + 1, column=column)
        columns = ("placa", "origem", "saida", "estado")
        table = ttk.Treeview(window, columns=columns, show="headings")
        for column, label in zip(columns, ("Placa", "Origem", "ELEGOO", "Verificação")):
            table.heading(column, text=label)
            table.column(column, width=90 if column == "placa" else 230)
        for before, after in zip(self.project.plates, self.result.output_project.plates):
            table.insert("", "end", values=(before.number,
                f"{before.instance_count} instâncias; IDs {', '.join(before.object_ids)}",
                f"{after.instance_count} instâncias; IDs {', '.join(after.object_ids)}",
                "contagem igual" if before.instance_count == after.instance_count else "diferença"))
        table.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(window, text="IDs podem mudar na exportação. Confira posição, pintura, cores e suportes no ELEGOO Slicer.").pack(padx=12, pady=(0, 12))

    def _poll_comparison(self):
        try:
            variants, error = self.comparison_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            if error:
                self.status_var.set("Falha na comparação")
                self._set_report(str(error))
            else:
                history_records = load_feedback_history() if self.save_history_var.get() else ()
                report_text = format_objective_comparison(
                    variants,
                    goal=self._current_goal(),
                    history_records=history_records,
                )
                self._set_report(report_text)
                self.status_var.set("Comparação concluída")
        self._comparison_after = self.after(150, self._poll_comparison)

    def _current_goal(self) -> PrintGoal:
        raw_phys = self.physical_material_var.get().strip()
        phys = "nao_sei" if raw_phys in {"", "Não sei informar"} else raw_phys
        return PrintGoal(
            purpose=purpose_code(self.purpose_var.get()),
            priority=priority_code(self.priority_var.get()),
            load_type=load_type_code(self.load_type_var.get()),
            criticality=criticality_code(self.criticality_var.get()),
            fit_clearance=fit_code(self.fit_clearance_var.get()),
            heat_exposure=heat_exposure_code(self.heat_exposure_var.get()),
            physical_material=phys,
        )

    def _build_current_plan(self, machine: Profile, process: Profile, filaments: list[Profile]) -> ConversionPlan:
        return build_conversion(self.project, self.install, machine, process, filaments)

    def _toggle_advanced(self):
        show = not self.advanced_visible.get()
        self.advanced_visible.set(show)
        if show:
            self.advanced_frame.pack(fill="x", pady=(0, 8), before=self.report_frame)
            self.advanced_toggle_btn.configure(text="Ocultar detalhes avançados ▴")
        else:
            self.advanced_frame.pack_forget()
            self.advanced_toggle_btn.configure(text="Mostrar detalhes avançados ▾")

    def _on_goal_or_pref_changed(self):
        self._save_preferences()
        self._update_context_preview()

    def _on_physical_filament_changed(self):
        raw_mat = self.physical_material_var.get().strip()
        if (
            raw_mat not in {"", "Não sei informar"}
            and self.project is not None
            and self.filament_profiles
            and self.filament_vars
        ):
            options = [p.name for p in self.filament_profiles]
            target_upper = raw_mat.upper()
            matched = (
                next((name for name in options if name.upper() == f"ELEGOO {target_upper} @ECC2"), None)
                or next((name for name in options if target_upper in name.upper() and "@ECC2" in name.upper()), None)
                or next((name for name in options if target_upper in name.upper()), None)
            )
            if matched:
                used = {
                    str(s) for s in (getattr(self.project, "used_filament_slots", ()) or ())
                    if s and str(s) != "0"
                }
                for idx, var in enumerate(self.filament_vars, 1):
                    if not used or str(idx) in used:
                        if var.get() != matched:
                            var.set(matched)
        self._update_context_preview()

    def _update_context_preview(self):
        goal = self._current_goal()
        conf, reasons = goal_confidence(goal)
        conf_txt = confidence_label(conf)
        if conf == "baixa" and reasons:
            self.confidence_var.set(f"Confiança da recomendação: {conf_txt} — faltam respostas ({len(reasons)} item(ns))")
        else:
            self.confidence_var.set(f"Confiança da recomendação: {conf_txt}")

        if not self.project or not self.install:
            return
        try:
            machine, process, filaments = self._selected_profiles()
            plan = self._build_current_plan(machine, process, filaments)
            advices = advise_offline(self.project, plan, goal)
            if self.save_history_var.get():
                advices = adjust_advices_from_history(advices, self.project, plan, goal, load_feedback_history())
            card = build_preconversion_card(
                self.project,
                plan,
                goal,
                physical_confirmed=self.physical_filament_confirmed_var.get(),
                advices=advices,
            )
            self.preconversion_var.set(card)
        except (ValueError, IndexError, StopIteration, ProfileError):
            pass

    def _save_preferences(self):
        save_settings({
            "nozzle": self.nozzle_var.get(),
            "machine": self.machine_var.get(),
            "last_dir": str(Path(self.file_var.get()).parent) if self.file_var.get() else self.preferences["last_dir"],
            "slicer_exe": str(self.install.executable) if self.install else self.preferences["slicer_exe"],
            "mode": self.mode_var.get(),
            "purpose": purpose_code(self.purpose_var.get()),
            "priority": priority_code(self.priority_var.get()),
            "load_type": load_type_code(self.load_type_var.get()),
            "criticality": criticality_code(self.criticality_var.get()),
            "fit_clearance": fit_code(self.fit_clearance_var.get()),
            "heat_exposure": heat_exposure_code(self.heat_exposure_var.get()),
            "save_print_history": "1" if self.save_history_var.get() else "0",
            "ai_model": self.ai_model_var.get(),
        })

    def _choose_slicer(self):
        filename = filedialog.askopenfilename(title="Localize elegoo-slicer.exe", filetypes=[("Executável", "*.exe")])
        if filename:
            self.preferences["slicer_exe"] = filename
            self._refresh_profiles()

    def _refresh_profiles(self):
        if self._refreshing_profiles:
            return
        self._refreshing_profiles = True
        self._profiles_changed()
        try:
            custom = self.preferences.get("slicer_exe")
            self.install = discover_slicer(executable=Path(custom) if custom else None)
            available = list_profiles(self.install, "machine", None)
            nozzles = sorted({str(resolve_profile(item, self.install)["nozzle_diameter"][0])
                              for item in available}, key=float)
            if not nozzles:
                raise ProfileError("Nenhum perfil da Centauri Carbon 2 encontrado neste computador")
            self.nozzle_combo["values"] = nozzles
            if self.nozzle_var.get() not in nozzles:
                self.nozzle_var.set(nozzles[0])
            nozzle = self.nozzle_var.get()
            self.machine_profiles = list_profiles(self.install, "machine", nozzle)
            options = [profile.name for profile in self.machine_profiles]
            self.machine_combo["values"] = options
            if self.machine_var.get() not in options:
                standard = f"Elegoo Centauri Carbon 2 {nozzle} nozzle"
                self.machine_var.set(standard if standard in options else options[0])
            self._refresh_dependents()
            self.status_var.set(f"Perfis carregados para bico {nozzle} mm")
            self._save_preferences()
        except (ProfileError, OSError) as exc:
            self.install = None
            self.machine_profiles = []
            self.process_profiles = []
            self.filament_profiles = []
            self.machine_combo["values"] = ()
            self.process_combo["values"] = ()
            self.status_var.set(str(exc))
        finally:
            self._refreshing_profiles = False

    def _refresh_dependents(self, *, prefer_suggested: bool = False):
        self._profiles_changed()
        machine = next((item for item in self.machine_profiles if item.name == self.machine_var.get()), None)
        if not self.install or machine is None:
            self.process_profiles = []
            self.filament_profiles = []
        else:
            nozzle = self.nozzle_var.get()
            self.process_profiles = list_profiles(self.install, "process", nozzle, machine=machine)
            self.filament_profiles = list_profiles(self.install, "filament", nozzle, machine=machine)
        options = [profile.name for profile in self.process_profiles]
        self.process_combo["values"] = options
        suggested = suggest_process(self.project.source_settings, self.process_profiles) if self.project else None
        if prefer_suggested and suggested and suggested.name in options:
            self.process_var.set(suggested.name)
        elif self.process_var.get() not in options:
            if suggested and suggested.name in options:
                self.process_var.set(suggested.name)
            else:
                self.process_var.set(next((name for name in options if "Standard" in name), options[0] if options else ""))
        self._render_filaments()
        if self.install:
            self._save_preferences()

    def _selected_profiles(self) -> tuple[Profile, Profile, list[Profile]]:
        machine = next(item for item in self.machine_profiles if item.name == self.machine_var.get())
        process = next(item for item in self.process_profiles if item.name == self.process_var.get())
        filaments = [next(item for item in self.filament_profiles if item.name == variable.get())
                     for variable in self.filament_vars]
        return machine, process, filaments

    def _choose_file(self):
        filename = filedialog.askopenfilename(title="Projeto MakerWorld", initialdir=self.preferences.get("last_dir") or None,
                                               filetypes=[("Projeto 3MF", "*.3mf")])
        if filename:
            self.file_var.set(filename)
            self._inspect_file()

    def _inspect_file(self):
        if getattr(self, "orientation_applying", False):
            messagebox.showinfo("Orientação de figura", "Aguarde a criação da cópia terminar.")
            return
        if self.orientation_dialog and self.orientation_dialog.winfo_exists():
            self._orientation_close()
        try:
            self.project = inspect_project(Path(self.file_var.get()))
            self.result = None
            self.last_plan = None
            self.orientation_analysis = None
            self.orientation_plan = None
            # Nunca presumir filamento físico == 3MF ao analisar novo projeto
            self.physical_filament_confirmed_var.set(False)
            self.physical_material_var.set("Não sei informar")
            self._clear_ai_approval()
            self.ai_button.configure(state="disabled")
            self.orientation_button.configure(state="normal")
            self.open_button.configure(state="disabled")
            self._set_report(format_project_summary(self.project))
            self._refresh_dependents(prefer_suggested=True)
            self._update_context_preview()
            self.status_var.set("Projeto analisado — confirme o filamento físico")
            self._save_preferences()
        except Exception as exc:
            self.project = None
            self.orientation_button.configure(state="disabled")
            messagebox.showerror("Não foi possível analisar", str(exc))

    def _render_filaments(self):
        for child in self.filament_frame.winfo_children():
            child.destroy()
        self.filament_vars = []
        if not self.project:
            ttk.Label(self.filament_frame, text="Os filamentos aparecerão após a análise do projeto.").grid(row=0, column=0, sticky="w")
            return
        options = [profile.name for profile in self.filament_profiles]
        used_slots = set(getattr(self.project, "used_filament_slots", ()) or ())
        for row, filament in enumerate(self.project.filaments):
            unused_tag = " (não usado nas placas)" if used_slots and str(filament.slot) not in used_slots else ""
            ttk.Label(self.filament_frame, text=f"Filamento {filament.slot}: {filament.material} {filament.color}{unused_tag}").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            preferred = next((name for name in options if name == f"Elegoo {filament.material} @ECC2"), None)
            if not preferred:
                preferred = next((name for name in options if filament.material.upper() in name.upper() and "@ECC2" in name), None)
            variable = tk.StringVar(value=preferred or (options[0] if options else ""))
            variable.trace_add("write", lambda *_: self._profiles_changed())
            ttk.Combobox(self.filament_frame, textvariable=variable, values=options,
                         state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
            self.filament_vars.append(variable)

    def _orientation_open(self):
        if not self.project or not self.install:
            messagebox.showinfo("Orientação de figura", "Analise um 3MF e localize o ELEGOO Slicer primeiro.")
            return
        if self.orientation_dialog and self.orientation_dialog.winfo_exists():
            self.orientation_dialog.lift()
            return
        self.orientation_cancel = threading.Event()
        self.orientation_generation += 1
        generation = self.orientation_generation
        self.orientation_analysis = None
        self.orientation_plan = None
        self.orientation_busy = False
        self.orientation_applying = False
        dialog = tk.Toplevel(self)
        self.orientation_dialog = dialog
        dialog.title("Analisar orientação de figura")
        dialog.geometry("900x600")
        dialog.minsize(700, 480)
        dialog.transient(self)
        dialog.protocol("WM_DELETE_WINDOW", self._orientation_close)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Escolha a vista em que aparece o rosto e a frente da figura.",
                  wraplength=820).pack(anchor="w")
        self.orientation_front = tk.StringVar(value="-Y")
        self.orientation_front.trace_add("write", lambda *_: self._orientation_front_changed())
        previews = ttk.Frame(frame)
        previews.pack(fill="x", pady=10)
        self.orientation_preview_frame = previews
        self.orientation_images = []
        self.orientation_message = tk.StringVar(value="Lendo a malha localmente...")
        ttk.Label(frame, textvariable=self.orientation_message).pack(anchor="w")
        self.orientation_report = scrolledtext.ScrolledText(frame, height=12, wrap="word", state="disabled")
        self.orientation_report.pack(fill="both", expand=True, pady=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        self.orientation_analyze_button = ttk.Button(buttons, text="Comparar e fatiar", command=self._orientation_analyze,
                                                     state="disabled")
        self.orientation_analyze_button.pack(side="left")
        self.orientation_apply_button = ttk.Button(buttons, text="Aplicar em cópia", command=self._orientation_apply,
                                                   state="disabled")
        self.orientation_apply_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Fechar", command=self._orientation_close).pack(side="right")
        project_path = self.project.path
        cancel = self.orientation_cancel

        def work():
            try:
                scene = load_scene(project_path)
                if not cancel.is_set():
                    self.orientation_queue.put((generation, "previews", render_front_views(scene)))
            except Exception as exc:
                self.orientation_queue.put((generation, "error", exc))

        threading.Thread(target=work, daemon=True).start()

    def _orientation_close(self):
        if getattr(self, "orientation_busy", False) and getattr(self, "orientation_applying", False):
            self.orientation_message.set("Aguarde o fatiamento da cópia terminar.")
            return
        self.orientation_cancel.set()
        if self.orientation_dialog and self.orientation_dialog.winfo_exists():
            self.orientation_dialog.destroy()
        self.orientation_dialog = None

    def _orientation_front_changed(self):
        analysis = self.orientation_analysis
        if analysis is not None and analysis.front != self.orientation_front.get():
            self.orientation_analysis = None
            self.orientation_apply_button.configure(state="disabled")
            self.orientation_message.set("A frente mudou. Compare e fatia novamente antes de aplicar.")

    def _orientation_analyze(self):
        if not self.project or not self.install or getattr(self, "orientation_busy", False):
            return
        try:
            machine, process, filaments = self._selected_profiles()
            plan = build_conversion(self.project, self.install, machine, process, filaments)
        except Exception as exc:
            messagebox.showerror("Perfis de destino", str(exc), parent=self.orientation_dialog)
            return
        self.orientation_plan = plan
        self.orientation_analysis = None
        self.orientation_busy = True
        self.orientation_applying = False
        self.orientation_analyze_button.configure(state="disabled")
        self.orientation_apply_button.configure(state="disabled")
        self.orientation_message.set("Comparando e fatiando as orientações... pode levar alguns minutos")
        project, front, cancel = self.project, self.orientation_front.get(), self.orientation_cancel
        generation = self.orientation_generation
        install = self.install

        def work():
            try:
                analysis = evaluate_orientations(
                    project, plan, front, SlicerCLI(install.executable),
                    progress=lambda label, index, total: self.orientation_queue.put(
                        (generation, "progress", f"Fatiando {label} ({index}/{total})...")),
                    cancelled=cancel.is_set)
                self.orientation_queue.put((generation, "analysis", analysis))
            except Exception as exc:
                self.orientation_queue.put((generation, "error", exc))

        threading.Thread(target=work, daemon=True).start()

    def _orientation_apply(self):
        if not self.project or not self.install or not self.orientation_analysis or not self.orientation_plan:
            return
        candidate = self.orientation_analysis.recommended
        if candidate.is_current or not candidate.valid:
            return
        destination = filedialog.asksaveasfilename(
            title="Salvar cópia orientada", defaultextension=".3mf",
            initialfile=self.project.path.stem + "_orientado_ELEGOO.3mf",
            initialdir=str(self.project.path.parent), filetypes=[("Projeto 3MF", "*.3mf")],
            parent=self.orientation_dialog)
        if not destination:
            return
        if Path(destination).exists() or Path(destination).resolve() == self.project.path.resolve():
            messagebox.showerror("Destino existente", "Escolha um novo nome para preservar os arquivos existentes.",
                                 parent=self.orientation_dialog)
            return
        if not messagebox.askyesno(
                "Confirmar orientação",
                f"Aplicar '{candidate.label}' em uma nova cópia e fatiar no ELEGOO Slicer?\n\n"
                "Confira rosto, suportes e prévia antes de imprimir.", parent=self.orientation_dialog):
            return
        self.orientation_busy = True
        self.orientation_applying = True
        self.orientation_apply_button.configure(state="disabled")
        self.orientation_analyze_button.configure(state="disabled")
        self.orientation_message.set("Criando e fatiando a cópia orientada...")
        project, plan = self.project, self.orientation_plan
        generation = self.orientation_generation
        install = self.install

        def work():
            try:
                result = apply_orientation(project, plan, candidate, Path(destination),
                                           SlicerCLI(install.executable))
                self.orientation_queue.put((generation, "applied", result))
            except Exception as exc:
                self.orientation_queue.put((generation, "error", exc))

        threading.Thread(target=work, daemon=True).start()

    def _poll_orientation(self):
        try:
            while True:
                generation, kind, payload = self.orientation_queue.get_nowait()
                dialog = self.orientation_dialog
                if (generation != self.orientation_generation or not dialog or
                        not dialog.winfo_exists() or self.orientation_cancel.is_set()):
                    continue
                if kind == "previews":
                    for direction in FRONTS:
                        photo = tk.PhotoImage(data=payload[direction], format="PPM")
                        self.orientation_images.append(photo)
                        box = ttk.Frame(self.orientation_preview_frame)
                        box.pack(side="left", padx=5)
                        ttk.Label(box, image=photo).pack()
                        ttk.Radiobutton(box, text=direction, variable=self.orientation_front,
                                        value=direction).pack()
                    self.orientation_message.set("Selecione a frente e compare as posições.")
                    self.orientation_analyze_button.configure(state="normal")
                elif kind == "progress":
                    self.orientation_message.set(payload)
                elif kind == "analysis":
                    self.orientation_busy = False
                    if payload.front != self.orientation_front.get():
                        self.orientation_message.set("A frente mudou durante a análise. Compare novamente.")
                        self.orientation_analyze_button.configure(state="normal")
                        continue
                    self.orientation_analysis = payload
                    self.orientation_report.configure(state="normal")
                    self.orientation_report.delete("1.0", "end")
                    self.orientation_report.insert("1.0", format_orientation_analysis(payload))
                    self.orientation_report.configure(state="disabled")
                    self.orientation_message.set(payload.reason)
                    self.orientation_analyze_button.configure(state="normal")
                    if not payload.recommended.is_current and payload.recommended.valid:
                        self.orientation_apply_button.configure(state="normal")
                elif kind == "applied":
                    self.orientation_busy = False
                    self.orientation_applying = False
                    self.result = payload
                    self.last_plan = self.orientation_plan
                    report = format_conversion_report(payload, self.orientation_plan)
                    self._set_report(report)
                    self.orientation_report.configure(state="normal")
                    self.orientation_report.delete("1.0", "end")
                    self.orientation_report.insert("1.0", report)
                    self.orientation_report.configure(state="disabled")
                    self.orientation_message.set("Cópia validada" if payload.success else "Falha; confira o relatório")
                    self.status_var.set(self.orientation_message.get())
                    if payload.destination.exists():
                        self.open_button.configure(state="normal")
                    self.orientation_analyze_button.configure(state="normal")
                elif kind == "error":
                    self.orientation_busy = False
                    self.orientation_applying = False
                    self.orientation_analyze_button.configure(state="normal")
                    self.orientation_message.set(str(payload))
                    messagebox.showerror("Orientação de figura", str(payload), parent=dialog)
        except queue.Empty:
            pass
        self._orientation_after = self.after(150, self._poll_orientation)

    def _configure_gemini_key(self):
        dialog = tk.Toplevel(self)
        dialog.title("Configurar Chave Google Gemini")
        dialog.geometry("540x260")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)

        current_key = get_gemini_key()
        status_text = "Status: Chave configurada e salva com segurança." if current_key else "Status: Nenhuma chave salva."
        ttk.Label(frame, text="Chave de API do Google Gemini (salva criptografada via Windows DPAPI):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        status_lbl = ttk.Label(frame, text=status_text, foreground="green" if current_key else "gray")
        status_lbl.pack(anchor="w", pady=(4, 10))

        key_var = tk.StringVar(value=current_key or "")
        entry = ttk.Entry(frame, textvariable=key_var, show="*")
        entry.pack(fill="x", pady=(0, 10))

        model_frame = ttk.Frame(frame)
        model_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(model_frame, text="Modelo:").pack(side="left", padx=(0, 8))
        ttk.Combobox(model_frame, textvariable=self.ai_model_var, values=("gemini-3.8-flash", "gemini-3.5-flash-lite"),
                     state="readonly", width=22).pack(side="left")

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill="x", pady=(8, 0))

        def save():
            k = key_var.get().strip()
            if k:
                save_gemini_key(k)
                messagebox.showinfo("Sucesso", "Chave salva com sucesso!", parent=dialog)
                dialog.destroy()
            else:
                messagebox.showwarning("Aviso", "Informe uma chave de API válida.", parent=dialog)

        def clear():
            clear_gemini_key()
            key_var.set("")
            status_lbl.configure(text="Status: Chave removida.", foreground="gray")
            messagebox.showinfo("Removida", "Chave apagada com sucesso.", parent=dialog)

        def test_conn():
            k = key_var.get().strip() or get_gemini_key() or ""
            if not k:
                messagebox.showwarning("Aviso", "Informe ou salve uma chave de API primeiro.", parent=dialog)
                return
            status_lbl.configure(text="Status: Testando conexão com o Google Gemini...", foreground="#555555")
            test_btn.configure(state="disabled")

            def work():
                try:
                    GeminiClient(api_key=k, model=self.ai_model_var.get()).test_connection()
                    res = (True, "Conexão validada com sucesso!")
                except GeminiClientError as exc:
                    res = (False, str(exc))
                if dialog.winfo_exists():
                    dialog.after(0, lambda: done_test(res))

            def done_test(res):
                if not dialog.winfo_exists():
                    return
                test_btn.configure(state="normal")
                ok, msg = res
                status_lbl.configure(text=f"Status: {msg}", foreground="green" if ok else "#B00020")

            threading.Thread(target=work, daemon=True).start()

        ttk.Button(btn_box, text="Salvar Chave", command=save).pack(side="left", padx=(0, 8))
        test_btn = ttk.Button(btn_box, text="Testar Conexão", command=test_conn)
        test_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Remover Chave", command=clear).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Fechar", command=dialog.destroy).pack(side="right")

    def _on_scale_mode_changed(self):
        if hasattr(self, "scale_value_entry"):
            if self.scale_mode_var.get() == "Original (100%)":
                self.scale_value_var.set("")
                self.scale_value_entry.configure(state="disabled")
            else:
                self.scale_value_entry.configure(state="normal")

    def _parse_scale_request(self) -> tuple[float | None, float | None]:
        mode = self.scale_mode_var.get()
        if mode == "Original (100%)":
            return None, None
        raw = self.scale_value_var.get().strip().replace(",", ".")
        if not raw:
            raise ScaleError("Informe o valor de redimensionamento (ex.: 80 para 80 mm ou 50 para 50%).")
        try:
            num = float(raw)
        except ValueError as exc:
            raise ScaleError("Valor de escala inválido; use apenas números positivos.") from exc
        if num <= 0:
            raise ScaleError("O valor de escala deve ser maior que zero.")
        if mode == "Escala (%)":
            return num, None
        return None, num

    def _convert(self):
        if not self.project or not self.install:
            messagebox.showinfo("Dados incompletos", "Analise um 3MF e localize o ELEGOO Slicer primeiro.")
            return
        if not self.physical_filament_confirmed_var.get():
            mat_label = self.physical_material_var.get()
            if not messagebox.askyesno(
                "Confirmar filamento físico",
                f"Filamento selecionado: {mat_label}.\n\n"
                "Nunca presumimos que o filamento na sua impressora é igual ao do arquivo 3MF.\n"
                "Você confirma que o filamento físico carregado corresponde à seleção?",
                parent=self,
            ):
                self.status_var.set("Confirme o filamento físico antes de traduzir")
                return
            self.physical_filament_confirmed_var.set(True)
            self._on_physical_filament_changed()
        try:
            scale_percent, target_height_mm = self._parse_scale_request()
        except ScaleError as exc:
            messagebox.showerror("Escala inválida", str(exc))
            return
        destination = filedialog.asksaveasfilename(title="Salvar projeto ELEGOO", defaultextension=".3mf",
                                                    initialfile=self.project.path.stem + "_ELEGOO.3mf",
                                                    initialdir=str(self.project.path.parent),
                                                    filetypes=[("Projeto 3MF", "*.3mf")])
        if not destination:
            return
        resolved_dest = _resolve_existing_destination(Path(destination), parent=self)
        if resolved_dest is None:
            return
        destination = str(resolved_dest)
        try:
            machine, process, filaments = self._selected_profiles()
        except (IndexError, StopIteration):
            messagebox.showerror("Perfil ausente", "Escolha um processo e um perfil para cada filamento.")
            return

        plan = self._build_current_plan(machine, process, filaments)
        goal = self._current_goal()

        scale_advices: list[Advice] = []
        if scale_percent is not None or target_height_mm is not None:
            geom = getattr(self.project, "geometry_summary", None)
            if geom is not None and getattr(geom, "size_z", 0.0) > 1e-6:
                factor = (target_height_mm / geom.size_z) if target_height_mm is not None else (scale_percent / 100.0)
                nozzle = float(str(plan.machine_settings.get("nozzle_diameter", ["0.4"])[0]))
                try:
                    risk = analyze_scale_risk(factor, (geom.size_x, geom.size_y, geom.size_z),
                                              nozzle_mm=nozzle, purpose=goal.purpose)
                except ScaleError as exc:
                    messagebox.showerror("Escala inválida", str(exc))
                    return
                for warn in risk.warnings:
                    scale_advices.append(Advice(
                        "alert", None, "", "", "", "Alerta de Redimensionamento", warn, False,
                        what_to_check="Confira espessura mínima e folgas após fatiar.",
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=True,
                    ))
                if risk.recommend_finer_layer:
                    cur_h = str(plan.process_settings.get("layer_height", "0.2"))
                    try:
                        if float(cur_h) > float(risk.recommend_finer_layer) + 0.01:
                            scale_advices.append(Advice(
                                "process", None, "layer_height", cur_h, risk.recommend_finer_layer,
                                "Camada Mais Fina Para Peça Reduzida",
                                "Compensa a redução de tamanho preservando contornos e detalhes com bico 0.4 mm.",
                                True,
                                expected_effect="Maior resolução vertical para compensar redução em Z (mais tempo).",
                                what_to_check="Compare detalhes na prévia de camadas.",
                                evidence_class="estimado_regra_ia",
                            ))
                    except ValueError:
                        pass

        self._pending_scale_advices = scale_advices

        # Obter conselhos do Professor (Offline ou IA em thread separada)
        if self.mode_var.get() == "ai":
            key = get_gemini_key()
            if not key:
                if messagebox.askyesno("Chave Ausente", "Nenhuma chave Gemini salva. Deseja configurar agora?"):
                    self._configure_gemini_key()
                    return
                self.mode_var.set("offline")
                advices = advise_offline(self.project, plan, goal)
                self._finish_professor_lookup(plan, destination, advices, goal=goal)
                return

            consent = messagebox.askyesno(
                "Autorizar envio ao Google Gemini",
                "Enviar resumo textual (materiais de origem/destino, uso, prioridade, bico e parâmetros permitidos) ao Google Gemini?\n\n"
                "O arquivo 3MF, a malha e o G-code NÃO serão enviados.",
                parent=self,
            )
            if not consent:
                self.status_var.set("Conversão cancelada pelo usuário")
                return

            self.convert_button.configure(state="disabled")
            self.status_var.set("Consultando Professor IA (Google Gemini)...")
            self._start_gemini_professor(self.project, plan, goal, destination, key, self.ai_model_var.get())
            return

        advices = advise_offline(self.project, plan, goal)
        self._finish_professor_lookup(plan, destination, advices, goal=goal)

    def _start_gemini_professor(self, project: ProjectInfo, plan: ConversionPlan, goal: PrintGoal,
                                destination: str, key: str, model_name: str):
        self.convert_button.configure(state="disabled")
        self.status_var.set(f"Consultando Professor IA ({model_name})...")

        def work_ai():
            try:
                client = GeminiClient(api_key=key, model=model_name)
                ai_advices = advise_gemini(client, project, plan, goal)
                merged_ai = merge_with_offline_alerts(ai_advices, advise_offline(project, plan, goal))
                self.professor_queue.put((project, plan, goal, destination, model_name, merged_ai, None))
            except Exception as exc:
                self.professor_queue.put((project, plan, goal, destination, model_name, None, exc))

        threading.Thread(target=work_ai, daemon=True).start()

    def _finish_professor_lookup(
        self,
        plan: ConversionPlan,
        destination: str,
        advices: list[Advice],
        *,
        goal: PrintGoal | None = None,
    ):
        merged = list(advices) + list(getattr(self, "_pending_scale_advices", ()))
        self._pending_scale_advices = []
        active_goal = goal or self._current_goal()
        if self.save_history_var.get() and self.project is not None:
            merged = adjust_advices_from_history(merged, self.project, plan, active_goal, load_feedback_history())
        needs_decision, _ = needs_user_intervention(
            self.project,
            plan,
            active_goal,
            merged,
            physical_confirmed=self.physical_filament_confirmed_var.get(),
        )
        if merged and (needs_decision or any(a.scope != "alert" for a in merged)):
            self._show_professor_dialog(plan, destination, merged)
        else:
            self._execute_conversion(plan, destination, professor_advices=merged)

    def _poll_professor(self):
        try:
            project, plan, goal, destination, model_name, advices, error = self.professor_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.convert_button.configure(state="normal")
            if error:
                if (isinstance(error, GeminiClientError)
                        and error.status_code == 429
                        and model_name != "gemini-3.5-flash-lite"
                        and (key := get_gemini_key())):
                    if messagebox.askyesno(
                        "Cota do Gemini excedida",
                        f"O modelo {model_name} atingiu o limite de cota (HTTP 429).\n\n"
                        "Deseja tentar automaticamente com o modelo mais leve (gemini-3.5-flash-lite)?",
                        parent=self,
                    ):
                        self._start_gemini_professor(project, plan, goal, destination, key, "gemini-3.5-flash-lite")
                        self._professor_after = self.after(150, self._poll_professor)
                        return
                if isinstance(error, GeminiClientError) and messagebox.askyesno(
                    "IA Indisponível",
                    f"{error}\n\nDeseja utilizar o Professor Offline (regras locais) nesta conversão?",
                    parent=self,
                ):
                    offline_advices = advise_offline(project, plan, goal)
                    self._finish_professor_lookup(plan, destination, offline_advices)
                else:
                    self.status_var.set("Falha ao consultar IA" if not isinstance(error, GeminiClientError) else "Conversão cancelada pelo usuário")
                    if not isinstance(error, GeminiClientError):
                        messagebox.showerror("Professor IA", str(error), parent=self)
            else:
                self._finish_professor_lookup(plan, destination, advices or [])
        self._professor_after = self.after(150, self._poll_professor)

    def _show_professor_dialog(self, plan: ConversionPlan, destination: str, advices: list[Advice]):
        dialog = tk.Toplevel(self)
        dialog.title("Professor de Impressão · Recomendações e Ajustes")
        dialog.geometry("780x560")
        dialog.transient(self)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        mode_name = "IA (Google Gemini)" if self.mode_var.get() == "ai" else "100% Offline (Engenharia)"
        ttk.Label(frame, text=f"Conselhos do Professor — Modo {mode_name}", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Revise e selecione os ajustes recomendados para sua peça antes do fatiamento.",
                  wraplength=740).pack(anchor="w", pady=(2, 10))

        list_container = ttk.Frame(frame)
        list_container.pack(fill="both", expand=True)

        content_canvas = tk.Canvas(list_container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=content_canvas.yview)
        scrollable_frame = ttk.Frame(content_canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: content_canvas.configure(scrollregion=content_canvas.bbox("all"))
        )
        canvas_window = content_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        content_canvas.bind(
            "<Configure>",
            lambda e: content_canvas.itemconfigure(canvas_window, width=e.width),
        )
        content_canvas.configure(yscrollcommand=scrollbar.set)
        dialog.bind(
            "<MouseWheel>",
            lambda e: content_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        content_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        check_vars: list[tuple[Advice, tk.BooleanVar]] = []
        adjustments = [adv for adv in advices if adv.scope != "alert"]
        alerts = [adv for adv in advices if adv.scope == "alert"]

        if self.project is not None:
            goal = self._current_goal()
            summary_box = ttk.LabelFrame(scrollable_frame, text="Resumo para impressão", padding=8)
            summary_box.pack(fill="x", expand=True, pady=(0, 8), padx=4)
            ttk.Label(
                summary_box,
                text=build_print_summary(self.project, plan, goal, advices),
                wraplength=700,
                justify="left",
            ).pack(anchor="w")

        if adjustments:
            adj_section = ttk.LabelFrame(scrollable_frame, text="Ajustes recomendados", padding=8)
            adj_section.pack(fill="x", expand=True, pady=(0, 8), padx=4)
            for adv in adjustments:
                adv_box = ttk.LabelFrame(adj_section, text=adv.title, padding=8)
                adv_box.pack(fill="x", expand=True, pady=4, padx=4)
                var = tk.BooleanVar(value=adv.default_on)
                chk = ttk.Checkbutton(
                    adv_box,
                    text=f"Aplicar: {adv.current} → {adv.proposed} ({evidence_label(adv.evidence_class)})",
                    variable=var,
                )
                chk.pack(anchor="w")
                ttk.Label(adv_box, text=f"Motivo: {adv.why}", wraplength=680, foreground="#333333").pack(
                    anchor="w", pady=(4, 0)
                )
                if getattr(adv, "expected_effect", ""):
                    ttk.Label(
                        adv_box,
                        text=f"Efeito esperado: {adv.expected_effect}",
                        wraplength=680,
                        foreground="#1F3A52",
                    ).pack(anchor="w", pady=(2, 0))
                if getattr(adv, "what_to_check", ""):
                    ttk.Label(
                        adv_box,
                        text=f"O que conferir: {adv.what_to_check}",
                        wraplength=680,
                        foreground="#444444",
                    ).pack(anchor="w", pady=(2, 0))
                check_vars.append((adv, var))

        if alerts:
            alert_section = ttk.LabelFrame(scrollable_frame, text="Avisos e dicas", padding=8)
            alert_section.pack(fill="x", expand=True, pady=(0, 8), padx=4)
            for adv in alerts:
                adv_box = ttk.LabelFrame(alert_section, text=adv.title, padding=8)
                adv_box.pack(fill="x", expand=True, pady=4, padx=4)
                phys_prefix = (
                    "[Depende de teste físico — fatiar não comprova]\n"
                    if getattr(adv, "requires_physical_test", False) or adv.evidence_class == "depende_teste_fisico"
                    else f"[{evidence_label(adv.evidence_class)}]\n"
                )
                ttk.Label(
                    adv_box,
                    text=f"{phys_prefix}{adv.why}",
                    foreground="#B34700",
                    wraplength=680,
                ).pack(anchor="w")
                if getattr(adv, "what_to_check", ""):
                    ttk.Label(
                        adv_box,
                        text=f"O que conferir: {adv.what_to_check}",
                        wraplength=680,
                        foreground="#444444",
                    ).pack(anchor="w", pady=(2, 0))

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill="x", pady=(12, 0))

        def proceed():
            approved = [adv for adv, var in check_vars if var.get()]
            dialog.destroy()
            final_plan = apply_advice(plan, approved)
            self._execute_conversion(final_plan, destination, professor_advices=[*approved, *alerts])

        def skip():
            dialog.destroy()
            self._execute_conversion(plan, destination, professor_advices=alerts)

        ttk.Button(btn_box, text="Aplicar Selecionados e Converter", command=proceed).pack(side="left")
        ttk.Button(btn_box, text="Converter Sem Ajustes", command=skip).pack(side="left", padx=8)
        ttk.Button(btn_box, text="Cancelar", command=dialog.destroy).pack(side="right")
        return dialog

    def _record_feedback(
        self,
        *,
        target_material: str,
        purpose: str,
        visual_result: str,
        notes: str = "",
        source_material: str = "",
        load_type: str = "",
    ):
        if not self.save_history_var.get():
            return None
        proj_label = self.project.path.stem if self.project else "projeto_local"
        src_mat = source_material or (
            "/".join(f.material for f in self.project.filaments) if self.project else target_material
        )
        goal = self._current_goal()
        params = {}
        if self.last_plan is not None:
            for k in ("layer_height", "wall_loops", "sparse_infill_density", "brim_type"):
                if k in self.last_plan.process_settings:
                    params[k] = str(self.last_plan.process_settings[k])
        record = FeedbackRecord(
            timestamp="",
            project_label=proj_label,
            source_material=src_mat,
            target_material=target_material,
            nozzle_mm=self.nozzle_var.get() or "0.4",
            purpose=purpose,
            priority=goal.priority,
            load_type=load_type or goal.load_type,
            visual_result=visual_result,
            applied_params=params,
            notes=notes,
        )
        append_feedback_record(record)
        self._update_context_preview()
        return record

    def _open_feedback_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Registrar resultado da impressão (histórico local)")
        dialog.geometry("540x400")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Registro 100% local (opcional). Nenhum .3mf, malha ou G-code sai deste computador.",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 8))

        ttk.Checkbutton(
            frame,
            text="Ativar histórico local de impressões para ajustar futuras recomendações",
            variable=self.save_history_var,
        ).pack(anchor="w", pady=(0, 8))

        mat_default = self.physical_material_var.get()
        if mat_default in {"", "Não sei informar"}:
            mat_default = "PLA"
        mat_var = tk.StringVar(value=mat_default)
        purp_var = tk.StringVar(value=purpose_code(self.purpose_var.get()))
        result_by_label = {label: code for code, label in VISUAL_RESULTS.items()}
        vis_label_var = tk.StringVar(value=VISUAL_RESULTS["aprovado"])
        notes_var = tk.StringVar()

        form = ttk.Frame(frame)
        form.pack(fill="x", pady=4)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Filamento impresso:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(
            form,
            textvariable=mat_var,
            values=("PLA", "PETG", "ABS", "ASA", "ABS-CF", "ASA-CF", "TPU"),
            state="readonly",
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="Uso principal (código):").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Combobox(form, textvariable=purp_var, values=tuple(PURPOSE_LABELS.keys()), state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(6, 0)
        )
        ttk.Label(form, text="Resultado observado:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Combobox(form, textvariable=vis_label_var, values=tuple(VISUAL_RESULTS.values()), state="readonly").grid(
            row=2, column=1, sticky="ew", pady=(6, 0)
        )

        ttk.Label(frame, text="Observações locais (opcional):").pack(anchor="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=notes_var).pack(fill="x", pady=(2, 10))

        def save():
            if not self.save_history_var.get():
                if not messagebox.askyesno(
                    "Ativar histórico local?",
                    "O armazenamento local de histórico está desativado. Deseja ativá-lo neste computador e salvar este registro?",
                    parent=dialog,
                ):
                    return
                self.save_history_var.set(True)
            vis_code = result_by_label.get(vis_label_var.get(), "aprovado")
            self._record_feedback(
                target_material=mat_var.get(),
                purpose=purp_var.get(),
                visual_result=vis_code,
                notes=notes_var.get(),
            )
            self.status_var.set("Resultado da impressão salvo localmente")
            dialog.destroy()

        def clear_hist():
            clear_feedback_history()
            self.status_var.set("Histórico local limpo")
            self._update_context_preview()

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Salvar registro local", command=save).pack(side="left")
        ttk.Button(btns, text="Limpar histórico", command=clear_hist).pack(side="left", padx=8)
        ttk.Button(btns, text="Fechar", command=dialog.destroy).pack(side="right")
        return dialog

    def _execute_conversion(self, plan: ConversionPlan, destination: str,
                            *, professor_advices: list[Advice] | tuple[Advice, ...] = ()):
        self.convert_button.configure(state="disabled")
        self.ai_button.configure(state="disabled")
        self.status_var.set("Convertendo e fatiando... pode levar alguns minutos")
        project = self.project
        install = self.install
        approved = tuple(self.ai_approved)
        prof_tuple = tuple(professor_advices)
        scale_percent, target_height_mm = self._parse_scale_request()
        purpose = purpose_code(self.purpose_var.get())

        def work():
            rescale_info = None
            try:
                active_plan = plan
                if approved:
                    active_plan = replace(active_plan, process_settings=apply_suggestions(active_plan.process_settings, list(approved)))
                if scale_percent is not None or target_height_mm is not None:
                    with tempfile.TemporaryDirectory(prefix="maker-elegoo-scale-") as tmp_dir:
                        area = active_plan.machine_settings.get("printable_area", ["0x0", "256x0", "256x256", "0x256"])
                        height = float(str(active_plan.machine_settings.get("printable_height", "256")))
                        nozzle = float(str(active_plan.machine_settings.get("nozzle_diameter", ["0.4"])[0]))
                        scaled_path = Path(tmp_dir) / project.path.name
                        rescale_info = rescale_3mf(
                            project.path, scaled_path,
                            scale_percent=scale_percent, target_height_mm=target_height_mm,
                            printable_area=area, printable_height=height,
                            nozzle_mm=nozzle, purpose=purpose,
                        )
                        working_project = inspect_project(scaled_path, include_geometry=False)
                        result = convert_project(working_project, active_plan, Path(destination), SlicerCLI(install.executable))
                else:
                    result = convert_project(project, active_plan, Path(destination), SlicerCLI(install.executable))
                self.worker_queue.put((result, active_plan, approved, prof_tuple, rescale_info, None))
            except Exception as exc:
                self.worker_queue.put((None, None, approved, prof_tuple, rescale_info, exc))

        threading.Thread(target=work, daemon=True).start()

    def _poll_worker(self):
        try:
            result, plan, approved, prof_tuple, rescale_info, error = self.worker_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.convert_button.configure(state="normal")
            if error:
                self.status_var.set("Falha na conversão")
                self._set_report(str(error))
            else:
                self.result = result
                self.last_plan = plan
                report = format_conversion_report(result, plan, professor_advices=prof_tuple, rescale_info=rescale_info)
                if approved:
                    report += "\n\nSugestões IA aprovadas e aplicadas:\n" + "\n".join(
                        f"  • {item.target_key} = {item.value}: {item.reason}" for item in approved)
                self._set_report(report)
                self.status_var.set("Concluído" if result.success else "Falha; confira o relatório")
                if result.destination.exists():
                    self.open_button.configure(state="normal")
                if result.output_project:
                    self.ai_button.configure(state="normal")
        self._worker_after = self.after(150, self._poll_worker)

    def _clear_ai_approval(self):
        self.ai_approved = []

    def _profiles_changed(self):
        self._clear_ai_approval()
        self.orientation_analysis = None
        self.orientation_plan = None

    def _manual_ai(self):
        if not self.result or not self.last_plan or not self.project:
            messagebox.showinfo("Ajuste guiado", "Converta o projeto uma vez antes de pedir sugestões.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Ajuste guiado por IA · sem chave de API")
        dialog.geometry("850x680")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Escolha o objetivo, copie o resumo para sua IA e cole a resposta JSON.",
                  wraplength=780).pack(anchor="w")
        priority = tk.StringVar(value=priority_label("equilibrio"))
        purpose = tk.StringVar(value=purpose_label("decorativa"))
        for label, variable, options in (
            ("Prioridade", priority, tuple(PRIORITY_LABELS.values())),
            ("Uso da peça", purpose, tuple(PURPOSE_LABELS.values())),
        ):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=(8, 0))
            ttk.Label(row, text=label, width=17).pack(side="left")
            ttk.Combobox(row, textvariable=variable, values=options, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Label(frame, text="Observações sobre a peça (opcional)").pack(anchor="w", pady=(8, 0))
        notes = ttk.Entry(frame)
        notes.pack(fill="x")
        ttk.Label(frame, text="Resumo para copiar").pack(anchor="w", pady=(8, 0))
        prompt_box = scrolledtext.ScrolledText(frame, height=10, wrap="word")
        prompt_box.pack(fill="both", expand=True)
        ttk.Label(frame, text="Resposta JSON da IA").pack(anchor="w", pady=(8, 0))
        response_box = scrolledtext.ScrolledText(frame, height=8, wrap="word")
        response_box.pack(fill="both", expand=True)

        def make_prompt():
            target_mats = [str(cfg.get("filament_type", [""])[0]) for cfg in self.last_plan.filament_settings]
            context = {
                "printer_model": self.last_plan.machine.name,
                "filament_type": target_mats,
                "nozzle_diameter": self.last_plan.machine_settings.get("nozzle_diameter"),
            }
            prompt = build_manual_prompt(self.result.unmapped, self.last_plan.process_settings,
                                         context, priority.get(), purpose.get(), notes.get())
            prompt_box.delete("1.0", "end")
            prompt_box.insert("1.0", prompt)
            self.clipboard_clear()
            self.clipboard_append(prompt)
            self.status_var.set("Resumo copiado; cole em sua IA e traga a resposta JSON")

        def review():
            try:
                suggestions = parse_manual_response(response_box.get("1.0", "end"),
                                                    self.result.unmapped, self.last_plan.process_settings)
            except AIError as exc:
                messagebox.showerror("Resposta inválida", str(exc), parent=dialog)
                return
            if not suggestions:
                messagebox.showinfo("Sem ajustes aplicáveis", "Nenhuma sugestão passou pelos limites e perfis disponíveis.", parent=dialog)
                return
            dialog.destroy()
            self._review_suggestions(suggestions)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Gerar e copiar resumo", command=make_prompt).pack(side="left")
        ttk.Button(buttons, text="Validar resposta e revisar", command=review).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Fechar", command=dialog.destroy).pack(side="right")
        make_prompt()

    def _analyze_ai(self):
        if not self.result or not self.last_plan or not self.result.output_project:
            messagebox.showinfo("IA opcional", "Converta o projeto uma vez antes de analisar campos não traduzidos.")
            return
        if self.ai_provider_var.get() == "Codex":
            self._analyze_codex()
            return
        key = get_gemini_key() or simpledialog.askstring("Gemini", "Chave de API Gemini (não será salva):", show="*", parent=self)
        if not key:
            return
        consent = messagebox.askyesno(
            "Autorizar envio ao Gemini",
            "Enviar até 30 nomes e valores curtos de configurações ao Gemini?\n\n"
            "O arquivo 3MF, a malha e o G-code não serão enviados. A camada gratuita do Gemini "
            "pode usar os dados enviados para melhorar os serviços do Google.", parent=self)
        if not consent:
            return
        self.ai_button.configure(state="disabled")
        self.status_var.set("Consultando Gemini...")
        unmapped = dict(self.result.unmapped)
        target = dict(self.last_plan.process_settings)
        target_mats = [str(cfg.get("filament_type", [""])[0]) for cfg in self.last_plan.filament_settings]
        context = {
            "printer_model": self.last_plan.machine.name,
            "filament_type": target_mats,
            "nozzle_diameter": self.last_plan.machine_settings.get("nozzle_diameter"),
        }

        def work():
            try:
                suggestions = suggest_equivalences(unmapped, target, context, key)
                self.ai_queue.put((suggestions, None))
            except Exception as exc:
                self.ai_queue.put((None, exc))

        threading.Thread(target=work, daemon=True).start()

    def _analyze_codex(self):
        orientation = self.orientation_analysis
        if orientation is not None and self.orientation_plan != self.last_plan:
            self.orientation_analysis = None
            orientation = None
        if (len(self.project.plates) == 1 and len(self.project.objects) == 1
                and orientation is None):
            messagebox.showinfo("Orientação de figura",
                                "Escolha a vista do rosto e conclua a comparação local. Depois, volte à análise com Codex.")
            self._orientation_open()
            return
        evidence = build_codex_evidence(self.project, self.last_plan, self.result, orientation)
        summary = json.dumps(evidence, ensure_ascii=False, indent=2)
        dialog = tk.Toplevel(self)
        dialog.title("Dados para análise com Codex")
        dialog.geometry("760x600")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Leia o resumo abaixo. Somente este texto será enviado ao Codex após sua autorização.",
                  wraplength=700).pack(anchor="w")
        preview = scrolledtext.ScrolledText(frame, wrap="word", font=("Consolas", 9))
        preview.pack(fill="both", expand=True, pady=8)
        preview.insert("1.0", summary)
        preview.configure(state="disabled")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def authorize():
            dialog.destroy()
            self.ai_button.configure(state="disabled")
            self.status_var.set("Codex analisando o resumo aprovado...")
            plan = self.last_plan
            project = self.project
            result = self.result
            install = self.install

            def work():
                try:
                    response = run_codex(summary)
                    suggestions, candidate = validate_codex_recommendations(response, plan, orientation)
                    observations = [str(item)[:300] for item in response["observations"][:10]]
                    verified = []
                    for suggestion in suggestions:
                        comparison = verify_process_recommendation(
                            project, plan, result, suggestion,
                            SlicerCLI(install.executable))
                        if not comparison["verified"]:
                            observations.append(f"{suggestion.target_key}: hipótese sem validação; não aplicável.")
                            continue
                        observations.append(f"{suggestion.target_key}: fatiamento comparativo validado; "
                                            f"base {comparison['baseline']['filament_grams']} g, "
                                            f"proposta {comparison['proposal']['filament_grams']} g; "
                                            f"avisos {comparison['baseline']['warning_count']} → "
                                            f"{comparison['proposal']['warning_count']}.")
                        verified.append(suggestion)
                    self.ai_queue.put(("codex", tuple(verified), candidate, tuple(observations), None,
                                       (project, plan, orientation)))
                except Exception as exc:
                    self.ai_queue.put(("codex", (), None, (), exc, (project, plan, orientation)))

            threading.Thread(target=work, daemon=True).start()

        ttk.Button(buttons, text="Autorizar envio ao Codex", command=authorize).pack(side="left")
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right")

    def _poll_ai(self):
        try:
            item = self.ai_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.ai_button.configure(state="normal")
            if item[0] == "codex_apply":
                _, result, plan, error = item
                if error:
                    self.status_var.set("Falha ao aplicar orientação")
                    messagebox.showerror("Orientação Codex", str(error))
                else:
                    self.result = result
                    self.last_plan = plan
                    self._set_report(format_conversion_report(result, plan))
                    self.status_var.set("Cópia orientada validada" if result.success else "Falha; confira relatório")
                    if result.success and result.destination.exists():
                        self.open_button.configure(state="normal")
                self._ai_after = self.after(150, self._poll_ai)
                return
            if len(item) == 6 and item[0] == "codex":
                _, suggestions, candidate, observations, error, context = item
                if (self.project, self.last_plan, self.orientation_analysis) != context:
                    self.status_var.set("Projeto ou perfis mudaram; repita a análise com Codex")
                    self._ai_after = self.after(150, self._poll_ai)
                    return
                if error:
                    self.status_var.set("Codex indisponível")
                    messagebox.showerror("Codex", str(error))
                else:
                    self._review_codex(suggestions, candidate, observations)
                self._ai_after = self.after(150, self._poll_ai)
                return
            suggestions, error = item
            if error:
                self.status_var.set("IA indisponível")
                messagebox.showerror("Gemini", str(error))
            elif not suggestions:
                self.status_var.set("Nenhuma equivalência segura encontrada")
                messagebox.showinfo("Gemini", "Nenhuma sugestão passou pela validação de segurança e compatibilidade.")
            else:
                self._review_suggestions(suggestions)
        self._ai_after = self.after(150, self._poll_ai)

    def _review_codex(self, suggestions, candidate, observations):
        project, plan, orientation = self.project, self.last_plan, self.orientation_analysis
        dialog = tk.Toplevel(self)
        dialog.title("Revisar análise do Codex")
        dialog.geometry("800x500")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        report = scrolledtext.ScrolledText(frame, wrap="word", height=10)
        report.pack(fill="both", expand=True)
        lines = ["Observações do Codex (hipóteses; confira no fatiador):",
                 *(f"• {item}" for item in observations)]
        if candidate:
            lines.extend(["", f"Orientação proposta e fatiada: {candidate.label}"])
        if suggestions:
            lines.extend(["", "Configurações propostas:",
                          *(f"• {item.target_key} = {item.value}: {item.reason}" for item in suggestions)])
        report.insert("1.0", "\n".join(lines))
        report.configure(state="disabled")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=8)
        if candidate and self.orientation_analysis:
            def orient():
                if (self.project, self.last_plan, self.orientation_analysis) != (project, plan, orientation):
                    messagebox.showerror("Análise desatualizada", "Projeto ou perfis mudaram. Repita a análise.")
                    dialog.destroy()
                    return
                dialog.destroy()
                self._apply_codex_orientation(candidate)
            ttk.Button(buttons, text="Aplicar orientação em cópia", command=orient).pack(side="left")
        if suggestions:
            def settings():
                if (self.project, self.last_plan, self.orientation_analysis) != (project, plan, orientation):
                    messagebox.showerror("Análise desatualizada", "Projeto ou perfis mudaram. Repita a análise.")
                    dialog.destroy()
                    return
                dialog.destroy()
                self._review_suggestions(list(suggestions), single=True)
            ttk.Button(buttons, text="Revisar configurações", command=settings).pack(side="left", padx=8)
        ttk.Button(buttons, text="Fechar", command=dialog.destroy).pack(side="right")

    def _apply_codex_orientation(self, candidate):
        if not self.project or not self.last_plan or not self.install:
            return
        destination = filedialog.asksaveasfilename(
            title="Salvar cópia orientada", defaultextension=".3mf",
            initialfile=self.project.path.stem + "_Codex_ELEGOO.3mf",
            initialdir=str(self.project.path.parent), filetypes=[("Projeto 3MF", "*.3mf")])
        if not destination:
            return
        if Path(destination).exists() or Path(destination).resolve() == self.project.path.resolve():
            messagebox.showerror("Destino existente", "Escolha um novo nome para preservar os arquivos existentes.")
            return
        if not messagebox.askyesno("Confirmar orientação",
                                   f"Aplicar '{candidate.label}' em nova cópia e fatiar no ELEGOO Slicer?"):
            return
        self.status_var.set("Criando e fatiando a cópia orientada...")
        project, plan, install = self.project, self.last_plan, self.install

        def work():
            try:
                result = apply_orientation(project, plan, candidate, Path(destination),
                                           SlicerCLI(install.executable))
                self.ai_queue.put(("codex_apply", result, plan, None))
            except Exception as exc:
                self.ai_queue.put(("codex_apply", None, plan, exc))

        threading.Thread(target=work, daemon=True).start()

    def _review_suggestions(self, suggestions: list[Suggestion], *, single: bool = False):
        context = (self.project, self.last_plan, self.orientation_analysis)
        dialog = tk.Toplevel(self)
        dialog.title("Revisar sugestões de IA")
        dialog.geometry("780x470")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Selecione somente as sugestões que deseja aplicar na próxima exportação.",
                  wraplength=720).pack(anchor="w", pady=(0, 10))
        listing = tk.Listbox(frame, selectmode="single" if single else "multiple", font=("Consolas", 10))
        listing.pack(fill="both", expand=True)
        for item in suggestions:
            label = "Equivalência" if item.kind == "mapping" else "Recurso ELEGOO"
            listing.insert("end", f"{label}: {item.source_key or 'extra'} → {item.target_key} = {item.value} [{item.confidence}] — {item.reason}")

        def approve():
            if single and (self.project, self.last_plan, self.orientation_analysis) != context:
                messagebox.showerror("Análise desatualizada", "Projeto ou perfis mudaram. Repita a análise.")
                dialog.destroy()
                return
            self.ai_approved = [suggestions[index] for index in listing.curselection()]
            self.status_var.set(f"{len(self.ai_approved)} sugestões aprovadas; converta novamente para aplicá-las")
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Aplicar selecionadas na próxima conversão", command=approve).pack(side="left")
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right")

    def _open_result(self):
        if self.result and self.result.destination.exists() and self.install:
            try:
                subprocess.Popen([str(self.install.executable), str(self.result.destination)])
            except OSError as exc:
                messagebox.showerror("Não foi possível abrir", str(exc))


def launch_app() -> None:
    app = MakerElegooApp()
    app.mainloop()
