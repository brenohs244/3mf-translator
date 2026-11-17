"""Identidade de material por metadados resolvidos e seleção segura por slot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .profiles import Profile, ProfileError, SlicerInstall, resolve_profile
from .project import ProjectInfo

_POLYMERS_ORDERED = ("PETG", "PET", "PLA", "TPU", "ASA", "ABS", "PC", "PA")
_KNOWN_VARIANTS = frozenset({
    "",
    "CF",
    "GF",
    "HT",
    "HT-CF",
    "6-CF",
    "12-CF",
    "SILK",
    "MATTE",
    "WOOD",
    "GLOW",
    "MARBLE",
    "SPARKLE",
    "TRANSLUCENT",
    "RAPID",
    "HF",
    "HS",
    "PRO",
    "FR",
    "BASIC",
    "+",
    "PLUS",
    "95A",
    "85A",
    "90A",
})


@dataclass(frozen=True)
class MaterialIdentity:
    polymer: str
    variant: str = ""

    @property
    def label(self) -> str:
        if not self.variant:
            return self.polymer
        if self.variant in {"+", "95A", "85A", "90A", "SILK", "MATTE", "WOOD", "GLOW", "MARBLE", "SPARKLE", "TRANSLUCENT", "PRO", "HF", "HS", "RAPID", "BASIC"}:
            return f"{self.polymer}{self.variant}" if self.variant == "+" else f"{self.polymer} {self.variant}"
        return f"{self.polymer}-{self.variant}"


@dataclass(frozen=True)
class MaterialSelection:
    profile: Profile | None
    reason: str
    requires_choice: bool


@dataclass(frozen=True)
class SlotMaterialTarget:
    slot: int
    identity: MaterialIdentity
    profile: Profile | None
    confirmed: bool
    planned_only: bool = False


def _first_str(val: object) -> str:
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return "" if val is None else str(val).strip()


def _detect_polymer(text: str) -> str:
    upper = (text or "").strip().upper()
    if not upper or upper in {"NAO_SEI", "NÃO SEI", "NÃO SEI INFORMAR", "DESCONHECIDO", "UNKNOWN"}:
        return "DESCONHECIDO"
    if "NYLON" in upper:
        return "PA"
    # PC antes de ABS para classificar PC-ABS como PC
    for polymer in ("PETG", "PET", "PLA", "TPU", "PC", "PA", "ASA", "ABS"):
        if polymer == "PA":
            if re.search(r"(?<![A-Z])PA(?:HT|6|12)?(?![A-Z])", upper):
                return "PA"
        elif polymer == "PETG":
            if re.search(r"(?<![A-Z])PET[\s-]?G(?![A-Z])", upper):
                return "PETG"
        elif re.search(rf"(?<![A-Z]){polymer}(?![A-Z])", upper):
            return polymer
    return "DESCONHECIDO"


def _extract_variant_tokens(text: str, polymer: str, *, allow_unknown_suffix: bool = False) -> str:
    upper = (text or "").strip().upper()
    if not upper or polymer == "DESCONHECIDO":
        return ""
    # Remove prefixo de fabricante e sufixo @ECC2/@Elegoo para evitar falsos tokens
    cleaned = re.sub(r"@[^\s]+", " ", upper)
    cleaned = re.sub(r"\b(?:ELEGOO|GENERIC|BAMBU|BL|CENTAURI|CARBON|2|NOZZLE|0\.[2468])\b", " ", cleaned)

    tokens: list[str] = []
    # Sufixos compostos específicos de poliamida / polímeros de engenharia
    if polymer == "PA":
        if re.search(r"\bPAHT[\s-]?CF\b", cleaned):
            return "HT-CF"
        if re.search(r"\bPA6[\s-]?CF\b", cleaned):
            return "6-CF"
        if re.search(r"\bPA12[\s-]?CF\b", cleaned):
            return "12-CF"

    known_checks = (
        ("CF", r"(?:^|[\s-])CF\b"),
        ("GF", r"(?:^|[\s-])GF\b"),
        ("SILK", r"\bSILK\b"),
        ("MATTE", r"\bMATTE\b"),
        ("WOOD", r"\bWOOD\b"),
        ("GLOW", r"\bGLOW\b"),
        ("MARBLE", r"\bMARBLE\b"),
        ("SPARKLE", r"\bSPARKLE\b"),
        ("TRANSLUCENT", r"\bTRANSLUCENT\d*\b"),
        ("FR", r"(?:^|[\s-])FR\b"),
        ("HT", r"(?:^|[\s-])HT\b"),
        ("95A", r"\b95A\b"),
        ("85A", r"\b85A\b"),
        ("90A", r"\b90A\b"),
        ("RAPID", r"\bRAPID\b"),
        ("HF", r"\bHF\b"),
        ("HS", r"\bHS\b"),
        ("PRO", r"\bPRO\b"),
        ("BASIC", r"\bBASIC\b"),
    )
    for tag, pattern in known_checks:
        if re.search(pattern, cleaned):
            tokens.append(tag)
    if "+" in cleaned:
        tokens.append("+")
    if tokens:
        return "-".join(tokens)

    if allow_unknown_suffix:
        # Ex.: "ABS-ESD" ou "PLA-XYZ"
        match = re.search(rf"\b{re.escape(polymer)}[\s-]+([A-Z0-9]+)\b", cleaned)
        if match:
            candidate = match.group(1)
            if candidate not in {"@ECC2", "ECC2", "3MF", "FILA"}:
                return candidate
    return ""


def parse_material_identity(raw: str) -> MaterialIdentity:
    text = (raw or "").strip()
    polymer = _detect_polymer(text)
    if polymer == "DESCONHECIDO":
        return MaterialIdentity("DESCONHECIDO", "")
    variant = _extract_variant_tokens(text, polymer, allow_unknown_suffix=True)
    return MaterialIdentity(polymer, variant)


def is_known_variant(variant: str) -> bool:
    norm = (variant or "").strip().upper()
    if norm in _KNOWN_VARIANTS:
        return True
    parts = [p for p in norm.split("-") if p]
    return bool(parts) and all(p in _KNOWN_VARIANTS for p in parts)


def extract_profile_material_identity(profile: Profile, install: SlicerInstall) -> MaterialIdentity:
    """Extrai MaterialIdentity resolvendo herança via `resolve_profile` (nunca apenas substring)."""
    try:
        resolved = resolve_profile(profile, install)
    except ProfileError:
        resolved = dict(profile.data)

    raw_type = _first_str(resolved.get("filament_type"))
    if raw_type:
        polymer = _detect_polymer(raw_type)
        # Primeiro procura modificador no próprio filament_type (ex.: "ABS-CF")
        variant = _extract_variant_tokens(raw_type, polymer, allow_unknown_suffix=True)
        # Perfis ECC2 reais às vezes declaram filament_type=["ASA"] para "Elegoo ASA-CF @ECC2"
        if not variant:
            resolved_name = _first_str(resolved.get("name")) or profile.name
            variant = _extract_variant_tokens(resolved_name, polymer, allow_unknown_suffix=False)
        if not variant:
            try:
                hrc = int(float(_first_str(resolved.get("required_nozzle_HRC")) or "0"))
                if hrc >= 35:
                    variant = "CF"
            except ValueError:
                pass
        return MaterialIdentity(polymer, variant)

    # Fallback apenas se o perfil não declarar filament_type em lugar algum da herança
    fallback_name = _first_str(resolved.get("name")) or profile.name
    return parse_material_identity(fallback_name)


def _profile_tier(profile: Profile, install: SlicerInstall) -> str:
    if "user" in profile.path.parts:
        return "user"
    try:
        resolved = resolve_profile(profile, install)
    except ProfileError:
        resolved = dict(profile.data)
    vendor = _first_str(resolved.get("filament_vendor")).upper()
    upper_name = profile.name.upper()
    if vendor == "GENERIC" or upper_name.startswith("GENERIC "):
        return "generic"
    return "vendor"


def select_material_profile(
    identity: MaterialIdentity,
    profiles: Iterable[Profile],
    install: SlicerInstall,
    *,
    preferred_profile_name: str | None = None,
) -> MaterialSelection:
    """Seleciona perfil por metadados resolvidos, bloqueando variantes erradas e empates ambíguos."""
    poly = (identity.polymer or "").strip().upper()
    var = (identity.variant or "").strip().upper()
    norm_ident = MaterialIdentity(poly, var)

    if poly in {"", "DESCONHECIDO", "NAO_SEI"}:
        return MaterialSelection(None, "Material alvo não identificado: escolha o filamento.", requires_choice=True)

    profile_list = list(profiles)
    identities = [(p, extract_profile_material_identity(p, install)) for p in profile_list]

    exact = [p for p, p_ident in identities if p_ident.polymer == poly and p_ident.variant == var]
    same_poly = [(p, p_ident) for p, p_ident in identities if p_ident.polymer == poly]

    if preferred_profile_name:
        pref_clean = preferred_profile_name.strip()
        pref_match = next((p for p in exact if p.name == pref_clean), None)
        if pref_match is not None:
            return MaterialSelection(
                pref_match,
                f"Último perfil utilizado para {norm_ident.label}: {pref_match.name}.",
                requires_choice=False,
            )

    if var and not is_known_variant(var) and not exact:
        return MaterialSelection(
            None,
            f"Variante '{var}' de {poly} é desconhecida: selecione manualmente o perfil de filamento correspondente.",
            requires_choice=True,
        )

    if not exact:
        if same_poly:
            found_labels = ", ".join(dict.fromkeys(p.name for p, _ in same_poly[:3]))
            return MaterialSelection(
                None,
                f"Nenhum perfil compatível para {norm_ident.label} (encontrados apenas {found_labels}; "
                "variantes ou compostos não são selecionados automaticamente).",
                requires_choice=False,
            )
        return MaterialSelection(
            None,
            f"Nenhum perfil ELEGOO compatível encontrado para {norm_ident.label}.",
            requires_choice=False,
        )

    if len(exact) == 1:
        winner = exact[0]
        return MaterialSelection(winner, f"Correspondência por metadados: {winner.name} ({norm_ident.label}).", requires_choice=False)

    # Múltiplos candidatos exatos para o mesmo (polímero, variante):
    tiers = [(p, _profile_tier(p, install)) for p in exact]
    user_profiles = [p for p, t in tiers if t == "user"]
    vendor_profiles = [p for p, t in tiers if t == "vendor"]

    # Se há perfis do usuário competindo entre si ou com presets do sistema, nunca escolhe silenciosamente
    if user_profiles:
        names = ", ".join(p.name for p in exact[:4])
        return MaterialSelection(
            None,
            f"Há {len(exact)} perfis compatíveis para {norm_ident.label} ({names}): escolha explicitamente qual corresponde ao carretel.",
            requires_choice=True,
        )

    # Um único preset oficial do fabricante vence apenas fallbacks Generic; dois vendor ou dois Generic empatam
    if len(vendor_profiles) == 1:
        winner = vendor_profiles[0]
        return MaterialSelection(winner, f"Preset oficial selecionado por metadados: {winner.name} ({norm_ident.label}).", requires_choice=False)

    names = ", ".join(p.name for p in exact[:4])
    return MaterialSelection(
        None,
        f"Há {len(exact)} perfis equivalentes para {norm_ident.label} ({names}): escolha explicitamente qual usar.",
        requires_choice=True,
    )


def active_filament_slots(project: ProjectInfo | None) -> tuple[int, ...]:
    if project is None or not getattr(project, "filaments", ()):
        return ()
    used_raw = {
        str(s) for s in (getattr(project, "used_filament_slots", ()) or ())
        if s and str(s) != "0"
    }
    if not used_raw:
        return tuple(f.slot for f in project.filaments)
    slots = tuple(f.slot for f in project.filaments if str(f.slot) in used_raw)
    return slots or tuple(f.slot for f in project.filaments)


def validate_slot_material_plan(
    project: ProjectInfo,
    slot_targets: Iterable[SlotMaterialTarget],
    install: SlicerInstall,
) -> tuple[bool, list[str]]:
    """Valida todos os slots usados antes de construir/converter o plano. Ignora slots não usados."""
    active = set(active_filament_slots(project))
    by_slot = {target.slot: target for target in slot_targets}
    errors: list[str] = []

    for slot in sorted(active):
        target = by_slot.get(slot)
        if target is None:
            errors.append(f"Slot {slot}: alvo de material não definido.")
            continue
        if target.identity.polymer in {"", "DESCONHECIDO", "NAO_SEI"}:
            errors.append(f"Slot {slot}: informe o material alvo (não deixe em 'Não sei informar').")
            continue
        if target.identity.variant and not is_known_variant(target.identity.variant):
            # Se o usuário escolheu manualmente um perfil que tem exatamente essa variante, OK; caso contrário bloqueia
            if target.profile is None:
                errors.append(f"Slot {slot}: variante '{target.identity.variant}' desconhecida sem perfil escolhido.")
                continue
        if target.profile is None:
            errors.append(f"Slot {slot}: selecione um perfil ELEGOO compatível para {target.identity.label}.")
            continue
        prof_ident = extract_profile_material_identity(target.profile, install)
        if prof_ident.polymer != target.identity.polymer or (
            target.identity.variant != prof_ident.variant
        ):
            errors.append(
                f"Slot {slot}: divergência entre material informado ({target.identity.label}) "
                f"e perfil selecionado ({target.profile.name} → {prof_ident.label})."
            )
            continue
        if not target.confirmed:
            action = "planejado" if target.planned_only else "carregado"
            errors.append(f"Slot {slot}: confirme o material {action} ({target.identity.label} / {target.profile.name}).")

    return (len(errors) == 0), errors
