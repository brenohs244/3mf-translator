"""Exportação e validação via linha de comando do ELEGOO Slicer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zipfile import ZipFile, is_zipfile

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
    estimated_seconds: int | None = None
    filament_grams: float | None = None


def _gcode_metrics(path: Path) -> tuple[int | None, float | None]:
    seconds = None
    grams = None
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("; estimated printing time (normal mode) ="):
                parts = re.findall(r"(\d+)\s*([hms])", line.partition("=")[2])
                if parts:
                    seconds = sum(int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
                                  for value, unit in parts)
            elif line.startswith("; total filament used [g] ="):
                try:
                    grams = float(line.partition("=")[2].strip())
                except ValueError:
                    pass
    return seconds, grams


def _details(result: subprocess.CompletedProcess, folder: Path) -> str:
    output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part and part.strip())
    if output:
        return output[-2000:]
    logs = sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if logs:
        return logs[0].read_text(encoding="utf-8", errors="replace")[-2000:].strip()
    return f"ELEGOO Slicer terminou com código {result.returncode}"


def _rewrite_project_settings(source_zip: Path, dest_zip: Path, settings: dict) -> None:
    """Reescreve Metadata/project_settings.config mantendo os demais itens do 3MF."""
    with ZipFile(source_zip) as source, ZipFile(dest_zip, "w") as target:
        for info in source.infolist():
            if info.filename == "Metadata/project_settings.config":
                target.writestr(info, json.dumps(settings, ensure_ascii=False).encode("utf-8"))
            else:
                with source.open(info) as stream_in, target.open(info, "w") as stream_out:
                    shutil.copyfileobj(stream_in, stream_out, length=1024 * 1024)


def _patched_source(project: ProjectInfo, repairs: dict, destination: Path) -> Path:
    if not repairs:
        return project.path.resolve()
    settings = dict(project.source_settings)
    for key, value in repairs.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    _rewrite_project_settings(project.path, destination, settings)
    return destination


def _sync_exported_prime_tower(destination: Path, wanted: object) -> None:
    """Restaura enable_prime_tower quando --export-3mf o descarta em projetos multicoloridos."""
    if wanted != "1" or not is_zipfile(destination):
        return
    with ZipFile(destination) as archive:
        if "Metadata/project_settings.config" not in archive.namelist():
            return
        try:
            settings = json.loads(archive.read("Metadata/project_settings.config"))
        except (ValueError, UnicodeDecodeError):
            return
    if not isinstance(settings, dict) or settings.get("enable_prime_tower") == "1":
        return
    settings["enable_prime_tower"] = "1"
    temporary = destination.with_name(f"{destination.name}.tmp")
    try:
        _rewrite_project_settings(destination, temporary, settings)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


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
            _sync_exported_prime_tower(destination, plan.process_settings.get("enable_prime_tower"))
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
            gcodes = [folder / f"plate_{number}.gcode" for number in range(1, plate_count + 1)]
            present = [path for path in gcodes if path.is_file() and path.stat().st_size > 0]
            if len(present) != plate_count:
                missing = [str(number) for number, path in enumerate(gcodes, 1) if path not in present]
                return ValidationResult(False, len(present),
                                        f"G-code ausente ou vazio nas placas: {', '.join(missing)}")
            warnings = tuple(line for line in (result.stderr or "").splitlines()
                             if "warning" in line.lower() or "aviso" in line.lower())
            metrics = [_gcode_metrics(path) for path in gcodes]
            seconds = sum(item[0] for item in metrics) if all(item[0] is not None for item in metrics) else None
            grams = sum(item[1] for item in metrics) if all(item[1] is not None for item in metrics) else None
            return ValidationResult(True, len(gcodes), "Todas as placas foram fatiadas",
                                    warnings, seconds, grams)
