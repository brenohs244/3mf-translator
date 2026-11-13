"""Redimensionamento uniforme seguro de projetos 3MF e detector de perda de qualidade."""

from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat
from zipfile import ZipFile

from .geometry_check import analyze_project_geometry
from .orientation import IDENTITY, _ITEM_TAG, _TRANSFORM_ATTR, _printable_bounds, compose_transform, parse_transform
from .project import inspect_project


class ScaleError(ValueError):
    """Projeto não suporta redimensionamento automático ou excede o volume útil."""


@dataclass(frozen=True)
class ScaleRisk:
    scale_factor: float
    original_size_mm: tuple[float, float, float]
    new_size_mm: tuple[float, float, float]
    warnings: tuple[str, ...]
    recommend_finer_layer: str | None
    recommend_nozzle_02: bool


@dataclass(frozen=True)
class RescaleResult:
    path: Path
    scale_factor: float
    original_size_mm: tuple[float, float, float]
    new_size_mm: tuple[float, float, float]
    risk: ScaleRisk
    removed_variable_layer: bool


def analyze_scale_risk(
    scale_factor: float,
    original_size_mm: tuple[float, float, float],
    *,
    nozzle_mm: float = 0.4,
    purpose: str = "decorativa",
) -> ScaleRisk:
    if not math.isfinite(scale_factor) or scale_factor <= 0:
        raise ScaleError("Fator de escala deve ser maior que zero")
    new_size = tuple(round(dim * scale_factor, 2) for dim in original_size_mm)
    warnings: list[str] = []
    recommend_layer: str | None = None
    recommend_02 = False

    if scale_factor < 0.99:
        pct = scale_factor * 100.0
        warnings.append(
            f"Redução para {pct:.0f}% ({new_size[0]:.1f}×{new_size[1]:.1f}×{new_size[2]:.1f} mm) "
            "diminui na mesma proporção relevos, paredes finas e detalhes superficiais."
        )
        if nozzle_mm >= 0.35 and (scale_factor <= 0.72 or min(new_size) < 18.0):
            recommend_layer = "0.12"
            warnings.append(
                f"Com bico {nozzle_mm:g} mm, detalhes reduzidos perdem definição; "
                "recomenda-se camada 0.12 mm e parede Arachne."
            )
        if nozzle_mm >= 0.35 and (scale_factor <= 0.60 or (scale_factor <= 0.70 and purpose == "decorativa")):
            recommend_02 = True
            warnings.append(
                "Redução severa em peça detalhada: avalie bico 0.2 mm se rostos, textos ou adornos "
                "ficarem finos demais para a largura de linha de 0.4 mm."
            )
        if purpose in {"moveis", "chaveiro_articulado"}:
            warnings.append(
                "ALERTA CRÍTICO: reduzir peças móveis ou articuladas abaixo de 100% encolhe as folgas "
                "internas e pode travar ou fundir as articulações."
            )
    elif scale_factor > 1.01:
        warnings.append(
            f"Ampliação para {scale_factor * 100:.0f}% aumenta tempo, consumo de material e distância de pontes."
        )

    return ScaleRisk(
        scale_factor=scale_factor,
        original_size_mm=tuple(round(v, 2) for v in original_size_mm),
        new_size_mm=new_size,
        warnings=tuple(warnings),
        recommend_finer_layer=recommend_layer,
        recommend_nozzle_02=recommend_02,
    )


def _single_item_transform(path: Path) -> tuple[float, ...]:
    items: list[tuple[float, ...]] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        if name.rsplit("}", 1)[-1] == "item":
            try:
                items.append(parse_transform(attrs.get("transform")))
            except Exception as exc:
                raise ScaleError(f"Transformação 3MF inválida: {exc}") from exc

    with ZipFile(path) as archive:
        if "3D/3dmodel.model" not in archive.namelist():
            raise ScaleError("3MF sem 3D/3dmodel.model")
        parser = expat.ParserCreate(namespace_separator="}")
        parser.StartElementHandler = start
        parser.StartDoctypeDeclHandler = lambda *_: (_ for _ in ()).throw(ScaleError("DTD não aceito"))
        with archive.open("3D/3dmodel.model") as stream:
            while chunk := stream.read(1024 * 1024):
                parser.Parse(chunk, False)
            parser.Parse(b"", True)
    if len(items) != 1:
        raise ScaleError("O redimensionamento inicial suporta apenas uma única instância/peça")
    return items[0]


def rescale_3mf(
    source: Path,
    destination: Path,
    *,
    scale_percent: float | None = None,
    target_height_mm: float | None = None,
    printable_area: list[str] | tuple[str, ...] = ("0x0", "256x0", "256x256", "0x256"),
    printable_height: float = 256.0,
    nozzle_mm: float = 0.4,
    purpose: str = "decorativa",
) -> RescaleResult:
    source, destination = Path(source), Path(destination)
    if (scale_percent is None) == (target_height_mm is None):
        raise ScaleError("Informe escala percentual OU altura Z desejada em mm")
    if destination.exists():
        raise FileExistsError(destination)
    if source.resolve() == destination.resolve():
        raise ScaleError("A origem não pode ser sobrescrita")

    project = inspect_project(source, include_geometry=False)
    if len(project.plates) != 1:
        raise ScaleError("O redimensionamento inicial aceita apenas projetos com 1 placa")

    old_item_transform = _single_item_transform(source)
    geom = analyze_project_geometry(source)
    if geom.triangle_count == 0 or geom.size_z <= 1e-6:
        raise ScaleError("Geometria vazia ou altura Z inválida para redimensionar")

    if target_height_mm is not None:
        if not math.isfinite(target_height_mm) or target_height_mm <= 0:
            raise ScaleError("Altura Z alvo deve ser maior que zero")
        scale_factor = target_height_mm / geom.size_z
    else:
        assert scale_percent is not None
        if not math.isfinite(scale_percent) or scale_percent <= 0:
            raise ScaleError("Percentual de escala deve ser maior que zero")
        scale_factor = scale_percent / 100.0

    bed_x0, bed_x1, bed_y0, bed_y1, max_z = _printable_bounds(list(printable_area), printable_height)
    new_sx = geom.size_x * scale_factor
    new_sy = geom.size_y * scale_factor
    new_sz = geom.size_z * scale_factor
    if new_sx > (bed_x1 - bed_x0) + 1e-4 or new_sy > (bed_y1 - bed_y0) + 1e-4 or new_sz > max_z + 1e-4:
        raise ScaleError(
            f"Peça redimensionada ({new_sx:.1f}×{new_sy:.1f}×{new_sz:.1f} mm) excede o volume útil "
            f"({bed_x1 - bed_x0:.0f}×{bed_y1 - bed_y0:.0f}×{max_z:.0f} mm)"
        )

    x0, x1, y0, y1, z0, _ = geom.bounds
    dx = (bed_x0 + bed_x1) / 2.0 - scale_factor * (x0 + x1) / 2.0
    dy = (bed_y0 + bed_y1) / 2.0 - scale_factor * (y0 + y1) / 2.0
    dz = -scale_factor * z0
    scale_translate = (
        scale_factor, 0.0, 0.0,
        0.0, scale_factor, 0.0,
        0.0, 0.0, scale_factor,
        dx, dy, dz,
    )
    new_item_transform = compose_transform(scale_translate, old_item_transform)
    matrix_bytes = " ".join(f"{val:.12g}" for val in new_item_transform).encode("ascii")

    replaced = 0

    def patch_item(match: re.Match[bytes]) -> bytes:
        nonlocal replaced
        replaced += 1
        tag = match.group(0)
        attr = b'transform="' + matrix_bytes + b'"'
        if _TRANSFORM_ATTR.search(tag):
            return _TRANSFORM_ATTR.sub(attr, tag, count=1)
        if tag.endswith(b"/>"):
            return tag[:-2] + b" " + attr + b"/>"
        return tag[:-1] + b" " + attr + b">"

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".scale.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)

    removed_var_layer = False
    try:
        with ZipFile(source) as original, ZipFile(temporary, "w") as copy:
            for info in original.infolist():
                normalized = info.filename.replace("\\", "/")
                if normalized == "Metadata/layer_heights_profile.txt":
                    removed_var_layer = True
                    continue
                with original.open(info) as reader, copy.open(info, "w") as writer:
                    if normalized != "3D/3dmodel.model":
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        continue
                    pending = b""
                    while chunk := reader.read(1024 * 1024):
                        pending += chunk
                        safe = max(0, len(pending) - 8192)
                        if safe:
                            opening = pending.rfind(b"<", max(0, safe - 4096), safe)
                            if opening >= 0 and pending.find(b">", opening, safe) < 0:
                                safe = opening
                            prefix, pending = pending[:safe], pending[safe:]
                            writer.write(_ITEM_TAG.sub(patch_item, prefix))
                    writer.write(_ITEM_TAG.sub(patch_item, pending))
        if replaced != 1:
            raise ScaleError("Não foi possível atualizar a instância única no 3D/3dmodel.model")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    risk = analyze_scale_risk(
        scale_factor,
        (geom.size_x, geom.size_y, geom.size_z),
        nozzle_mm=nozzle_mm,
        purpose=purpose,
    )
    return RescaleResult(
        path=destination,
        scale_factor=scale_factor,
        original_size_mm=(round(geom.size_x, 2), round(geom.size_y, 2), round(geom.size_z, 2)),
        new_size_mm=(round(new_sx, 2), round(new_sy, 2), round(new_sz, 2)),
        risk=risk,
        removed_variable_layer=removed_var_layer,
    )
