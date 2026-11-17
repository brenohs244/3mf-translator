import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.credentials import (
    clear_gemini_key,
    clear_github_token,
    get_gemini_key,
    get_github_token,
    save_gemini_key,
    save_github_token,
)


class CredentialsTest(unittest.TestCase):
    def test_save_and_retrieve_key(self):
        with TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "gemini.key"
            self.assertIsNone(get_gemini_key(key_file=key_file))
            save_gemini_key("AIzaSyTestKey123456", key_file=key_file)
            self.assertEqual(get_gemini_key(key_file=key_file), "AIzaSyTestKey123456")
            clear_gemini_key(key_file=key_file)
            self.assertIsNone(get_gemini_key(key_file=key_file))

            gh_file = Path(tmp) / "github.token"
            self.assertIsNone(get_github_token(key_file=gh_file))
            save_github_token("ghp_test_token_12345", key_file=gh_file)
            self.assertEqual(get_github_token(key_file=gh_file), "ghp_test_token_12345")
            clear_github_token(key_file=gh_file)
            self.assertIsNone(get_github_token(key_file=gh_file))
