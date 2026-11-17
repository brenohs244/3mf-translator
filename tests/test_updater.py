import gc
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ui import MakerElegooApp
from maker_elegoo.updater import (
    ReleaseAsset,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateError,
    check_latest_release,
    download_and_verify_installer,
    is_newer_version,
    launch_silent_installer,
    normalize_repo,
    parse_sha256_manifest,
    parse_version,
)


class _Resp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._buf.close()


class UpdaterTests(unittest.TestCase):
    def test_version_parsing_and_repo_validation(self):
        self.assertEqual(parse_version("v0.2.1"), (0, 2, 1))
        self.assertTrue(is_newer_version("v0.2.0", "0.1.0"))
        self.assertTrue(is_newer_version("0.10.0", "0.2.9"))
        self.assertFalse(is_newer_version("0.2.0", "v0.2.0"))
        self.assertEqual(normalize_repo("https://github.com/brenohs244/3mf-translator"), "brenohs244/3mf-translator")
        self.assertEqual(normalize_repo("brenohs244/3mf-translator-releases"), "brenohs244/3mf-translator-releases")
        with self.assertRaises(UpdateError):
            normalize_repo("http://evil.local/foo")
        with self.assertRaises(UpdateError):
            normalize_repo("apenas-um-segmento")

    def test_check_latest_release_handles_404_private_repo_without_resource_warning(self):
        def transport_404(req, timeout=20):
            raise error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            with self.assertRaises(UpdateError) as ctx:
                check_latest_release("brenohs244/3mf-translator", current_version="0.1.0", transport=transport_404)
            self.assertIn("privado", str(ctx.exception).lower())
            del ctx
            gc.collect()
        self.assertEqual([w for w in caught if issubclass(w.category, ResourceWarning)], [])

    def test_download_and_verify_installer_enforces_sha256_and_https(self):
        payload = b"MZ-FAKE-INNO-SETUP-BINARY-12345"
        good_sha = hashlib.sha256(payload).hexdigest()
        manifest = f"{good_sha}  MakerElegoo-Setup-v0.2.0.exe\n".encode("utf-8")

        release_json = {
            "tag_name": "v0.2.0",
            "name": "Versao 0.2.0",
            "body": "Mais rapido e com instalador.",
            "html_url": "https://github.com/brenohs244/3mf-translator/releases/tag/v0.2.0",
            "assets": [
                {
                    "name": "MakerElegoo-Setup-v0.2.0.exe",
                    "browser_download_url": "https://github.com/brenohs244/3mf-translator/releases/download/v0.2.0/MakerElegoo-Setup-v0.2.0.exe",
                    "size": len(payload),
                },
                {
                    "name": "checksums-v0.2.0.txt",
                    "browser_download_url": "https://github.com/brenohs244/3mf-translator/releases/download/v0.2.0/checksums-v0.2.0.txt",
                    "size": len(manifest),
                },
            ],
        }

        def transport(req, timeout=20):
            url = req.full_url
            if url.endswith("/releases/latest"):
                return _Resp(json.dumps(release_json).encode("utf-8"))
            if url.endswith("checksums-v0.2.0.txt"):
                return _Resp(manifest)
            if url.endswith("MakerElegoo-Setup-v0.2.0.exe"):
                return _Resp(payload)
            raise AssertionError(f"URL inesperada: {url}")

        res = check_latest_release("brenohs244/3mf-translator", current_version="0.1.0", transport=transport)
        self.assertTrue(res.update_available)
        self.assertIsNotNone(res.latest)
        self.assertEqual(res.latest.version, "0.2.0")

        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            exe_path = download_and_verify_installer(res.latest, dest_dir, transport=transport)
            self.assertTrue(exe_path.is_file())
            self.assertEqual(exe_path.read_bytes(), payload)

            # Lançador silencioso Inno Setup
            launcher = MagicMock()
            launch_silent_installer(exe_path, launcher=launcher)
            launcher.assert_called_once()
            cmd = launcher.call_args.args[0]
            self.assertEqual(cmd[0], str(exe_path))
            self.assertIn("/VERYSILENT", cmd)
            self.assertIn("/NORESTART", cmd)

            # Adulteração no binário deve falhar fechando e apagar arquivo parcial
            bad_manifest = f"{'0' * 64}  MakerElegoo-Setup-v0.2.0.exe\n".encode("utf-8")

            def bad_transport(req, timeout=20):
                if req.full_url.endswith("checksums-v0.2.0.txt"):
                    return _Resp(bad_manifest)
                return transport(req, timeout=timeout)

            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                download_and_verify_installer(res.latest, dest_dir / "bad", transport=bad_transport)
            self.assertFalse((dest_dir / "bad" / "MakerElegoo-Setup-v0.2.0.exe").exists())

        # Rejeita URL insegura HTTP
        bad_release = json.loads(json.dumps(release_json))
        bad_release["assets"][0]["browser_download_url"] = "http://github.com/a.exe"
        with self.assertRaisesRegex(UpdateError, "HTTPS"):
            check_latest_release(
                "brenohs244/3mf-translator",
                current_version="0.1.0",
                transport=lambda req, timeout=20: _Resp(json.dumps(bad_release).encode("utf-8")),
            )

    def test_parse_sha256_manifest_variants(self):
        parsed = parse_sha256_manifest(
            f"{'a'*64}  dist/MakerElegoo-Setup-v0.2.0.exe\n"
            f"{'B'*64} *MakerElegoo-Windows-Portable.zip\n"
        )
        self.assertEqual(parsed["MakerElegoo-Setup-v0.2.0.exe"], "a" * 64)
        self.assertEqual(parsed["MakerElegoo-Windows-Portable.zip"], "b" * 64)

    def test_ui_update_flow_requires_consent_and_cleans_up_poller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "APPDATA": str(root / "EmptyAppData"),
                "ProgramFiles": str(root / "EmptyProgramFiles"),
                "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs"),
            }
            fake_exe = root / "MakerElegoo-Setup-v0.2.0.exe"
            fake_exe.write_bytes(b"setup")
            rel = ReleaseInfo(
                tag_name="v0.2.0",
                version="0.2.0",
                name="v0.2.0",
                notes="Notas de teste",
                html_url="https://github.com/brenohs244/3mf-translator/releases/tag/v0.2.0",
                installer_asset=ReleaseAsset("MakerElegoo-Setup-v0.2.0.exe", "https://github.com/a.exe", 5),
                checksums_asset=ReleaseAsset("checksums-v0.2.0.txt", "https://github.com/a.txt", 5),
            )
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    self.assertIn("_update_after", app._POLL_HANDLE_ATTRS)
                    app.update_queue.put(("check", False, "brenohs244/3mf-translator", None, UpdateCheckResult("0.1.0", rel, True), None))
                    with patch("maker_elegoo.ui.messagebox.askyesno", return_value=False) as ask_spy, \
                         patch.object(app, "_start_update_download") as dl_spy:
                        app._poll_update()
                        ask_spy.assert_called_once()
                        dl_spy.assert_not_called()

                    app.update_queue.put(("downloaded", False, rel, None, fake_exe, None))
                    with patch("maker_elegoo.ui.messagebox.askyesno", return_value=True), \
                         patch("maker_elegoo.ui.launch_silent_installer") as launch_spy:
                        app._poll_update()
                        launch_spy.assert_called_once_with(fake_exe)
                finally:
                    if not getattr(app, "_closing", False):
                        app.destroy()
                self.assertTrue(app._closing)


if __name__ == "__main__":
    unittest.main()
