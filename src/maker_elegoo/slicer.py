"""Exportação e validação via linha de comando do ELEGOO Slicer."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

from .mapping import ConversionPlan
from .project import ProjectInfo


@dataclass(frozen=True)
class ExportResult:
    success: bool
    destination: Path
    message: str


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    plate_count: int
    message: str
    warnings: tuple[str, ...] = ()


def _details(result: subprocess.CompletedProcess, folder: Path) -> str:
    output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part and part.strip())
    if output:
        return output[-2000:]
    logs = sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if logs:
        return logs[0].read_text(encoding="utf-8", errors="replace")[-2000:].strip()
    return f"ELEGOO Slicer terminou com código {result.returncode}"


def _patched_source(project: ProjectInfo, repairs: dict, destination: Path) -> Path:
    if not repairs:
        return project.path.resolve()
    with ZipFile(project.path) as source, ZipFile(destination, "w") as target:
        for info in source.infolist():
            if info.filename == "Metadata/project_settings.config":
                settings = dict(project.source_settings)
                settings.update(repairs)
                target.writestr(info, json.dumps(settings, ensure_ascii=False).encode("utf-8"))
            else:
                with source.open(info) as stream_in, target.open(info, "w") as stream_out:
                    shutil.copyfileobj(stream_in, stream_out, length=1024 * 1024)
    return destination


class SlicerCLI:
    def __init__(self, executable: Path, *, runner: Callable = subprocess.run):
        self.executable = Path(executable)
        self._runner = runner

    def _call(self, args: list[str], folder: Path, timeout: int):
        return self._runner(args, cwd=folder, capture_output=True, text=True,
                            timeout=timeout, shell=False)

    def export(self, project: ProjectInfo, plan: ConversionPlan, destination: Path) -> ExportResult:
        destination = Path(destination).resolve()
        if destination.exists():
            raise FileExistsError(f"Destino já existe: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="maker-elegoo-") as scratch:
            folder = Path(scratch)
            input_path = _patched_source(project, plan.source_repairs, folder / "input.3mf")
            machine_path = folder / "machine.json"
            process_path = folder / "process.json"
            machine_path.write_text(json.dumps(plan.machine_settings, ensure_ascii=False), encoding="utf-8")
            process_path.write_text(json.dumps(plan.process_settings, ensure_ascii=False), encoding="utf-8")
            filament_paths = []
            for index, config in enumerate(plan.filament_settings, 1):
                path = folder / f"filament_{index}.json"
                path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                filament_paths.append(str(path))
            args = [str(self.executable), "--allow-newer-file", "--load-settings",
                    f"{machine_path};{process_path}", "--load-filaments", ";".join(filament_paths),
                    "--export-3mf", str(destination), str(input_path)]
            try:
                result = self._call(args, folder, 300)
            except subprocess.TimeoutExpired:
                return ExportResult(False, destination, "Exportação excedeu o tempo limite")
            except OSError as exc:
                return ExportResult(False, destination, f"Falha ao iniciar ELEGOO Slicer: {exc}")
            if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
                return ExportResult(False, destination, _details(result, folder))
            return ExportResult(True, destination, "Projeto ELEGOO exportado")

    def validate(self, project: Path, plate_count: int) -> ValidationResult:
        with tempfile.TemporaryDirectory(prefix="maker-elegoo-slice-") as scratch:
            folder = Path(scratch)
            args = [str(self.executable), "--slice", "0", "--outputdir",
                    str(folder), str(Path(project).resolve())]
            try:
                result = self._call(args, folder, 600)
            except subprocess.TimeoutExpired:
                return ValidationResult(False, 0, "Fatiamento excedeu o tempo limite")
            except OSError as exc:
                return ValidationResult(False, 0, f"Falha ao iniciar ELEGOO Slicer: {exc}")
            if result.returncode != 0:
                return ValidationResult(False, 0, _details(result, folder))
            gcodes = [path for path in folder.glob("plate_*.gcode") if path.stat().st_size > 0]
            if len(gcodes) < plate_count:
                return ValidationResult(False, len(gcodes),
                                        f"G-code gerado para {len(gcodes)} de {plate_count} placas")
            warnings = tuple(line for line in (result.stderr or "").splitlines()
                             if "warning" in line.lower() or "aviso" in line.lower())
            return ValidationResult(True, len(gcodes), "Todas as placas foram fatiadas", warnings)
