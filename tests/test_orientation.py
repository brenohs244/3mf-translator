import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.orientation import (OrientationError, load_scene, rank_orientations,
                                      render_front_views, write_oriented_copy)


VERTICES = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
            (0, 0, 20), (10, 0, 20), (10, 10, 20), (0, 10, 20), (5, -3, 15)]
TRIANGLES = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
             (4, 8, 5), (5, 8, 6)]


def write_figure(path: Path, *, items: int = 1, transform: str | None = None) -> Path:
    coordinates = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in VERTICES)
    faces = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in TRIANGLES)
    matrix = transform or "1 0 0 0 1 0 0 0 1 100 100 0"
    build = "".join(f'<item objectid="2" transform="{matrix}"/>' for _ in range(items))
    model = (f'<model unit="millimeter"><resources><object id="1"><mesh><vertices>{coordinates}'
             f'</vertices><triangles>{faces}</triangles></mesh></object><object id="2">'
             '<components><component objectid="1"/></components></object></resources>'
             f'<build>{build}</build></model>')
    with ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/project_settings.config", json.dumps({"filament_type": ["PLA"]}))
        archive.writestr("Metadata/model_settings.config",
                         '<config><plate><model_instance/></plate></config>')
    return path


class OrientationTests(unittest.TestCase):
    def test_loads_single_mesh_and_existing_build_transform(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_figure(Path(folder) / "figure.3mf", transform="0 1 0 -1 0 0 0 0 1 100 100 0")
            scene = load_scene(source)
        self.assertEqual(scene.vertex_count, 9)
        self.assertEqual(scene.triangle_count, 14)
        self.assertEqual(scene.bounds, (90.0, 103.0, 100.0, 110.0, 0.0, 20.0))

    def test_rejects_multiple_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_figure(Path(folder) / "two.3mf", items=2)
            with self.assertRaisesRegex(OrientationError, "uma instância"):
                load_scene(source)

    def test_front_views_are_local_ppm_and_show_asymmetry(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = load_scene(write_figure(Path(folder) / "figure.3mf"))
        views = render_front_views(scene, size=96)
        self.assertEqual(set(views), {"+X", "-X", "+Y", "-Y"})
        self.assertTrue(all(value.startswith(b"P6\n96 96\n255\n") for value in views.values()))
        self.assertNotEqual(views["+Y"], views["-Y"])

    def test_rank_keeps_current_and_rejects_positions_outside_bed(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = load_scene(write_figure(Path(folder) / "figure.3mf"))
            candidates = rank_orientations(scene, "-Y", ["0x0", "32x0", "32x32", "0x32"], 30)
        self.assertEqual(candidates[0].label, "Atual")
        self.assertFalse(candidates[0].valid)
        self.assertEqual(len({item.label for item in candidates}), len(candidates))
        self.assertTrue(all(item.bounds[5] <= 30 for item in candidates if item.valid))
        self.assertTrue(any(not item.valid for item in candidates))
        self.assertTrue(any(item.valid for item in candidates))

    def test_oriented_copy_changes_only_build_transform(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_figure(Path(folder) / "figure.3mf", transform="0 1 0 -1 0 0 0 0 1 100 100 0")
            before = source.read_bytes()
            scene = load_scene(source)
            candidates = rank_orientations(scene, "-Y", ["0x0", "256x0", "256x256", "0x256"], 256)
            turned = next(item for item in candidates if item.label == "+X para cima")
            destination = Path(folder) / "turned.3mf"
            write_oriented_copy(source, turned, destination)
            after = load_scene(destination)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual((after.vertex_count, after.triangle_count), (scene.vertex_count, scene.triangle_count))
            self.assertAlmostEqual(after.bounds[4], 0, places=3)
            self.assertAlmostEqual(after.bounds[5] - after.bounds[4], 13, places=2)
            with self.assertRaises(FileExistsError):
                write_oriented_copy(source, turned, destination)

    def test_copy_handles_item_tag_at_stream_boundary_and_attribute_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = write_figure(root / "original.3mf")
            with ZipFile(original) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            model = members["3D/3dmodel.model"].replace(
                b'<item objectid="2" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>',
                b'<item transform="1 0 0 0 1 0 0 0 1 100 100 0" objectid="2"/>')
            start = model.index(b"<item ")
            pad = (1024 * 1024 - 8192 - 4) - start
            model = model[:start] + b" " * pad + model[start:]
            model = model.replace(b"</build>", b" " * 20000 + b"</build>")
            members["3D/3dmodel.model"] = model
            source = root / "boundary.3mf"
            with ZipFile(source, "w") as archive:
                for name, content in members.items():
                    archive.writestr(name, content)
            scene = load_scene(source)
            candidate = next(item for item in rank_orientations(
                scene, "-Y", ["0x0", "256x0", "256x256", "0x256"], 256)
                if item.label == "+X para cima")
            destination = root / "turned.3mf"
            write_oriented_copy(source, candidate, destination)
            self.assertNotEqual(load_scene(destination).item_transform, scene.item_transform)

    def test_copy_adds_transform_to_self_closing_item_without_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = write_figure(root / "original.3mf")
            with ZipFile(original) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            members["3D/3dmodel.model"] = members["3D/3dmodel.model"].replace(
                b'<item objectid="2" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>',
                b'<item objectid="2"/>')
            source = root / "no_transform.3mf"
            with ZipFile(source, "w") as archive:
                for name, content in members.items():
                    archive.writestr(name, content)
            scene = load_scene(source)
            candidate = next(item for item in rank_orientations(
                scene, "-Y", ["0x0", "256x0", "256x256", "0x256"], 256)
                if item.label == "+X para cima")
            destination = root / "turned.3mf"
            write_oriented_copy(source, candidate, destination)
            self.assertNotEqual(load_scene(destination).item_transform, scene.item_transform)
