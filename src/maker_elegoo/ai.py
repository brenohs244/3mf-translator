"""Sugestões opcionais do Gemini, sempre restritas a ajustes revisáveis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib import error, request


class AIError(RuntimeError):
    """Falha de comunicação ou resposta inválida da IA."""


@dataclass(frozen=True)
class Suggestion:
    kind: str
    source_key: str
    target_key: str
    value: str
    reason: str
    confidence: str


BOOLEAN_KEYS = {"enable_support", "support_on_build_plate_only", "detect_thin_wall",
                "adaptive_layer_height", "extra_perimeters_on_overhangs", "only_one_wall_top",
                "reduce_infill_retraction", "staggered_inner_seams"}
INTEGER_KEYS = {"wall_loops": (1, 8), "top_shell_layers": (0, 12),
                "bottom_shell_layers": (0, 12)}
FLOAT_KEYS = {"brim_width": (0, 20)}
PERCENT_KEYS = {"sparse_infill_density": (0, 80)}
SAFE_KEYS = BOOLEAN_KEYS | INTEGER_KEYS.keys() | FLOAT_KEYS.keys() | PERCENT_KEYS.keys()


def validate_suggestion(suggestion: Suggestion, schema: dict) -> bool:
    if suggestion.kind not in {"mapping", "feature"} or suggestion.target_key not in schema:
        return False
    if suggestion.target_key not in SAFE_KEYS or len(suggestion.value) > 30:
        return False
    key, value = suggestion.target_key, suggestion.value
    if key in BOOLEAN_KEYS:
        return value in {"0", "1"}
    if key in INTEGER_KEYS:
        low, high = INTEGER_KEYS[key]
        return value.isdigit() and low <= int(value) <= high
    try:
        if key in PERCENT_KEYS and value.endswith("%"):
            number = float(value[:-1]); low, high = PERCENT_KEYS[key]
            return low <= number <= high
        if key in FLOAT_KEYS:
            number = float(value); low, high = FLOAT_KEYS[key]
            return low <= number <= high
    except ValueError:
        return False
    return False


def apply_suggestions(process_settings: dict, approved: list[Suggestion]) -> dict:
    updated = dict(process_settings)
    for suggestion in approved:
        if not validate_suggestion(suggestion, process_settings):
            raise AIError(f"Sugestão insegura ou incompatível: {suggestion.target_key}")
        updated[suggestion.target_key] = suggestion.value
    return updated


def build_manual_prompt(unmapped: dict, process_settings: dict, context: dict,
                        priority: str, purpose: str, notes: str) -> str:
    """Create a text-only prompt that the user may copy into any AI chat."""
    source, target, safe_context = _safe_inputs(unmapped, process_settings, context)
    payload = {"source_unmapped": source, "elegoo_safe_process_options": target,
               "context": safe_context, "priority": priority[:80],
               "purpose": purpose[:120], "notes": notes[:500]}
    return ("Analise este projeto 3MF para a ELEGOO Centauri Carbon 2. "
            "Sugira ajustes para o objetivo informado. Responda APENAS JSON no formato "
            '{"suggestions":[{"kind":"mapping|feature","source_key":"",'
            '"target_key":"","value":"","reason":"","confidence":"low|medium|high"}]}. '
            "Use apenas chaves e valores compatíveis em elegoo_safe_process_options. "
            "Não sugira G-code, temperatura, firmware ou limites da máquina. "
            "Para kind=feature, deixe source_key vazio. Se não houver ajuste seguro, retorne lista vazia.\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def parse_manual_response(raw_text: str, unmapped: dict, process_settings: dict) -> list[Suggestion]:
    """Keep only known, bounded process changes from a pasted AI response."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"Resposta não é JSON válido: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("suggestions"), list):
        raise AIError("Resposta deve conter uma lista 'suggestions'")
    accepted = []
    for item in data["suggestions"][:30]:
        if not isinstance(item, dict):
            continue
        suggestion = Suggestion(*(str(item.get(key, "")) for key in
                                  ("kind", "source_key", "target_key", "value", "reason", "confidence")))
        if suggestion.kind == "mapping" and suggestion.source_key not in unmapped:
            continue
        if suggestion.kind == "feature" and suggestion.source_key:
            continue
        if suggestion.confidence not in {"low", "medium", "high"}:
            continue
        if validate_suggestion(suggestion, process_settings):
            accepted.append(suggestion)
    return accepted


def _safe_inputs(unmapped: dict, elegoo_keys: dict, context: dict) -> tuple[dict, dict, dict]:
    forbidden = ("gcode", "script", "password", "token", "key", "path", "file")
    source = {str(key): str(value) for key, value in sorted(unmapped.items())
              if not any(word in str(key).lower() for word in forbidden)
              and isinstance(value, (str, int, float, bool)) and len(str(value)) <= 200}
    source = dict(list(source.items())[:30])
    target = {key: str(value) for key, value in elegoo_keys.items() if key in SAFE_KEYS}
    safe_context = {key: context[key] for key in ("printer_model", "filament_type", "nozzle_diameter")
                    if key in context and len(str(context[key])) <= 200}
    return source, target, safe_context


def suggest_equivalences(unmapped: dict, elegoo_keys: dict, context: dict, api_key: str,
                         *, model: str = "gemini-3.5-flash-lite", transport=request.urlopen) -> list[Suggestion]:
    if not api_key.strip():
        raise AIError("Informe uma chave de API Gemini")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise AIError("Nome de modelo Gemini inválido")
    source, target, safe_context = _safe_inputs(unmapped, elegoo_keys, context)
    prompt = ("Você analisa parâmetros de fatiadores 3D. Responda SOMENTE JSON com objeto "
              "{\"suggestions\":[{\"kind\":\"mapping|feature\",\"source_key\":\"\","
              "\"target_key\":\"\",\"value\":\"\",\"reason\":\"\",\"confidence\":\"low|medium|high\"}]}. "
              "Use apenas chaves ELEGOO fornecidas. 'mapping' liga campo de origem a um destino; "
              "'feature' sugere recurso extra do ELEGOO. Nunca sugira G-code, comandos de firmware, "
              "temperaturas, limites de máquina ou parâmetros ausentes. Se não houver equivalência, retorne lista vazia.\n"
              + json.dumps({"source_unmapped": source, "elegoo_safe_process_options": target,
                            "context": safe_context}, ensure_ascii=False))
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req = request.Request(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                          method="POST")
    try:
        with transport(req, timeout=30) as response:
            data = json.loads(response.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        decoded = json.loads(text)
        raw_suggestions = decoded.get("suggestions", [])
        if not isinstance(raw_suggestions, list):
            raise ValueError("suggestions não é uma lista")
    except error.HTTPError as exc:
        if exc.code == 429:
            raise AIError("Cota do Gemini excedida; tente mais tarde ou use outro modelo") from exc
        raise AIError(f"Gemini recusou a solicitação (HTTP {exc.code})") from exc
    except (OSError, TimeoutError) as exc:
        raise AIError(f"Falha de rede ao consultar o Gemini: {exc}") from exc
    except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AIError(f"Resposta inválida do Gemini: {exc}") from exc
    suggestions = []
    for raw in raw_suggestions[:20]:
        if not isinstance(raw, dict):
            continue
        suggestion = Suggestion(str(raw.get("kind", "")), str(raw.get("source_key", "")),
                                str(raw.get("target_key", "")), str(raw.get("value", "")),
                                str(raw.get("reason", ""))[:300], str(raw.get("confidence", "low")))
        if suggestion.kind == "mapping" and suggestion.source_key not in source:
            continue
        if suggestion.kind == "feature" and suggestion.source_key:
            continue
        if suggestion.confidence not in {"low", "medium", "high"}:
            continue
        if validate_suggestion(suggestion, target):
            suggestions.append(suggestion)
    return suggestions
