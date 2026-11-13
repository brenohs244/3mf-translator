"""Armazenamento seguro de credenciais via Windows DPAPI ou fallback local."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _default_key_path() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home())
    return base / "MakerElegoo" / ".gemini.key"


def _protect_data(data: bytes) -> bytes:
    if os.name != "nt":
        # Fallback para ambientes não-Windows (testes/CI)
        return b"PLAIN:" + data

    crypt32 = ctypes.windll.crypt32
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()

    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "MakerElegooGeminiKey",
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError("Falha ao proteger dados com Windows DPAPI")

    try:
        protected = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return protected
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree(blob_out.pbData)


def _unprotect_data(data: bytes) -> bytes:
    if not data:
        return b""
    if data.startswith(b"PLAIN:"):
        return data[6:]
    if os.name != "nt":
        return data

    crypt32 = ctypes.windll.crypt32
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError("Falha ao decodificar dados com Windows DPAPI")

    try:
        unprotected = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return unprotected
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree(blob_out.pbData)


def save_gemini_key(key: str, *, key_file: Path | None = None) -> None:
    target = key_file or _default_key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _protect_data(key.strip().encode("utf-8"))
    target.write_bytes(encrypted)


def get_gemini_key(*, key_file: Path | None = None) -> str | None:
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    target = key_file or _default_key_path()
    if not target.is_file():
        return None
    try:
        data = target.read_bytes()
        decrypted = _unprotect_data(data)
        return decrypted.decode("utf-8").strip() or None
    except Exception:
        return None


def clear_gemini_key(*, key_file: Path | None = None) -> None:
    target = key_file or _default_key_path()
    if target.is_file():
        try:
            target.unlink()
        except OSError:
            pass
