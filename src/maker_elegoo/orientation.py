"""Leitura local e análise geométrica de uma figura em 3MF."""

from __future__ import annotations

import math
import re
import shutil
from array import array
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat
from zipfile import ZipFile

from .project import inspect_project


class OrientationError(ValueError):
    """A orientação deste projeto não pode ser analisada com segurança."""


IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
FRONTS = ("+X", "-X", "+Y", "-Y")


@dataclass(frozen=True)
class Scene:
    path: Path
    vertices: array
    triangles: array
    item_transform: tuple[float, ...]
    world_transform: tuple[float, ...]
    bounds: tuple[float, float, float, float, float, float]

    @property
    def vertex_count(self) -> int:
        return len(self.vertices) // 3

    @property
    def triangle_count(self) -> int:
        return len(self.triangles) // 3


@dataclass(frozen=True)
class Candidate:
    label: str
    item_transform: tuple[float, ...]
    bounds: tuple[float, float, float, float, float, float]
    contact_mm2: float
    overhang_mm2: float
    front_overhang_mm2: float
    score: float
    valid: bool
    reason: str
    is_current: bool = False
    load_note: str = ""


def parse_transform(value: str | None) -> tuple[float, ...]:
    if not value:
        return IDENTITY
    try:
        numbers = tuple(float(part) for part in value.split())
    except ValueError as exc:
        raise OrientationError("Transformação 3MF inválida") from exc
    if len(numbers) != 12 or not all(math.isfinite(number) for number in numbers):
        raise OrientationError("Transformação 3MF inválida")
    return numbers


def apply_transform(matrix: tuple[float, ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (matrix[0] * x + matrix[3] * y + matrix[6] * z + matrix[9],
            matrix[1] * x + matrix[4] * y + matrix[7] * z + matrix[10],
            matrix[2] * x + matrix[5] * y + matrix[8] * z + matrix[11])


def compose_transform(outer: tuple[float, ...], inner: tuple[float, ...]) -> tuple[float, ...]:
    result = []
    for column in range(3):
        basis = tuple(inner[column * 3 + row] for row in range(3))
        for row in range(3):
            result.append(sum(outer[axis * 3 + row] * basis[axis] for axis in range(3)))
    result.extend(apply_transform(outer, tuple(inner[9:12])))
    return tuple(result)


def _bounds(vertices: array, matrix: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
    minima = [math.inf] * 3
    maxima = [-math.inf] * 3
    for offset in range(0, len(vertices), 3):
        point = apply_transform(matrix, tuple(vertices[offset:offset + 3]))
        for axis, value in enumerate(point):
            minima[axis] = min(minima[axis], value)
            maxima[axis] = max(maxima[axis], value)
    return (minima[0], maxima[0], minima[1], maxima[1], minima[2], maxima[2])


def load_scene(path: Path, *, max_vertices: int = 1_500_000,
               max_triangles: int = 3_000_000) -> Scene:
    path = Path(path)
    project = inspect_project(path)
    if len(project.plates) != 1:
        raise OrientationError("A análise inicial aceita apenas uma placa")
    vertices = array("f")
    triangles = array("I")
    objects: dict[str, list[tuple[str, tuple[float, ...]]]] = {}
    items: list[tuple[str, tuple[float, ...]]] = []
    current_object: str | None = None
    mesh_object: str | None = None
    unit: str | None = None

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal current_object, mesh_object, unit
        tag = name.rsplit("}", 1)[-1]
        if tag == "model":
            unit = attrs.get("unit", "millimeter")
        elif tag == "object":
            current_object = attrs.get("id")
            if not current_object or current_object in objects:
                raise OrientationError("Objetos 3MF inválidos ou duplicados")
            objects[current_object] = []
        elif tag == "mesh":
            if mesh_object and mesh_object != current_object:
                raise OrientationError("A análise inicial aceita apenas uma malha")
            mesh_object = current_object
        elif tag == "vertex" and current_object == mesh_object:
            try:
                coordinates = tuple(float(attrs[axis]) for axis in ("x", "y", "z"))
            except (KeyError, ValueError) as exc:
                raise OrientationError("Vértice 3MF inválido") from exc
            if not all(math.isfinite(value) for value in coordinates):
                raise OrientationError("Vértice 3MF inválido")
            vertices.extend(coordinates)
            if len(vertices) // 3 > max_vertices:
                raise OrientationError("Malha grande demais para análise de orientação")
        elif tag == "triangle" and current_object == mesh_object:
            try:
                indices = tuple(int(attrs[key]) for key in ("v1", "v2", "v3"))
            except (KeyError, ValueError) as exc:
                raise OrientationError("Triângulo 3MF inválido") from exc
            if min(indices) < 0:
                raise OrientationError("Triângulo 3MF inválido")
            triangles.extend(indices)
            if len(triangles) // 3 > max_triangles:
                raise OrientationError("Malha grande demais para análise de orientação")
        elif tag == "component" and current_object:
            objects[current_object].append((attrs.get("objectid", ""), parse_transform(attrs.get("transform"))))
        elif tag == "item":
            items.append((attrs.get("objectid", ""), parse_transform(attrs.get("transform"))))

    def end(name: str) -> None:
        nonlocal current_object
        if name.rsplit("}", 1)[-1] == "object":
            current_object = None

    try:
        with ZipFile(path) as archive:
            info = archive.getinfo("3D/3dmodel.model")
            if info.file_size > 512_000_000:
                raise OrientationError("Modelo grande demais para análise de orientação")
            parser = expat.ParserCreate(namespace_separator="}")
            parser.StartElementHandler = start
            parser.EndElementHandler = end
            parser.StartDoctypeDeclHandler = lambda *_: (_ for _ in ()).throw(OrientationError("DTD não aceito"))
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    parser.Parse(chunk, False)
                parser.Parse(b"", True)
    except (OSError, KeyError, expat.ExpatError) as exc:
        raise OrientationError(f"Não foi possível analisar a malha: {exc}") from exc

    if unit != "millimeter":
        raise OrientationError("A análise inicial aceita apenas modelos em milímetros")
    if len(items) != 1:
        raise OrientationError("A análise inicial aceita apenas uma instância")
    if not mesh_object or not vertices or not triangles or max(triangles) >= len(vertices) // 3:
        raise OrientationError("Malha 3MF ausente ou inválida")
    object_id, item_transform = items[0]
    world_transform = item_transform
    seen: set[str] = set()
    while object_id != mesh_object:
        if object_id in seen or object_id not in objects or len(objects[object_id]) != 1:
            raise OrientationError("A instância deve conter uma única malha sem ciclo")
        seen.add(object_id)
        object_id, component_transform = objects[object_id][0]
        world_transform = compose_transform(world_transform, component_transform)
    return Scene(path, vertices, triangles, item_transform, world_transform,
                 _bounds(vertices, world_transform))


def render_front_views(scene: Scene, size: int = 220) -> dict[str, bytes]:
    if not 64 <= size <= 512:
        raise ValueError("Tamanho de prévia inválido")
    views = {}
    sample_step = max(1, scene.vertex_count // 250_000)
    for direction in FRONTS:
        if direction == "+X":
            project = lambda x, y, z: (-y, z, x)
        elif direction == "-X":
            project = lambda x, y, z: (y, z, -x)
        elif direction == "+Y":
            project = lambda x, y, z: (x, z, y)
        else:
            project = lambda x, y, z: (-x, z, -y)
        x0, x1, y0, y1, z0, z1 = scene.bounds
        horizontal_span = (y1 - y0) if direction.endswith("X") else (x1 - x0)
        center_horizontal = -(y0 + y1) / 2 if direction == "+X" else ((y0 + y1) / 2 if direction == "-X" else
                            ((x0 + x1) / 2 if direction == "+Y" else -(x0 + x1) / 2))
        scale = (size - 12) / max(horizontal_span, z1 - z0, 1e-6)
        depth = [-math.inf] * (size * size)
        for index in range(0, scene.vertex_count, sample_step):
            offset = index * 3
            world = apply_transform(scene.world_transform, tuple(scene.vertices[offset:offset + 3]))
            u, vertical, distance = project(*world)
            px = round((u - center_horizontal) * scale + size / 2)
            py = round(size / 2 - (vertical - (z0 + z1) / 2) * scale)
            if 0 <= px < size and 0 <= py < size:
                pixel = py * size + px
                depth[pixel] = max(depth[pixel], distance)
        visible = [value for value in depth if value != -math.inf]
        low, high = (min(visible), max(visible)) if visible else (0.0, 1.0)
        rgb = bytearray(size * size * 3)
        for pixel, value in enumerate(depth):
            shade = 245 if value == -math.inf else int(40 + 170 * (value - low) / max(high - low, 1e-6))
            rgb[pixel * 3:pixel * 3 + 3] = bytes((shade, shade, shade))
        views[direction] = f"P6\n{size} {size}\n255\n".encode("ascii") + rgb
    return views


def _rotation(axis: str, angle: float) -> tuple[float, ...]:
    cosine, sine = math.cos(angle), math.sin(angle)
    if axis == "X":
        return (1, 0, 0, 0, cosine, sine, 0, -sine, cosine, 0, 0, 0)
    return (cosine, 0, -sine, 0, 1, 0, sine, 0, cosine, 0, 0, 0)


def _printable_bounds(printable_area: list[str], printable_height: float) -> tuple[float, float, float, float, float]:
    try:
        points = [tuple(float(value) for value in point.split("x", 1)) for point in printable_area]
    except (ValueError, AttributeError) as exc:
        raise OrientationError("Área útil da impressora inválida") from exc
    if len(points) < 3 or not math.isfinite(printable_height) or printable_height <= 0:
        raise OrientationError("Área útil da impressora inválida")
    xs, ys = zip(*points)
    return min(xs), max(xs), min(ys), max(ys), printable_height


def rank_orientations(scene: Scene, front: str, printable_area: list[str],
                      printable_height: float, *, load_type: str = "nao_sei") -> list[Candidate]:
    if front not in FRONTS:
        raise OrientationError("Escolha a vista frontal da figura")
    bed_x0, bed_x1, bed_y0, bed_y1, max_height = _printable_bounds(printable_area, printable_height)
    rotations = [("Atual", IDENTITY, True),
                 ("+X para cima", _rotation("Y", -math.pi / 2), False),
                 ("-X para cima", _rotation("Y", math.pi / 2), False),
                 ("+Y para cima", _rotation("X", math.pi / 2), False),
                 ("-Y para cima", _rotation("X", -math.pi / 2), False),
                 ("Invertida", _rotation("X", math.pi), False)]
    tilt_axis = "Y" if front.endswith("X") else "X"
    tilt_sign = (-1 if front == "+X" else 1) if tilt_axis == "Y" else (1 if front == "+Y" else -1)
    for degrees in (10, 20):
        rotations.append((f"{degrees}° para trás", _rotation(tilt_axis, tilt_sign * math.radians(degrees)), False))

    world = array("f")
    for offset in range(0, len(scene.vertices), 3):
        world.extend(apply_transform(scene.world_transform, tuple(scene.vertices[offset:offset + 3])))
    x0, x1, y0, y1, z0, z1 = scene.bounds
    if front == "+X":
        front_axis, front_sign, width_axis = 0, 1, 1
    elif front == "-X":
        front_axis, front_sign, width_axis = 0, -1, 1
    elif front == "+Y":
        front_axis, front_sign, width_axis = 1, 1, 0
    else:
        front_axis, front_sign, width_axis = 1, -1, 0
    front_limits = (x0, x1) if front_axis == 0 else (y0, y1)
    width_limits = (y0, y1) if width_axis == 1 else (x0, x1)
    front_max = max(front_sign * value for value in front_limits)
    front_span = front_limits[1] - front_limits[0]
    width_center = sum(width_limits) / 2
    width_span = width_limits[1] - width_limits[0]
    step = max(1, scene.triangle_count // 300_000)
    candidates: list[Candidate] = []

    for label, rotation, current in rotations:
        if current:
            transformed_bounds = scene.bounds
            item_transform = scene.item_transform
            rotated_min_z = scene.bounds[4]
        else:
            minima = [math.inf] * 3
            maxima = [-math.inf] * 3
            for offset in range(0, len(world), 3):
                point = apply_transform(rotation, tuple(world[offset:offset + 3]))
                for axis, value in enumerate(point):
                    minima[axis] = min(minima[axis], value)
                    maxima[axis] = max(maxima[axis], value)
            rotated_min_z = minima[2]
            dx = (bed_x0 + bed_x1 - minima[0] - maxima[0]) / 2
            dy = (bed_y0 + bed_y1 - minima[1] - maxima[1]) / 2
            shift = (*IDENTITY[:9], dx, dy, -rotated_min_z)
            item_transform = compose_transform(shift, compose_transform(rotation, scene.item_transform))
            transformed_bounds = (minima[0] + dx, maxima[0] + dx,
                                  minima[1] + dy, maxima[1] + dy, 0.0, maxima[2] - minima[2])

        contact = overhang = front_overhang = 0.0
        for triangle in range(0, scene.triangle_count, step):
            ids = [int(scene.triangles[triangle * 3 + index]) * 3 for index in range(3)]
            ax, ay, az = world[ids[0]:ids[0] + 3]
            bx, by, bz = world[ids[1]:ids[1] + 3]
            cx, cy, cz = world[ids[2]:ids[2] + 3]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            norm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm <= 1e-12:
                continue
            area = norm * step / 2
            down = rotation[2] * nx + rotation[5] * ny + rotation[8] * nz
            if down < -0.70710678 * norm:
                overhang += area
                centroid_front = front_sign * ((ax, ay, az)[front_axis] +
                                               (bx, by, bz)[front_axis] +
                                               (cx, cy, cz)[front_axis]) / 3
                centroid_width = ((ax, ay, az)[width_axis] +
                                  (bx, by, bz)[width_axis] +
                                  (cx, cy, cz)[width_axis]) / 3
                if (centroid_front >= front_max - 0.45 * front_span
                        and abs(centroid_width - width_center) <= 0.35 * width_span):
                    front_overhang += area
            height_values = [rotation[2] * x + rotation[5] * y + rotation[8] * z
                             for x, y, z in ((ax, ay, az), (bx, by, bz), (cx, cy, cz))]
            if max(abs(value - rotated_min_z) for value in height_values) <= 0.5:
                contact += area * abs(down) / norm

        fits = (transformed_bounds[0] >= bed_x0 - 1e-4 and transformed_bounds[1] <= bed_x1 + 1e-4
                and transformed_bounds[2] >= bed_y0 - 1e-4 and transformed_bounds[3] <= bed_y1 + 1e-4
                and transformed_bounds[4] >= -1e-4 and transformed_bounds[5] <= max_height + 1e-4)
        score = 4 * front_overhang + 0.4 * overhang - 0.2 * min(contact, 1000)
        load_note = ""
        if load_type in {"tracao_eixo_z", "flexao_lateral", "impacto"}:
            dx_b = transformed_bounds[1] - transformed_bounds[0]
            dy_b = transformed_bounds[3] - transformed_bounds[2]
            dz_b = transformed_bounds[5] - transformed_bounds[4]
            max_xy = max(dx_b, dy_b)
            if dz_b > 1.35 * max_xy:
                score += min(250.0, (dz_b - max_xy) * 3.0)
                load_note = "Camadas transversais ao eixo alto (ponto fraco potencial sob tração/flexão)."
            elif max_xy >= 1.35 * dz_b:
                score -= min(250.0, (max_xy - dz_b) * 3.0)
                load_note = (
                    "Camadas alinhadas ao maior vão (favorece continuidade em tração/flexão, "
                    "porém pode exigir suportes; resistência exige teste físico)."
                )
            else:
                load_note = "Proporção equilibrada; confira a direção da carga em relação às camadas no Slicer."
        candidates.append(Candidate(label, item_transform, transformed_bounds, contact, overhang,
                                    front_overhang, score, fits, "" if fits else "Fora do volume útil", current, load_note))

    minimum_contact = max(10.0, 0.12 * max(item.contact_mm2 for item in candidates))
    checked = []
    for item in candidates:
        if item.contact_mm2 < minimum_contact:
            checked.append(Candidate(item.label, item.item_transform, item.bounds, item.contact_mm2,
                                     item.overhang_mm2, item.front_overhang_mm2, item.score, False,
                                     "Contato insuficiente com a mesa", item.is_current, item.load_note))
        else:
            checked.append(item)
    return [checked[0], *sorted(checked[1:], key=lambda item: (not item.valid, item.score))]


_ITEM_TAG = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?item\b[^>]{0,4096}>")
_TRANSFORM_ATTR = re.compile(rb"\btransform\s*=\s*(['\"])[^'\"]*\1")


def write_oriented_copy(source: Path, candidate: Candidate, destination: Path) -> Path:
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    if source.resolve() == destination.resolve():
        raise OrientationError("A origem não pode ser sobrescrita")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".orientation.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    matrix = " ".join(f"{value:.12g}" for value in candidate.item_transform).encode("ascii")
    replaced = 0

    def patch_tag(match: re.Match[bytes]) -> bytes:
        nonlocal replaced
        replaced += 1
        tag = match.group(0)
        attribute = b'transform="' + matrix + b'"'
        if _TRANSFORM_ATTR.search(tag):
            return _TRANSFORM_ATTR.sub(attribute, tag, count=1)
        if tag.endswith(b"/>"):
            return tag[:-2] + b" " + attribute + b"/>"
        return tag[:-1] + b" " + attribute + b">"

    try:
        with ZipFile(source) as original, ZipFile(temporary, "w") as copy:
            for info in original.infolist():
                with original.open(info) as reader, copy.open(info, "w") as writer:
                    if info.filename != "3D/3dmodel.model":
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
                            writer.write(_ITEM_TAG.sub(patch_tag, prefix))
                    writer.write(_ITEM_TAG.sub(patch_tag, pending))
        if replaced != 1:
            raise OrientationError("Não foi possível alterar uma única instância 3MF")
        temporary.replace(destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()
