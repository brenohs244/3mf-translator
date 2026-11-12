"""Interface desktop para inspeção, seleção de perfis e conversão."""

from __future__ import annotations

import queue
import json
import subprocess
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from .ai import (AIError, Suggestion, apply_suggestions, build_manual_prompt,
                 parse_manual_response, suggest_equivalences)
from .converter import ConversionResult, convert_project
from .codex_cli import run_codex
from .codex_evidence import (build_codex_evidence,
                             validate_codex_recommendations, verify_process_recommendation)
from .mapping import ConversionPlan, build_conversion
from .orientation import FRONTS, load_scene, render_front_views
from .orientation_service import (OrientationAnalysis, apply_orientation,
                                  evaluate_orientations)
from .profiles import Profile, ProfileError, SlicerInstall, discover_slicer, list_profiles, resolve_profile
from .project import ProjectInfo, inspect_project
from .settings import load_settings, save_settings
from .slicer import SlicerCLI


def format_project_summary(project: ProjectInfo) -> str:
    lines = [f"Arquivo: {project.path.name}",
             f"Origem: {project.source_settings.get('printer_model', 'desconhecida')}",
             f"{len(project.plates)} placas · {len(project.objects)} objetos · {len(project.filaments)} filamentos",
             "Filamentos:"]
    lines.extend(f"  {filament.slot}. {filament.material} {filament.color} ({filament.profile or 'sem perfil'})"
                 for filament in project.filaments)
    if project.warnings:
        lines.extend(["Avisos:", *(f"  • {warning}" for warning in project.warnings)])
    return "\n".join(lines)


def format_conversion_report(result: ConversionResult, plan: ConversionPlan) -> str:
    lines = ["CONVERSÃO CONCLUÍDA" if result.success else "CONVERSÃO COM FALHA",
             result.message, "", f"Destino: {result.destination}",
             f"Máquina: {plan.machine.name}", f"Processo: {plan.process.name}",
             "Filamentos:"]
    lines.extend(f"  {index}. {profile.name}" for index, profile in enumerate(plan.filaments, 1))
    lines.extend(["", f"Parâmetros de processo transferidos: {len(plan.transferred)}",
                  f"Campos sem equivalência confirmada: {len(result.unmapped)}"])
    if result.geometry:
        lines.append("Malhas: " + ("preservadas (tolerância de 0,0001 mm)" if result.geometry.unchanged
                                     else "diferenças detectadas; confira antes de imprimir"))
    if result.validation:
        lines.append(f"Fatiamento: {result.validation.plate_count} placas verificadas")
        lines.extend(f"Aviso do fatiador: {warning}" for warning in result.validation.warnings)
    if plan.material_findings:
        lines.extend(["", "Mudanças de material/perfil:"])
        lines.extend(f"  Filamento {item.slot}: {item.key} {item.source} → {item.target}"
                     for item in plan.material_findings)
    if result.unmapped:
        lines.extend(["", "Campos a revisar (primeiros 30):"])
        lines.extend(f"  • {key}" for key in list(sorted(result.unmapped))[:30])
    lines.extend(["", "Confira a posição das peças, cores, suportes e prévia no ELEGOO Slicer antes de imprimir."])
    return "\n".join(lines)


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
        self.orientation_queue: queue.Queue = queue.Queue()
        self.orientation_cancel = threading.Event()
        self.orientation_dialog: tk.Toplevel | None = None
        self.orientation_analysis: OrientationAnalysis | None = None
        self.orientation_plan: ConversionPlan | None = None
        self.orientation_generation = 0

        self.file_var = tk.StringVar()
        self.nozzle_var = tk.StringVar(value=self.preferences["nozzle"])
        self.machine_var = tk.StringVar(value=self.preferences["machine"])
        self.process_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Selecione um projeto 3MF para começar")
        self.ai_provider_var = tk.StringVar(value="Codex")
        self._refreshing_profiles = False
        self._build_layout()
        self.nozzle_var.trace_add("write", lambda *_: self._refresh_profiles())
        self.process_var.trace_add("write", lambda *_: self._profiles_changed())
        self._refresh_profiles()
        self._worker_after = self.after(150, self._poll_worker)
        self._ai_after = self.after(150, self._poll_ai)
        self._orientation_after = self.after(150, self._poll_orientation)

    def destroy(self):
        self.orientation_cancel.set()
        for name in ("_worker_after", "_ai_after", "_orientation_after"):
            callback = getattr(self, name, None)
            if callback is not None:
                self.after_cancel(callback)
        super().destroy()

    def _build_layout(self):
        menu = tk.Menu(self)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Ajuste guiado por IA (sem API)", command=self._manual_ai)
        tools_menu.add_command(label="Analisar orientação de figura", command=self._orientation_open)
        menu.add_cascade(label="Ferramentas", menu=tools_menu)
        self.configure(menu=menu)
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Maker → ELEGOO", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Converta projetos MakerWorld usando os perfis reais da Centauri Carbon 2.").pack(anchor="w", pady=(2, 16))

        source = ttk.LabelFrame(outer, text="1  Projeto de origem", padding=12)
        source.pack(fill="x", pady=(0, 12))
        source.columnconfigure(0, weight=1)
        ttk.Entry(source, textvariable=self.file_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(source, text="Escolher 3MF", command=self._choose_file).grid(row=0, column=1)
        ttk.Button(source, text="Analisar", command=self._inspect_file).grid(row=0, column=2, padx=(8, 0))

        target = ttk.LabelFrame(outer, text="2  Perfis de destino", padding=12)
        target.pack(fill="x", pady=(0, 12))
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="Bico").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.nozzle_combo = ttk.Combobox(target, textvariable=self.nozzle_var,
                                         state="readonly", width=8)
        self.nozzle_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(target, text="Impressora").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        self.machine_combo = ttk.Combobox(target, textvariable=self.machine_var, state="readonly")
        self.machine_combo.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        self.machine_combo.bind("<<ComboboxSelected>>", lambda *_: self._refresh_dependents())
        ttk.Label(target, text="Processo").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        self.process_combo = ttk.Combobox(target, textvariable=self.process_var, state="readonly")
        self.process_combo.grid(row=2, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(target, text="Localizar ELEGOO Slicer", command=self._choose_slicer).grid(row=0, column=2, rowspan=3, padx=(12, 0))
        self.filament_frame = ttk.Frame(target)
        self.filament_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.filament_frame.columnconfigure(1, weight=1)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 12))
        self.convert_button = ttk.Button(actions, text="Converter e fatiar para validar", command=self._convert)
        self.convert_button.pack(side="left")
        self.orientation_button = ttk.Button(actions, text="Orientação de figura", command=self._orientation_open,
                                             state="disabled")
        self.orientation_button.pack(side="left", padx=(10, 0))
        self.open_button = ttk.Button(actions, text="Abrir no ELEGOO Slicer", command=self._open_result, state="disabled")
        self.open_button.pack(side="left", padx=(10, 0))
        self.ai_button = ttk.Button(actions, text="Analisar com IA (opcional)", command=self._analyze_ai, state="disabled")
        self.ai_button.pack(side="left", padx=(10, 0))
        ttk.Combobox(actions, textvariable=self.ai_provider_var, values=("Codex", "Gemini"),
                     state="readonly", width=8).pack(side="left", padx=(5, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        report_frame = ttk.LabelFrame(outer, text="3  Análise e relatório", padding=8)
        report_frame.pack(fill="both", expand=True)
        self.report = scrolledtext.ScrolledText(report_frame, wrap="word", font=("Consolas", 10), state="disabled")
        self.report.pack(fill="both", expand=True)
        self._set_report("O arquivo original permanece intacto. O G-code de validação é temporário e nunca é enviado à impressora.")

    def _set_report(self, content: str):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", content)
        self.report.configure(state="disabled")

    def _save_preferences(self):
        save_settings({"nozzle": self.nozzle_var.get(),
                       "machine": self.machine_var.get(),
                       "last_dir": str(Path(self.file_var.get()).parent) if self.file_var.get() else self.preferences["last_dir"],
                       "slicer_exe": str(self.install.executable) if self.install else self.preferences["slicer_exe"]})

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

    def _refresh_dependents(self):
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
        if self.process_var.get() not in options:
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
            self._clear_ai_approval()
            self.ai_button.configure(state="disabled")
            self.orientation_button.configure(state="normal")
            self.open_button.configure(state="disabled")
            self._set_report(format_project_summary(self.project))
            self._render_filaments()
            self.status_var.set("Projeto analisado")
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
        for row, filament in enumerate(self.project.filaments):
            ttk.Label(self.filament_frame, text=f"Filamento {filament.slot}: {filament.material} {filament.color}").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
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

    def _convert(self):
        if not self.project or not self.install:
            messagebox.showinfo("Dados incompletos", "Analise um 3MF e localize o ELEGOO Slicer primeiro.")
            return
        destination = filedialog.asksaveasfilename(title="Salvar projeto ELEGOO", defaultextension=".3mf",
                                                    initialfile=self.project.path.stem + "_ELEGOO.3mf",
                                                    initialdir=str(self.project.path.parent),
                                                    filetypes=[("Projeto 3MF", "*.3mf")])
        if not destination:
            return
        if Path(destination).exists():
            messagebox.showerror("Destino existente", "Escolha um nome novo para preservar arquivos existentes.")
            return
        try:
            machine, process, filaments = self._selected_profiles()
        except (IndexError, StopIteration):
            messagebox.showerror("Perfil ausente", "Escolha um processo e um perfil para cada filamento.")
            return
        self.convert_button.configure(state="disabled")
        self.ai_button.configure(state="disabled")
        self.status_var.set("Convertendo e fatiando... pode levar alguns minutos")
        project = self.project
        install = self.install
        approved = tuple(self.ai_approved)

        def work():
            try:
                plan = build_conversion(project, install, machine, process, filaments)
                if approved:
                    plan = replace(plan, process_settings=apply_suggestions(plan.process_settings, list(approved)))
                result = convert_project(project, plan, Path(destination), SlicerCLI(install.executable))
                self.worker_queue.put((result, plan, approved, None))
            except Exception as exc:
                self.worker_queue.put((None, None, approved, exc))

        threading.Thread(target=work, daemon=True).start()

    def _poll_worker(self):
        try:
            result, plan, approved, error = self.worker_queue.get_nowait()
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
                report = format_conversion_report(result, plan)
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
        priority = tk.StringVar(value="Equilibrada")
        purpose = tk.StringVar(value="Decorativa ou visual")
        for label, variable, options in (
            ("Prioridade", priority, ("Equilibrada", "Qualidade visual", "Resistência", "Velocidade", "Menos material")),
            ("Uso da peça", purpose, ("Decorativa ou visual", "Funcional, uso leve", "Funcional, com esforço mecânico",
                                      "Protótipo rápido", "Miniatura com muitos detalhes", "Acabamento para venda"))):
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
            context = {key: self.project.source_settings.get(key) for key in
                       ("printer_model", "filament_type", "nozzle_diameter")}
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
        key = simpledialog.askstring("Gemini", "Chave de API Gemini (não será salva):", show="*", parent=self)
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
        context = {name: self.project.source_settings.get(name) for name in
                   ("printer_model", "filament_type", "nozzle_diameter")}

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
