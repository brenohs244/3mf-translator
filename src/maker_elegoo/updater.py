"""Atualização automática segura via GitHub Releases (HTTPS + verificação SHA-256)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib import error, parse, request

from . import __version__

DEFAULT_UPDATE_REPO = "brenohs244/3mf-translator"
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(RuntimeError):
    """Erro ao consultar, baixar ou validar atualização pelo GitHub."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0
    api_url: str = ""


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    version: str
    name: str
    notes: str
    html_url: str
    installer_asset: ReleaseAsset
    checksums_asset: ReleaseAsset


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest: ReleaseInfo | None
    update_available: bool


def normalize_repo(raw: str) -> str:
    text = (raw or "").strip().rstrip("/")
    if text.lower().startswith("https://github.com/"):
        text = text[len("https://github.com/"):]
    if text.lower().endswith(".git"):
        text = text[:-4]
    if not _REPO_RE.fullmatch(text):
        raise UpdateError(
            "Repositório GitHub inválido. Informe no formato 'usuario/repositorio' "
            "(ex.: brenohs244/3mf-translator)."
        )
    return text


def _require_https_url(url: str, *, label: str = "URL de atualização") -> str:
    parsed = parse.urlparse((url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise UpdateError(f"{label} rejeitada: apenas endereços HTTPS válidos são aceitos.")
    return parsed.geturl()


def parse_version(raw: str) -> tuple[int, ...]:
    cleaned = (raw or "").strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    core = cleaned.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for piece in core.split("."):
        m = re.match(r"^\d+", piece.strip())
        if not m:
            break
        parts.append(int(m.group(0)))
    if not parts:
        raise UpdateError(f"Versão inválida: {raw!r}")
    return tuple(parts)


def is_newer_version(latest: str, current: str) -> bool:
    a = list(parse_version(latest))
    b = list(parse_version(current))
    width = max(len(a), len(b))
    a.extend([0] * (width - len(a)))
    b.extend([0] * (width - len(b)))
    return tuple(a) > tuple(b)


def parse_sha256_manifest(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        digest, fname = parts[0].strip(), parts[1].strip().lstrip("*")
        if not _SHA256_RE.fullmatch(digest):
            continue
        base = Path(fname).name
        if base:
            result[base] = digest.lower()
    return result


def _build_headers(*, token: str | None, accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": f"MakerElegoo/{__version__}",
    }
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _handle_http_error(exc: error.HTTPError, *, repo: str, has_token: bool) -> UpdateError:
    code = exc.code
    exc.close()
    if code == 404:
        if has_token:
            return UpdateError(
                f"Nenhuma Release encontrada em '{repo}' (HTTP 404). "
                "Confirme se já existe uma Release publicada e se o token tem permissão de leitura (Contents/Releases)."
            )
        return UpdateError(
            f"Nenhuma Release pública encontrada em '{repo}' (HTTP 404). "
            "Se o repositório for privado, configure um Token GitHub somente-leitura ou aponte para um repositório público de Releases."
        )
    if code in (401, 403):
        return UpdateError(
            f"Acesso negado ou limite excedido no GitHub (HTTP {code}). "
            "Verifique seu Token GitHub ou tente novamente em instantes."
        )
    return UpdateError(f"Erro ao consultar GitHub Releases (HTTP {code}).")


def check_latest_release(
    repo: str | None = None,
    *,
    current_version: str = __version__,
    token: str | None = None,
    transport: Callable = request.urlopen,
) -> UpdateCheckResult:
    clean_repo = normalize_repo(os.getenv("MAKER_ELEGOO_UPDATE_REPO") or repo or DEFAULT_UPDATE_REPO)
    api_url = _require_https_url(
        f"https://api.github.com/repos/{clean_repo}/releases/latest",
        label="URL da API GitHub",
    )
    req = request.Request(
        api_url,
        headers=_build_headers(token=token, accept="application/vnd.github+json"),
        method="GET",
    )
    try:
        with transport(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise _handle_http_error(exc, repo=clean_repo, has_token=bool(token and token.strip())) from exc
    except (OSError, TimeoutError) as exc:
        raise UpdateError(f"Falha de rede ao consultar atualizações: {exc}") from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Resposta inválida da API de Releases: {exc}") from exc

    if not isinstance(payload, dict) or not payload.get("tag_name"):
        raise UpdateError("Resposta inesperada do GitHub Releases (tag ausente).")

    assets = payload.get("assets") or []
    installer_asset: ReleaseAsset | None = None
    checksums_asset: ReleaseAsset | None = None
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        name = str(raw_asset.get("name") or "").strip()
        if not name:
            continue
        dl_url = _require_https_url(str(raw_asset.get("browser_download_url") or ""), label=f"URL de '{name}'")
        raw_api = str(raw_asset.get("url") or "").strip()
        asset_api = _require_https_url(raw_api, label=f"API URL de '{name}'") if raw_api else ""
        asset_obj = ReleaseAsset(name=name, download_url=dl_url, size=int(raw_asset.get("size") or 0), api_url=asset_api)
        lower_name = name.lower()
        if lower_name.endswith(".exe") and ("setup" in lower_name or installer_asset is None):
            installer_asset = asset_obj
        elif "checksum" in lower_name and lower_name.endswith(".txt"):
            checksums_asset = asset_obj

    if installer_asset is None or checksums_asset is None:
        raise UpdateError(
            "A Release mais recente não contém instalador .exe e arquivo de checksum SHA-256 válidos."
        )

    tag = str(payload["tag_name"]).strip()
    version = tag[1:] if tag.lower().startswith("v") else tag
    release = ReleaseInfo(
        tag_name=tag,
        version=version,
        name=str(payload.get("name") or tag),
        notes=str(payload.get("body") or ""),
        html_url=_require_https_url(str(payload.get("html_url") or f"https://github.com/{clean_repo}/releases")),
        installer_asset=installer_asset,
        checksums_asset=checksums_asset,
    )
    return UpdateCheckResult(
        current_version=current_version,
        latest=release,
        update_available=is_newer_version(release.version, current_version),
    )


def _open_asset_stream(
    asset: ReleaseAsset,
    *,
    token: str | None,
    transport: Callable,
):
    use_api = bool(token and token.strip() and asset.api_url.startswith("https://api.github.com/"))
    url = _require_https_url(asset.api_url if use_api else asset.download_url)
    headers = _build_headers(
        token=token if use_api else None,
        accept="application/octet-stream" if use_api else "*/*",
    )
    req = request.Request(url, headers=headers, method="GET")
    return transport(req, timeout=60)


def download_and_verify_installer(
    release: ReleaseInfo,
    dest_dir: Path,
    *,
    token: str | None = None,
    transport: Callable = request.urlopen,
) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(release.installer_asset.name).name
    if not safe_name.lower().endswith(".exe") or safe_name != release.installer_asset.name:
        raise UpdateError(f"Nome de instalador inválido: {release.installer_asset.name!r}")

    try:
        with _open_asset_stream(release.checksums_asset, token=token, transport=transport) as resp:
            manifest_text = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        raise _handle_http_error(exc, repo="release asset", has_token=bool(token and token.strip())) from exc
    except (OSError, TimeoutError) as exc:
        raise UpdateError(f"Falha ao baixar manifesto de checksum SHA-256: {exc}") from exc

    checksums = parse_sha256_manifest(manifest_text)
    expected_sha = checksums.get(safe_name)
    if not expected_sha:
        raise UpdateError(
            f"SHA-256 de '{safe_name}' ausente no manifesto da Release; instalação cancelada por segurança."
        )

    final_path = dest_dir / safe_name
    part_path = dest_dir / f"{safe_name}.part"
    hasher = hashlib.sha256()
    try:
        with _open_asset_stream(release.installer_asset, token=token, transport=transport) as resp:
            with part_path.open("wb") as out:
                while chunk := resp.read(65536):
                    hasher.update(chunk)
                    out.write(chunk)
    except error.HTTPError as exc:
        part_path.unlink(missing_ok=True)
        raise _handle_http_error(exc, repo="release asset", has_token=bool(token and token.strip())) from exc
    except (OSError, TimeoutError) as exc:
        part_path.unlink(missing_ok=True)
        raise UpdateError(f"Falha ao baixar instalador: {exc}") from exc

    actual_sha = hasher.hexdigest().lower()
    if actual_sha != expected_sha:
        part_path.unlink(missing_ok=True)
        raise UpdateError(
            f"Falha na verificação de integridade SHA-256 para '{safe_name}' "
            f"(esperado {expected_sha[:12]}..., obtido {actual_sha[:12]}...)."
        )

    part_path.replace(final_path)
    return final_path


def launch_silent_installer(
    installer_path: Path,
    *,
    launcher: Callable = subprocess.Popen,
):
    target = Path(installer_path)
    if not target.is_file() or target.suffix.lower() != ".exe":
        raise UpdateError(f"Instalador inválido: {target}")
    cmd = [
        str(target),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/SP-",
    ]
    kwargs: dict = {}
    if launcher is subprocess.Popen and os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    return launcher(cmd, **kwargs)
