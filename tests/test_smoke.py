import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class SmokeTests(unittest.TestCase):
    def test_main_launches_interface(self):
        from maker_elegoo import __main__

        with patch.object(__main__, "launch_app") as launch:
            __main__.main()
        launch.assert_called_once_with()
