"""Cliente direto do Google Gemini para o Professor de Impressão."""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib import error, request

from .mapping import ConversionPlan
from .professor import Advice, PrintGoal, SAFE_PROCESS_KEYS, SAFE_FILAMENT_KEYS, validate_change
from .project import ProjectInfo


class GeminiClientError(RuntimeError):
    """Erro de comunicação ou validação com o Gemini."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        transport: Callable = request.urlopen,
    ):
        self.api_key = api_key.strip()
        self.model = model.strip()
        self._transport = transport

    def test_connection(self) -> bool:
        if not self.api_key:
            raise GeminiClientError("Chave de API do Gemini não configurada.")
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        req = request.Request(
            url,
            headers={"x-goog-api-key": self.api_key},
            method="GET",
        )
        try:
            with self._transport(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict) or "models" not in data:
                raise GeminiClientError("Resposta inesperada ao testar conexão com o Gemini.")
            return True
        except error.HTTPError as exc:
            if exc.code in (400, 401, 403):
                raise GeminiClientError(f"Chave de API rejeitada pelo Google (HTTP {exc.code}).", status_code=exc.code) from exc
            raise GeminiClientError(f"Google Gemini retornou HTTP {exc.code}", status_code=exc.code) from exc
        except (OSError, TimeoutError) as exc:
            raise GeminiClientError(f"Falha de rede ao conectar ao Gemini: {exc}") from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiClientError(f"Resposta inválida do Gemini: {exc}") from exc

    def generate_json(self, prompt: str, schema: dict | None = None) -> dict:
        if not self.api_key:
            raise GeminiClientError("Chave de API do Gemini não configurada.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", self.model):
            raise GeminiClientError(f"Nome de modelo Gemini inválido: {self.model}")

        gen_config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        }
        if schema:
            gen_config["responseSchema"] = schema

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        req = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )

        try:
            with self._transport(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except error.HTTPError as exc:
            if exc.code == 429:
                raise GeminiClientError("Limite de cota excedido (HTTP 429). Tente novamente em instantes.", status_code=429) from exc
            raise GeminiClientError(f"Google Gemini recusou a solicitação (HTTP {exc.code})", status_code=exc.code) from exc
        except (OSError, TimeoutError) as exc:
            raise GeminiClientError(f"Falha de conexão com a API do Gemini: {exc}") from exc
        except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiClientError(f"Resposta inesperada do Gemini: {exc}") from exc


def advise_gemini(
    client: GeminiClient,
    project: ProjectInfo,
    plan: ConversionPlan,
    goal: PrintGoal,
) -> list[Advice]:
    # Preparar contexto seguro restrito aos slots realmente usados quando disponíveis
    used_slots = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    target_materials = [
        str((f.get("filament_type") or ["Desconhecido"])[0])
        for idx, f in enumerate(plan.filament_settings, 1)
        if not used_slots or str(idx) in used_slots
    ] or [
        str((f.get("filament_type") or ["Desconhecido"])[0])
        for f in plan.filament_settings
    ]
    source_materials = [
        f.material for idx, f in enumerate(project.filaments, 1)
        if not used_slots or str(getattr(f, "slot", idx)) in used_slots
    ] or [f.material for f in project.filaments]

    safe_process = {
        k: str(v) for k, v in plan.process_settings.items() if k in SAFE_PROCESS_KEYS
    }
    safe_process.setdefault("brim_type", str(plan.process_settings.get("brim_type") or "auto_brim"))
    safe_filaments = [
        {
            "slot": idx,
            **{
                k: str(v[0]) if isinstance(v, list) else str(v)
                for k, v in f.items() if k in SAFE_FILAMENT_KEYS or k == "filament_type"
            },
        }
        for idx, f in enumerate(plan.filament_settings, 1)
        if not used_slots or str(idx) in used_slots
    ] or [
        {
            "slot": idx,
            **{
                k: str(v[0]) if isinstance(v, list) else str(v)
                for k, v in f.items() if k in SAFE_FILAMENT_KEYS or k == "filament_type"
            },
        }
        for idx, f in enumerate(plan.filament_settings, 1)
    ]

    min_h = plan.machine_settings.get("min_layer_height", ["0.08"])
    max_h = plan.machine_settings.get("max_layer_height", ["0.28"])
    max_plate_colors = max(
        (
            len({s for s in (getattr(p, "used_filament_slots", ()) or getattr(p, "filament_slots", ())) if s and s != "0"})
            for p in getattr(project, "plates", ())
        ),
        default=1,
    )
    context_payload = {
        "printer": plan.machine_settings.get("printer_model", "ELEGOO"),
        "nozzle_mm": str(plan.machine_settings.get("nozzle_diameter", ["0.4"])[0]),
        "min_layer_height_mm": str(min_h[0] if isinstance(min_h, list) else min_h),
        "max_layer_height_mm": str(max_h[0] if isinstance(max_h, list) else max_h),
        "source_materials": source_materials,
        "target_materials": target_materials,
        "used_filament_slots": list(getattr(project, "used_filament_slots", ()) or ()),
        "chamber": "passiva fechada (support_chamber_temp_control = 0; sem aquecimento ativo controlado por software)",
        "max_colors_on_single_plate": int(max_plate_colors),
        "advanced_features": list(getattr(project, "advanced_features", ()) or ()),
        "has_object_overrides": bool(getattr(project, "object_overrides", ())),
        "current_process": safe_process,
        "current_filaments": safe_filaments,
        "goal_purpose": goal.purpose,
        "goal_priority": goal.priority,
        "goal_load_type": getattr(goal, "load_type", "nao_sei"),
        "goal_criticality": getattr(goal, "criticality", "nao_sei"),
        "goal_fit_clearance": getattr(goal, "fit_clearance", "nao_sei"),
        "goal_heat_exposure": getattr(goal, "heat_exposure", "nao_sei"),
        "goal_physical_material": getattr(goal, "physical_material", "nao_sei"),
    }
    geom = getattr(project, "geometry_summary", None)
    if geom is not None and getattr(geom, "triangle_count", 0) > 0:
        context_payload["geometry"] = {
            "triangle_count": int(geom.triangle_count),
            "object_count": int(geom.object_count),
            "size_mm": [round(float(geom.size_x), 1), round(float(geom.size_y), 1), round(float(geom.size_z), 1)],
            "contact_mm2": round(float(geom.contact_mm2), 1),
            "overhang_mm2": round(float(geom.overhang_mm2), 1),
            "has_slender_parts": bool(geom.has_slender_parts),
        }

    prompt = (
        "Você é um Professor e Engenheiro Especialista em Manufatura Aditiva e Impressão 3D FDM. "
        "Um usuário baixou um projeto 3MF (originalmente configurado para impressora Bambu) e está convertendo "
        "para uma impressora ELEGOO Centauri Carbon 2.\n\n"
        "Analise o contexto a seguir e sugira ajustes didáticos necessários como hipóteses de partida para que o usuário "
        "possa testar e validar no fatiamento e na peça real.\n"
        "Regras estritas:\n"
        "1. Para 'process', use APENAS chaves existentes em 'current_process' e respeite min_layer_height_mm e max_layer_height_mm (para brim_type use auto_brim, outer_only ou no_brim).\n"
        "2. Para 'filament', informe o 'slot' (1-based) e use chaves existentes em current_filaments (como fan_max_speed, fan_min_speed, overhang_fan_speed, during_print_exhaust_fan_speed) respeitando fan_min_speed <= fan_max_speed.\n"
        "3. Nunca prometa nem afirme resistência mecânica garantida, estabilidade dimensional ou solda perfeita sem ensaio físico; informe 'expected_effect' e 'what_to_check' em linguagem simples.\n"
        "4. Diferencie origem PLA vs PETG vs mista; nunca rotule PETG como PLA.\n"
        "5. A ELEGOO Centauri Carbon 2 possui câmara passiva (support_chamber_temp_control = 0), sem aquecimento ativo controlado por software.\n"
        "6. Em 'default_on', use true para recomendações padrão compatíveis e false para alertas de odor/exaustão, câmara ou itens que dependam de teste físico.\n\n"
        f"Contexto do Projeto:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}\n\n"
        "Responda SOMENTE um JSON no formato:\n"
        "{\n"
        '  "advices": [\n'
        '    {"scope": "process|filament|alert", "slot": 1, "key": "string", "proposed": "string", "title": "string", "why": "string", "expected_effect": "string", "what_to_check": "string", "requires_physical_test": false, "default_on": true}\n'
        "  ]\n"
        "}"
    )

    result = client.generate_json(prompt)
    raw_advices = result.get("advices", [])
    if not isinstance(raw_advices, list):
        return []

    verified: list[Advice] = []
    for item in raw_advices:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope", ""))
        raw_slot = item.get("slot")
        slot: int | None
        if scope == "process" or scope == "alert":
            slot = None
        elif raw_slot is None or raw_slot == "" or isinstance(raw_slot, bool):
            continue
        else:
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                continue
        key = str(item.get("key", ""))
        proposed = str(item.get("proposed", ""))
        title = str(item.get("title", ""))[:80]
        why = str(item.get("why", ""))[:400]
        expected_effect = str(item.get("expected_effect", ""))[:200]
        what_to_check = str(item.get("what_to_check", ""))[:200]
        requires_physical_test = bool(item.get("requires_physical_test", False))
        default_on = bool(item.get("default_on", False))

        if scope == "alert":
            verified.append(Advice(
                "alert", None, "", "", "", title, why, default_on,
                expected_effect=expected_effect,
                what_to_check=what_to_check,
                evidence_class="depende_teste_fisico" if requires_physical_test else "estimado_regra_ia",
                requires_physical_test=requires_physical_test,
                confidence="media",
            ))
            continue

        if scope in {"process", "filament"}:
            if validate_change(scope, key, proposed, plan, slot=slot):
                if scope == "process":
                    current_val = str(plan.process_settings.get(key, ""))
                else:
                    raw_cur = plan.filament_settings[slot - 1].get(key, "")
                    current_val = str(raw_cur[0] if isinstance(raw_cur, list) and raw_cur else raw_cur)
                verified.append(
                    Advice(
                        scope, slot, key, current_val, proposed, title, why, default_on,
                        expected_effect=expected_effect,
                        what_to_check=what_to_check,
                        evidence_class="estimado_regra_ia",
                        requires_physical_test=requires_physical_test,
                        confidence="media",
                    )
                )

    return verified
