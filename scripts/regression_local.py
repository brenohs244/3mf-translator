"""Executa regressão local: python scripts/regression_local.py --output DIR arquivos.3mf ..."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import build_conversion
from maker_elegoo.profiles import discover_slicer, list_profiles, resolve_profile
from maker_elegoo.project import inspect_project
from maker_elegoo.regression import RegressionCase, run_regression
from maker_elegoo.slicer import SlicerCLI


def main() -> int:
    parser = argparse.ArgumentParser(description="Regressão local de 3MF no ELEGOO Slicer")
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nozzle", default="0.4", choices=("0.2", "0.4", "0.8"))
    args = parser.parse_args()
    install = discover_slicer()
    machine = list_profiles(install, "machine", args.nozzle)[0]
    process = list_profiles(install, "process", args.nozzle, machine=machine)[0]
    available = list_profiles(install, "filament", args.nozzle, machine=machine)
    if not available:
        raise ValueError("Nenhum perfil de filamento compatível")
    cases = []
    for source in args.sources:
        project = inspect_project(source)
        selected = []
        for filament in project.filaments:
            match = next((profile for profile in available
                          if filament.material.upper() in [str(value).upper() for value in
                             resolve_profile(profile, install).get("filament_type", [])]), None)
            if match is None:
                raise ValueError(f"Sem perfil compatível com {filament.material} em {source.name}")
            selected.append(match)
        cases.append(RegressionCase(source, build_conversion(project, install, machine, process, selected)))
    print(run_regression(cases, args.output, SlicerCLI(install.executable)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
