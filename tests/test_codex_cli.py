import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.codex_cli import CodexError, run_codex


class CodexCLITests(unittest.TestCase):
    def test_uses_ephemeral_read_only_schema_and_empty_directory(self):
        def runner(command, **kwargs):
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertEqual(command[command.index("--output-schema") + 1], "schema.json")
            self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [Path(kwargs["cwd"]) / "schema.json"])
            self.assertIn('"machine"', kwargs["input"])
            return SimpleNamespace(returncode=0, stdout='{"suggestions":[],"orientation_id":"","observations":[]}', stderr="")

        with patch("maker_elegoo.codex_cli.shutil.which", return_value="codex.exe"):
            result = run_codex('{"machine":"CC2"}', runner=runner)
        self.assertEqual(result["suggestions"], [])

    def test_missing_cli_and_invalid_response_fail_closed(self):
        with patch("maker_elegoo.codex_cli.shutil.which", return_value=None):
            with self.assertRaises(CodexError):
                run_codex("{}")
        with patch("maker_elegoo.codex_cli.shutil.which", return_value="codex.exe"):
            with self.assertRaises(CodexError):
                run_codex("{}", runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="no json", stderr=""))
