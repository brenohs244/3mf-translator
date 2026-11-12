"""Execução opcional e limitada do Codex CLI para resumos textuais."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class CodexError(RuntimeError):
    pass


SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string"}, "source_key": {"type": "string"},
            "target_key": {"type": "string"}, "value": {"type": "string"},
            "reason": {"type": "string"}, "confidence": {"type": "string"}},
            "required": ["kind", "source_key", "target_key", "value", "reason", "confidence"],
            "additionalProperties": False}},
        "orientation_id": {"type": "string"},
        "observations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["suggestions", "orientation_id", "observations"],
    "additionalProperties": False,
}


def run_codex(summary: str, *, runner=subprocess.run, timeout: int = 120) -> dict:
    """Send only an approved, caller-constructed summary to Codex."""
    executable = shutil.which("codex")
    if not executable:
        raise CodexError("Codex CLI não encontrado neste computador. Instale e autentique o Codex.")
    if len(summary) > 16000:
        raise CodexError("Resumo excede o limite permitido")
    instruction = ("Analise somente os dados JSON fornecidos. Não use ferramentas nem procure arquivos. "
                   "Responda no esquema solicitado. Sugira apenas chaves de processo presentes no resumo; "
                   "para orientação use apenas um identificador de candidata validada ou texto vazio. "
                   "Não invente medidas de acabamento, suporte ou resistência.\n" + summary)
    with tempfile.TemporaryDirectory(prefix="maker-elegoo-codex-") as folder:
        schema = Path(folder) / "schema.json"
        schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        command = [executable, "exec", "--ephemeral", "--ignore-user-config",
                   "--skip-git-repo-check",
                   "--sandbox", "read-only", "--output-schema", "schema.json", "-"]
        try:
            result = runner(command, input=instruction, text=True, encoding="utf-8",
                            cwd=folder, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise CodexError("Codex excedeu o tempo de análise") from exc
        except OSError as exc:
            raise CodexError(f"Não foi possível iniciar o Codex: {exc}") from exc
    if result.returncode != 0:
        raise CodexError("Codex não concluiu a análise. Confira a autenticação e a conexão.")
    if len(result.stdout) > 100000:
        raise CodexError("Resposta do Codex excede o limite permitido")
    try:
        data = json.loads(result.stdout)
        if (not isinstance(data, dict) or not isinstance(data.get("suggestions"), list)
                or not isinstance(data.get("orientation_id"), str)
                or not isinstance(data.get("observations"), list)):
            raise ValueError("formato incorreto")
    except (ValueError, TypeError) as exc:
        raise CodexError("Resposta do Codex não é JSON válido no formato esperado") from exc
    return data
