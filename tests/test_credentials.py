import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.credentials import get_gemini_key, save_gemini_key, clear_gemini_key


class CredentialsTest(unittest.TestCase):
    def test_save_and_retrieve_key(self):
        with TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "gemini.key"
            self.assertIsNone(get_gemini_key(key_file=key_file))
            save_gemini_key("AIzaSyTestKey123456", key_file=key_file)
            self.assertEqual(get_gemini_key(key_file=key_file), "AIzaSyTestKey123456")
            clear_gemini_key(key_file=key_file)
            self.assertIsNone(get_gemini_key(key_file=key_file))
