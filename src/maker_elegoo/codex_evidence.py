"""Allowlisted local evidence and strict Codex recommendation gates."""
from __future__ import annotations

import math
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from .ai import Suggestion, validate_suggestion
from .converter import convert_project
from .orientation import write_oriented_copy
from .project import inspect_project

SUPPORT_KEYS = frozenset({'enable_support', 'support_on_build_plate_only'})
PROCESS_KEYS = frozenset({'wall_loops', 'top_shell_layers', 'bottom_shell_layers',
                          'sparse_infill_density', 'brim_width', 'enable_support',
                          'support_on_build_plate_only'})
_SAFE_VALUE = re.compile(r'^(?:[0-9]{1,3}(?:\.[0-9]{1,3})?%?|[01])$')
_MATERIALS = {'PLA', 'PETG', 'ABS', 'ASA', 'TPU', 'PA', 'PC'}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(value, 3)


def _settings(settings):
    return {key: str(value) for key, value in settings.items()
            if key in PROCESS_KEYS and isinstance(value, (str, int, float))
            and _SAFE_VALUE.fullmatch(str(value))}


def _slice(result):
    validation = getattr(result, 'validation', None)
    return {'success': bool(getattr(result, 'success', False)),
            'mesh_unchanged': bool(getattr(getattr(result, 'geometry', None), 'unchanged', False)),
            'estimated_seconds': _number(getattr(validation, 'estimated_seconds', None)),
            'filament_grams': _number(getattr(validation, 'filament_grams', None)),
            'warning_count': len(getattr(validation, 'warnings', ()) or ())}


def build_codex_evidence(project, plan, result, orientation=None) -> dict:
    """Return only text and measurements safe for explicit review and consent."""
    nozzle = plan.machine_settings.get('nozzle_diameter', [])
    nozzle = nozzle[0] if isinstance(nozzle, (list, tuple)) and nozzle else nozzle
    source_materials = sorted({item.material.upper() for item in project.filaments
                               if item.material.upper() in _MATERIALS})
    target_filaments = getattr(plan, 'filament_settings', None) or ()
    target_materials = sorted({
        str((cfg.get('filament_type') or [''])[0] if isinstance(cfg.get('filament_type'), (list, tuple))
            else cfg.get('filament_type', '')).upper()
        for cfg in target_filaments
    } & _MATERIALS)
    materials = target_materials or source_materials
    evidence = {'printer_model': 'Elegoo Centauri Carbon 2',
                'nozzle_mm': str(nozzle) if _SAFE_VALUE.fullmatch(str(nozzle)) else None,
                'materials': materials,
                'source_materials': source_materials,
                'process_options': _settings(plan.process_settings),
                'unmapped_keys': sorted(key for key in plan.unmapped
                                        if isinstance(key, str) and re.fullmatch(r'[a-z][a-z0-9_]{1,50}', key)
                                        and not any(word in key for word in ('path', 'file', 'name', 'token', 'secret', 'password', 'gcode', 'script')))[:30],
                'slicing': _slice(result), 'orientation': None}
    if orientation is not None:
        evaluations = (orientation.current, *orientation.alternatives)
        evidence['orientation'] = {'front': orientation.front if orientation.front in ('+X', '-X', '+Y', '-Y') else None,
                                   'candidates': [{'id': item.candidate.label,
                                                   'dimensions_mm': [_number(item.candidate.bounds[i + 1] - item.candidate.bounds[i]) for i in (0, 2, 4)],
                                                   'contact_mm2': _number(item.candidate.contact_mm2),
                                                   'overhang_mm2': _number(item.candidate.overhang_mm2),
                                                   'front_overhang_mm2': _number(item.candidate.front_overhang_mm2),
                                                   'valid': bool(item.candidate.valid),
                                                   'slicing': _slice(item.result)}
                                                  for item in evaluations
                                                  if re.fullmatch(r'[A-Za-z0-9 À-ÿ_+°.\\-]{1,50}', item.candidate.label)]}
    return evidence


def validate_codex_recommendations(raw: dict, plan, orientation=None):
    """Return accepted process suggestions and one locally sliced orientation candidate."""
    if not isinstance(raw, dict):
        return (), None
    accepted = []
    for item in raw.get('suggestions', [])[:30] if isinstance(raw.get('suggestions'), list) else []:
        if not isinstance(item, dict):
            continue
        suggestion = Suggestion(*(str(item.get(key, '')) for key in
                                  ('kind', 'source_key', 'target_key', 'value', 'reason', 'confidence')))
        if (suggestion.target_key not in PROCESS_KEYS or suggestion.confidence not in ('low', 'medium', 'high')
                or len(suggestion.reason) > 300 or not validate_suggestion(suggestion, plan.process_settings)):
            continue
        if suggestion.kind == 'mapping' and suggestion.source_key not in plan.unmapped:
            continue
        if suggestion.kind == 'feature' and suggestion.source_key:
            continue
        accepted.append(suggestion)
    candidate = None
    chosen = raw.get('orientation_id')
    if isinstance(chosen, str) and orientation is not None:
        for evaluation in (orientation.current, *orientation.alternatives):
            if (evaluation.candidate.label == chosen
                    and evaluation.candidate == orientation.recommended
                    and not evaluation.candidate.is_current
                    and evaluation.candidate.valid
                    and evaluation.result.success and evaluation.result.geometry
                    and evaluation.result.geometry.unchanged):
                candidate = evaluation.candidate
                break
    return tuple(accepted), candidate


def verify_process_recommendation(project, plan, result, suggestion: Suggestion, slicer, candidate=None) -> dict:
    """Reslice one process change locally; return compared metrics and applicability."""
    if suggestion.target_key not in PROCESS_KEYS or not validate_suggestion(suggestion, plan.process_settings):
        return {'verified': False, 'reason': 'Ajuste de processo inseguro'}
    if candidate is not None and (not candidate.valid or candidate.is_current):
        return {'verified': False, 'reason': 'Orientação não validada'}
    updated = replace(plan, process_settings={**plan.process_settings, suggestion.target_key: suggestion.value})
    with TemporaryDirectory(prefix='maker-elegoo-codex-verify-') as scratch:
        folder = Path(scratch)
        source = project
        if candidate is not None:
            source = inspect_project(write_oriented_copy(project.path, candidate, folder / 'oriented.3mf'))
        compared = convert_project(source, updated, folder / 'compared.3mf', slicer)
    baseline = _slice(result)
    proposal = _slice(compared)
    return {'verified': bool(baseline['success'] and baseline['mesh_unchanged']
                             and proposal['success'] and proposal['mesh_unchanged']
                             and proposal['warning_count'] <= baseline['warning_count']),
            'baseline': baseline, 'proposal': proposal}


def verify_support_recommendation(project, plan, result, suggestion: Suggestion, slicer, candidate=None) -> dict:
    if suggestion.target_key not in SUPPORT_KEYS:
        return {'verified': False, 'reason': 'Ajuste de suporte inseguro'}
    return verify_process_recommendation(project, plan, result, suggestion, slicer, candidate)

