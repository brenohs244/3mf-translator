"""Gerador paramétrico offline de peça rápida de calibração (contração XY e folgas)."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

from .converter import ConversionResult, convert_project
from .mapping import build_conversion
from .profiles import Profile, SlicerInstall
from .project import inspect_project
from .slicer import SlicerCLI


NOMINAL_BAR_MM = 50.0
CALIBRATION_CLEARANCES_MM = (0.15, 0.20, 0.30)


@dataclass(frozen=True)
class ShrinkageStats:
    nominal_mm: float
    measured_mm: float
    shrinkage_pct: float
    recommended_filament_shrink: str
    xy_scale_factor: float


def compute_shrinkage_stats(
    measured_bar_mm: float,
    nominal_mm: float = NOMINAL_BAR_MM,
) -> ShrinkageStats:
    """Calcula contração percentual observada e fator `filament_shrink` correspondente."""
    if not math.isfinite(measured_bar_mm) or not math.isfinite(nominal_mm) or nominal_mm <= 0:
        raise ValueError("Medida física inválida.")
    ratio = measured_bar_mm / nominal_mm
    if ratio < 0.90 or ratio > 1.05:
        raise ValueError(
            f"Medida {measured_bar_mm:.2f} mm fora da faixa plausível para barra de {nominal_mm:.0f} mm (90%–105%)."
        )
    shrink_pct = (1.0 - ratio) * 100.0
    filament_shrink_pct = ratio * 100.0
    return ShrinkageStats(
        nominal_mm=nominal_mm,
        measured_mm=round(measured_bar_mm, 3),
        shrinkage_pct=round(shrink_pct, 3),
        recommended_filament_shrink=f"{filament_shrink_pct:.1f}%",
        xy_scale_factor=round(nominal_mm / measured_bar_mm, 5),
    )


def _box_mesh(
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    return verts, tris


def _comb_gauge_mesh(
    xs: tuple[float, ...] = (100.0, 108.0, 114.15, 120.0, 126.20, 132.0, 138.30, 146.0),
    y_tip: float = 126.0,
    y_mid: float = 136.0,
    y_back: float = 143.0,
    z0: float = 0.0,
    z1: float = 4.0,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Constrói um pente de folgas estanque sem interseções nem T-junctions."""
    # Índice 2D compartilhado para topo (z1) e base (z0) garantindo arestas conformes.
    coords: list[tuple[float, float]] = []
    idx_back: list[int] = []
    idx_mid: list[int] = []
    idx_tip: dict[int, int] = {}

    for i, x_val in enumerate(xs):
        idx_back.append(len(coords))
        coords.append((x_val, y_back))
        idx_mid.append(len(coords))
        coords.append((x_val, y_mid))
    for bay in (0, 2, 4, 6):
        idx_tip[bay] = len(coords)
        coords.append((xs[bay], y_tip))
        idx_tip[bay + 1] = len(coords)
        coords.append((xs[bay + 1], y_tip))

    n = len(coords)
    verts = [(x_v, y_v, z0) for x_v, y_v in coords] + [(x_v, y_v, z1) for x_v, y_v in coords]
    tris: list[tuple[int, int, int]] = []

    def add_quad_xy(a: int, b: int, c: int, d: int) -> None:
        # CCW no plano XY (a->b->c normal +Z): base recebe orientação invertida (-Z), topo normal (+Z).
        tris.append((a, c, b))
        tris.append((a, d, c))
        tris.append((n + a, n + b, n + c))
        tris.append((n + a, n + c, n + d))

    # Faixa traseira contínua (y_mid -> y_back) em todas as colunas
    for i in range(len(xs) - 1):
        add_quad_xy(idx_mid[i], idx_mid[i + 1], idx_back[i + 1], idx_back[i])

    # Quatro dentes frontais (y_tip -> y_mid) criando vãos exatos +0.15, +0.20, +0.30 mm para pino de 6.00 mm
    for bay in (0, 2, 4, 6):
        add_quad_xy(idx_tip[bay], idx_tip[bay + 1], idx_mid[bay + 1], idx_mid[bay])

    # Perímetro externo CCW formando paredes verticais fechadas
    loop: list[int] = [idx_back[0]]
    for bay in (0, 2, 4, 6):
        loop.append(idx_tip[bay])
        loop.append(idx_tip[bay + 1])
        if bay < 6:
            loop.append(idx_mid[bay + 1])
            loop.append(idx_mid[bay + 2])
    for i in range(len(xs) - 1, 0, -1):
        loop.append(idx_back[i])

    for idx_edge, p in enumerate(loop):
        q = loop[(idx_edge + 1) % len(loop)]
        tris.append((p, q, n + q))
        tris.append((p, n + q, n + p))

    return verts, tris


def _object_xml(obj_id: int, verts: list[tuple[float, float, float]], tris: list[tuple[int, int, int]]) -> str:
    v_lines = "\n".join(f'          <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    t_lines = "\n".join(f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return (
        f'    <object id="{obj_id}" type="model">\n'
        '      <mesh>\n'
        '        <vertices>\n'
        f"{v_lines}\n"
        '        </vertices>\n'
        '        <triangles>\n'
        f"{t_lines}\n"
        '        </triangles>\n'
        '      </mesh>\n'
        '    </object>'
    )


def write_calibration_source_3mf(
    destination: Path,
    *,
    nozzle_mm: str = "0.4",
    material: str = "PLA",
    layer_height: str = "0.2",
) -> Path:
    """Escreve um projeto 3MF rápido de calibração (barra 50,00 mm + folgas 0,15/0,20/0,30 mm + pino 6,00 mm)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    bar_verts, bar_tris = _box_mesh(-25.0, -5.0, -2.0, 25.0, 5.0, 2.0)
    comb_verts, comb_tris = _comb_gauge_mesh(
        xs=(-23.0, -15.0, -8.85, -3.0, 3.20, 9.0, 15.30, 23.0),
        y_tip=-8.5,
        y_mid=1.5,
        y_back=8.5,
        z0=-2.0,
        z1=2.0,
    )
    pin_verts, pin_tris = _box_mesh(-3.0, -5.0, -2.0, 3.0, 5.0, 2.0)

    objects_xml = "\n".join([
        _object_xml(1, bar_verts, bar_tris),
        _object_xml(2, comb_verts, comb_tris),
        _object_xml(3, pin_verts, pin_tris),
    ])
    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        '  <resources>\n'
        f"{objects_xml}\n"
        '  </resources>\n'
        '  <build>\n'
        '    <item objectid="1" transform="1 0 0 0 1 0 0 0 1 128 116 2"/>\n'
        '    <item objectid="2" transform="1 0 0 0 1 0 0 0 1 123 134.5 2"/>\n'
        '    <item objectid="3" transform="1 0 0 0 1 0 0 0 1 123 153 2"/>\n'
        '  </build>\n'
        '</model>\n'
    )
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<config>\n'
        '  <object id="1"><metadata key="name" value="Barra_50mm_Contracao"/><metadata key="extruder" value="1"/></object>\n'
        '  <object id="2"><metadata key="name" value="Pente_Folgas_0.15_0.20_0.30"/><metadata key="extruder" value="1"/></object>\n'
        '  <object id="3"><metadata key="name" value="Pino_Prova_6mm"/><metadata key="extruder" value="1"/></object>\n'
        '  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n'
        '    <metadata key="plater_name" value="Calibracao"/>\n'
        '    <model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/></model_instance>\n'
        '    <model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="1"/></model_instance>\n'
        '    <model_instance><metadata key="object_id" value="3"/><metadata key="instance_id" value="2"/></model_instance>\n'
        '  </plate>\n'
        '</config>\n'
    )
    project_cfg = json.dumps({
        "filament_type": [material],
        "layer_height": layer_height,
        "nozzle_diameter": [nozzle_mm],
        "curr_bed_type": "Textured PEI Plate",
    }, ensure_ascii=False)
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n'
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '</Types>\n'
    )
    with ZipFile(destination, "w") as archive:
        archive.writestr("[Content_Types].xml", ct)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml)
        archive.writestr("Metadata/project_settings.config", project_cfg)
        archive.writestr("Metadata/model_settings.config", model_settings)
    return destination


def export_calibration_3mf(
    install: SlicerInstall,
    machine: Profile,
    process: Profile,
    filament: Profile,
    destination: Path,
    *,
    runner: Callable = subprocess.run,
) -> ConversionResult:
    """Exporta e fatia no ELEGOO Slicer a peça rápida de calibração usando os perfis escolhidos."""
    destination = Path(destination)
    nozzle_val = machine.data.get("nozzle_diameter", ["0.4"])
    nozzle_mm = str(nozzle_val[0] if isinstance(nozzle_val, list) and nozzle_val else nozzle_val)
    mat_val = filament.data.get("filament_type", ["PLA"])
    material = str(mat_val[0] if isinstance(mat_val, list) and mat_val else mat_val)
    layer_h = str(process.data.get("layer_height", "0.2"))

    with tempfile.TemporaryDirectory(prefix="maker-elegoo-calib-") as scratch:
        src = write_calibration_source_3mf(
            Path(scratch) / "calibration_source.3mf",
            nozzle_mm=nozzle_mm,
            material=material,
            layer_height=layer_h,
        )
        project = inspect_project(src, include_geometry=False)
        plan = build_conversion(project, install, machine, process, [filament])
        return convert_project(project, plan, destination, SlicerCLI(install.executable, runner=runner))
