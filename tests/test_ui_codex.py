import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]

from maker_elegoo.project import inspect_project
from maker_elegoo.ui import MakerElegooApp
from test_orientation import write_figure


class UICodexTests(unittest.TestCase):
    def test_cancelled_payload_review_never_invokes_codex(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = inspect_project(write_figure(root / "figure.3mf"))
            with patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs")}):
                app = MakerElegooApp()
                try:
                    app.project = project
                    app.last_plan = SimpleNamespace()
                    app.orientation_plan = app.last_plan
                    app.orientation_analysis = SimpleNamespace(front="-Y")
                    app.result = SimpleNamespace(output_project=project)
                    with patch("maker_elegoo.ui.build_codex_evidence", return_value={"safe": "summary"}), \
                         patch("maker_elegoo.ui.run_codex") as codex:
                        app._analyze_codex()
                        dialog = next(child for child in app.winfo_children()
                                      if child.winfo_class() == "Toplevel")
                        dialog.destroy()
                        self.assertFalse(codex.called)
                finally:
                    app.destroy()
