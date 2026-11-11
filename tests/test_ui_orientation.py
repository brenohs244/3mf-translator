import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]

from maker_elegoo.orientation import rank_orientations, load_scene
from maker_elegoo.profiles import SlicerInstall
from maker_elegoo.project import inspect_project
from maker_elegoo.ui import MakerElegooApp
from test_orientation import write_figure


class UIOrientationTests(unittest.TestCase):
    def test_four_local_views_can_be_selected_before_slicing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_figure(root / "figure.3mf")
            with patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    app.project = inspect_project(source)
                    app.install = SlicerInstall(root / "elegoo-slicer.exe", root)
                    app._orientation_open()
                    deadline = time.monotonic() + 5
                    while len(app.orientation_images) < 4 and time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.02)
                    self.assertEqual(len(app.orientation_images), 4)
                    app.orientation_front.set("+X")
                    self.assertEqual(app.orientation_front.get(), "+X")
                finally:
                    app.destroy()

    def test_changing_front_invalidates_a_previous_recommendation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_figure(root / "figure.3mf")
            with patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    app.project = inspect_project(source)
                    app.install = SlicerInstall(root / "elegoo-slicer.exe", root)
                    app._orientation_open()
                    app.orientation_analysis = SimpleNamespace(front="-Y", recommended=SimpleNamespace(valid=True,
                                                                                                          is_current=False))
                    app.orientation_apply_button.configure(state="normal")
                    app.orientation_front.set("+X")
                    self.assertIsNone(app.orientation_analysis)
                    self.assertEqual(str(app.orientation_apply_button.cget("state")), "disabled")
                finally:
                    app.destroy()

    def test_declining_recommendation_keeps_source_and_destination_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_figure(root / "figure.3mf")
            before = source.read_bytes()
            destination = root / "oriented.3mf"
            with patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    app.project = inspect_project(source)
                    app.install = SlicerInstall(root / "elegoo-slicer.exe", root)
                    scene = load_scene(source)
                    candidate = next(item for item in rank_orientations(
                        scene, "-Y", ["0x0", "256x0", "256x256", "0x256"], 256)
                        if item.label == "Invertida")
                    app.orientation_analysis = SimpleNamespace(recommended=candidate)
                    app.orientation_plan = SimpleNamespace()
                    app.orientation_dialog = tk.Toplevel(app)
                    with patch("maker_elegoo.ui.filedialog.asksaveasfilename", return_value=str(destination)), \
                         patch("maker_elegoo.ui.messagebox.askyesno", return_value=False):
                        app._orientation_apply()
                    self.assertFalse(destination.exists())
                    self.assertEqual(source.read_bytes(), before)
                finally:
                    app.destroy()
