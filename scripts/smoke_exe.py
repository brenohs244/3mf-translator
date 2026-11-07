"""Start the packaged Windows app and verify its main window appears."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    exe = Path(__file__).resolve().parents[1] / "dist" / "MakerElegoo.exe"
    if not exe.is_file():
        raise FileNotFoundError(exe)

    user32 = ctypes.windll.user32
    titles: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append((hwnd, buffer.value))
        return True

    callback = callback_type(collect)
    with tempfile.TemporaryDirectory(prefix="maker-elegoo-smoke-") as config_dir:
        env = os.environ.copy()
        env["MAKER_ELEGOO_CONFIG_DIR"] = config_dir
        process = subprocess.Popen([str(exe)], env=env)
        window = None
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"O executável saiu antes de abrir a janela: {process.returncode}")
                titles.clear()
                user32.EnumWindows(callback, 0)
                window = next((hwnd for hwnd, title in titles if title == "Maker → ELEGOO"), None)
                if window is not None:
                    print("Janela principal abriu com sucesso.")
                    return 0
                time.sleep(0.25)
            raise TimeoutError("A janela principal não abriu em 25 segundos")
        finally:
            if window is not None:
                user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
