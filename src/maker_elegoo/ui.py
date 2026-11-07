"""Interface desktop para inspeção, seleção de perfis e conversão."""

from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from .ai import Suggestion, apply_suggestions, suggest_equivalences
from .converter import ConversionResult, convert_project
from .mapping import ConversionPlan, build_conversion
from .profiles import Profile, ProfileError, SlicerInstall, discover_slicer, list_profiles
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
        self.process_profiles: list[Profile] = []
        self.filament_profiles: list[Profile] = []
        self.filament_vars: list[tk.StringVar] = []
        self.worker_queue: queue.Queue = queue.Queue()
        self.ai_queue: queue.Queue = queue.Queue()

        self.file_var = tk.StringVar()
        self.nozzle_var = tk.StringVar(value=self.preferences["nozzle"])
        self.process_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Selecione um projeto 3MF para começar")
        self._build_layout()
        self.nozzle_var.trace_add("write", lambda *_: self._refresh_profiles())
        self.process_var.trace_add("write", lambda *_: self._clear_ai_approval())
        self._refresh_profiles()
        self.after(150, self._poll_worker)
        self.after(150, self._poll_ai)

    def _build_layout(self):
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
        ttk.Combobox(target, textvariable=self.nozzle_var, values=("0.2", "0.4", "0.8"),
                     state="readonly", width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(target, text="Processo").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        self.process_combo = ttk.Combobox(target, textvariable=self.process_var, state="readonly")
        self.process_combo.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(target, text="Localizar ELEGOO Slicer", command=self._choose_slicer).grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self.filament_frame = ttk.Frame(target)
        self.filament_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.filament_frame.columnconfigure(1, weight=1)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 12))
        self.convert_button = ttk.Button(actions, text="Converter e fatiar para validar", command=self._convert)
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Abrir no ELEGOO Slicer", command=self._open_result, state="disabled")
        self.open_button.pack(side="left", padx=(10, 0))
        self.ai_button = ttk.Button(actions, text="Analisar com IA (opcional)", command=self._analyze_ai, state="disabled")
        self.ai_button.pack(side="left", padx=(10, 0))
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
                       "last_dir": str(Path(self.file_var.get()).parent) if self.file_var.get() else self.preferences["last_dir"],
                       "slicer_exe": str(self.install.executable) if self.install else self.preferences["slicer_exe"]})

    def _choose_slicer(self):
        filename = filedialog.askopenfilename(title="Localize elegoo-slicer.exe", filetypes=[("Executável", "*.exe")])
        if filename:
            self.preferences["slicer_exe"] = filename
            self._refresh_profiles()

    def _refresh_profiles(self):
        self._clear_ai_approval()
        try:
            custom = self.preferences.get("slicer_exe")
            self.install = discover_slicer(executable=Path(custom) if custom else None)
            nozzle = self.nozzle_var.get()
            self.process_profiles = list_profiles(self.install, "process", nozzle)
            self.filament_profiles = list_profiles(self.install, "filament", nozzle)
            options = [profile.name for profile in self.process_profiles]
            self.process_combo["values"] = options
            if self.process_var.get() not in options:
                self.process_var.set(next((name for name in options if "Standard" in name), options[0] if options else ""))
            self._render_filaments()
            self.status_var.set(f"Perfis carregados para bico {nozzle} mm")
            self._save_preferences()
        except (ProfileError, OSError) as exc:
            self.install = None
            self.status_var.set(str(exc))

    def _choose_file(self):
        filename = filedialog.askopenfilename(title="Projeto MakerWorld", initialdir=self.preferences.get("last_dir") or None,
                                               filetypes=[("Projeto 3MF", "*.3mf")])
        if filename:
            self.file_var.set(filename)
            self._inspect_file()

    def _inspect_file(self):
        try:
            self.project = inspect_project(Path(self.file_var.get()))
            self.result = None
            self.last_plan = None
            self._clear_ai_approval()
            self.ai_button.configure(state="disabled")
            self.open_button.configure(state="disabled")
            self._set_report(format_project_summary(self.project))
            self._render_filaments()
            self.status_var.set("Projeto analisado")
            self._save_preferences()
        except Exception as exc:
            self.project = None
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
            ttk.Combobox(self.filament_frame, textvariable=variable, values=options,
                         state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
            self.filament_vars.append(variable)

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
            machine = list_profiles(self.install, "machine", self.nozzle_var.get())[0]
            process = next(profile for profile in self.process_profiles if profile.name == self.process_var.get())
            filaments = [next(profile for profile in self.filament_profiles if profile.name == variable.get())
                         for variable in self.filament_vars]
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
        self.after(150, self._poll_worker)

    def _clear_ai_approval(self):
        self.ai_approved = []

    def _analyze_ai(self):
        if not self.result or not self.last_plan or not self.result.output_project:
            messagebox.showinfo("IA opcional", "Converta o projeto uma vez antes de analisar campos não traduzidos.")
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

    def _poll_ai(self):
        try:
            suggestions, error = self.ai_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.ai_button.configure(state="normal")
            if error:
                self.status_var.set("IA indisponível")
                messagebox.showerror("Gemini", str(error))
            elif not suggestions:
                self.status_var.set("Nenhuma equivalência segura encontrada")
                messagebox.showinfo("Gemini", "Nenhuma sugestão passou pela validação de segurança e compatibilidade.")
            else:
                self._review_suggestions(suggestions)
        self.after(150, self._poll_ai)

    def _review_suggestions(self, suggestions: list[Suggestion]):
        dialog = tk.Toplevel(self)
        dialog.title("Revisar sugestões do Gemini")
        dialog.geometry("780x470")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Selecione somente as sugestões que deseja aplicar na próxima exportação.",
                  wraplength=720).pack(anchor="w", pady=(0, 10))
        listing = tk.Listbox(frame, selectmode="multiple", font=("Consolas", 10))
        listing.pack(fill="both", expand=True)
        for item in suggestions:
            label = "Equivalência" if item.kind == "mapping" else "Recurso ELEGOO"
            listing.insert("end", f"{label}: {item.source_key or 'extra'} → {item.target_key} = {item.value} [{item.confidence}] — {item.reason}")

        def approve():
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
