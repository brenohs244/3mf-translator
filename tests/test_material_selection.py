import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.material_selection import (
    MaterialIdentity,
    MaterialSelection,
    SlotMaterialTarget,
    extract_profile_material_identity,
    parse_material_identity,
    select_material_profile,
    validate_slot_material_plan,
)
from maker_elegoo.profiles import SlicerInstall, discover_slicer, list_profiles
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


def _write_profile(root: Path, rel: str, payload: dict) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class MaterialSelectionTests(unittest.TestCase):
    def _base_env(self, root: Path, filament_specs: list[tuple[str, dict]]) -> tuple[SlicerInstall, list]:
        exe = root / "elegoo-slicer.exe"
        exe.touch()
        base = "Elegoo Centauri Carbon 2 0.4 nozzle"
        _write_profile(
            root,
            "system/Elegoo/machine/ECC2/base.json",
            {
                "type": "machine",
                "name": base,
                "printer_model": "Elegoo Centauri Carbon 2",
                "nozzle_diameter": ["0.4"],
            },
        )
        for rel, payload in filament_specs:
            data = {"type": "filament", "compatible_printers": [base], **payload}
            _write_profile(root, rel, data)
        install = discover_slicer(executable=exe, data_dir=root)
        machine = list_profiles(install, "machine", "0.4")[0]
        fils = list_profiles(install, "filament", "0.4", machine=machine)
        return install, fils

    def test_abs_does_not_select_abs_cf_when_only_composite_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [
                    ("system/Elegoo/filament/Generic/pla.json", {"name": "Generic PLA @ECC2", "filament_type": ["PLA"]}),
                    ("system/Elegoo/filament/Generic/abs_cf.json", {"name": "Generic ABS-CF @ECC2", "filament_type": ["ABS-CF"]}),
                    # Caso real ECC2: ASA-CF declara filament_type=["ASA"] mas tem -CF no perfil
                    ("system/Elegoo/filament/Generic/asa_cf.json", {"name": "Elegoo ASA-CF @ECC2", "filament_type": ["ASA"]}),
                ],
            )
            sel_abs = select_material_profile(MaterialIdentity("ABS", ""), tuple(fils), install)
            self.assertIsNone(sel_abs.profile)
            self.assertIn("ABS", sel_abs.reason)

            sel_asa = select_material_profile(MaterialIdentity("ASA", ""), tuple(fils), install)
            self.assertIsNone(sel_asa.profile)

            sel_abs_cf = select_material_profile(MaterialIdentity("ABS", "CF"), tuple(fils), install)
            self.assertIsNotNone(sel_abs_cf.profile)
            self.assertEqual(sel_abs_cf.profile.name, "Generic ABS-CF @ECC2")
            self.assertFalse(sel_abs_cf.requires_choice)

            sel_asa_cf = select_material_profile(MaterialIdentity("ASA", "CF"), tuple(fils), install)
            self.assertIsNotNone(sel_asa_cf.profile)
            self.assertEqual(sel_asa_cf.profile.name, "Elegoo ASA-CF @ECC2")

    def test_renamed_profile_uses_resolved_metadata_not_name_substring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [
                    # Nome sem ABS e até com "PLA" no nome, mas metadado real é ABS
                    ("user/u1/filament/renamed.json", {"name": "Carretel Teste PLA Renomeado", "filament_type": ["ABS"]}),
                ],
            )
            ident = extract_profile_material_identity(fils[0], install)
            self.assertEqual(ident, MaterialIdentity("ABS", ""))

            sel_abs = select_material_profile(MaterialIdentity("ABS", ""), tuple(fils), install)
            self.assertIsNotNone(sel_abs.profile)
            self.assertEqual(sel_abs.profile.name, "Carretel Teste PLA Renomeado")
            self.assertFalse(sel_abs.requires_choice)

            sel_pla = select_material_profile(MaterialIdentity("PLA", ""), tuple(fils), install)
            self.assertIsNone(sel_pla.profile)

    def test_no_candidate_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [("system/Elegoo/filament/Generic/pla.json", {"name": "Elegoo PLA @ECC2", "filament_type": ["PLA"]})],
            )
            sel = select_material_profile(MaterialIdentity("TPU", ""), tuple(fils), install)
            self.assertIsNone(sel.profile)
            self.assertFalse(sel.requires_choice)
            self.assertIn("TPU", sel.reason)

    def test_two_equivalent_candidates_require_explicit_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [
                    ("user/u1/filament/abs_a.json", {"name": "Minha Marca A", "filament_type": ["ABS"]}),
                    ("user/u1/filament/abs_b.json", {"name": "Minha Marca B", "filament_type": ["ABS"]}),
                ],
            )
            sel = select_material_profile(MaterialIdentity("ABS", ""), tuple(fils), install)
            self.assertIsNone(sel.profile)
            self.assertTrue(sel.requires_choice)
            self.assertIn("Minha Marca A", sel.reason)
            self.assertIn("Minha Marca B", sel.reason)

    def test_unknown_variant_requires_explicit_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [("system/Elegoo/filament/Generic/abs.json", {"name": "Elegoo ABS @ECC2", "filament_type": ["ABS"]})],
            )
            sel = select_material_profile(parse_material_identity("ABS-ESD"), tuple(fils), install)
            self.assertIsNone(sel.profile)
            self.assertTrue(sel.requires_choice)
            self.assertIn("ESD", sel.reason)

    def test_multi_slot_validation_blocks_mismatch_and_ignores_unused_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [
                    ("system/Elegoo/filament/Generic/pla.json", {"name": "Elegoo PLA @ECC2", "filament_type": ["PLA"]}),
                    ("system/Elegoo/filament/Generic/tpu.json", {"name": "Elegoo TPU 95A @ECC2", "filament_type": ["TPU"]}),
                    ("system/Elegoo/filament/Generic/abs.json", {"name": "Elegoo ABS @ECC2", "filament_type": ["ABS"]}),
                ],
            )
            by_name = {p.name: p for p in fils}
            proj = ProjectInfo(
                root / "multi.3mf",
                {},
                (
                    FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),
                    FilamentInfo(2, "TPU", "#000000", "Bambu TPU"),
                    FilamentInfo(3, "ABS-ESD", "#FF0000", "Não usado"),
                ),
                (PlateInfo(1, 1, ("1", "2"), ("1", "2"), ("1", "2")),),
                ("Parte A",),
                (),
                (),
                used_filament_slots=("1", "2"),
            )
            # Slot 1/2 corretos e confirmados; slot 3 não usado é divergente/sem perfil e NÃO bloqueia
            targets_ok = [
                SlotMaterialTarget(slot=1, identity=MaterialIdentity("PLA", ""), profile=by_name["Elegoo PLA @ECC2"], confirmed=True),
                SlotMaterialTarget(slot=2, identity=parse_material_identity("TPU 95A"), profile=by_name["Elegoo TPU 95A @ECC2"], confirmed=True),
                SlotMaterialTarget(slot=3, identity=MaterialIdentity("DESCONHECIDO", ""), profile=None, confirmed=False),
            ]
            ok, errors = validate_slot_material_plan(proj, targets_ok, install)
            self.assertTrue(ok, f"Deveria aceitar quando apenas slot não usado está pendente: {errors}")

            # Divergência: slot 1 declarado PLA mas perfil ABS selecionado -> bloqueia
            targets_bad = [
                SlotMaterialTarget(slot=1, identity=MaterialIdentity("PLA", ""), profile=by_name["Elegoo ABS @ECC2"], confirmed=True),
                SlotMaterialTarget(slot=2, identity=parse_material_identity("TPU 95A"), profile=by_name["Elegoo TPU 95A @ECC2"], confirmed=True),
            ]
            ok_bad, errors_bad = validate_slot_material_plan(proj, targets_bad, install)
            self.assertFalse(ok_bad)
            self.assertTrue(any("Slot 1" in e for e in errors_bad))

            # Falta de confirmação no slot 2 -> bloqueia
            targets_unconf = [
                SlotMaterialTarget(slot=1, identity=MaterialIdentity("PLA", ""), profile=by_name["Elegoo PLA @ECC2"], confirmed=True),
                SlotMaterialTarget(slot=2, identity=parse_material_identity("TPU 95A"), profile=by_name["Elegoo TPU 95A @ECC2"], confirmed=False),
            ]
            ok_unconf, errors_unconf = validate_slot_material_plan(proj, targets_unconf, install)
            self.assertFalse(ok_unconf)
            self.assertTrue(any("Slot 2" in e for e in errors_unconf))

    def test_preferred_profile_resolves_tie_but_never_overrides_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install, fils = self._base_env(
                root,
                [
                    ("system/Elegoo/filament/Generic/pla.json", {"name": "Elegoo PLA @ECC2", "filament_type": ["PLA"]}),
                    ("user/u1/filament/ender.json", {"name": "ENDER PLA", "filament_type": ["PLA"]}),
                    ("user/u1/filament/abs_cf.json", {"name": "Minha ABS-CF", "filament_type": ["ABS-CF"]}),
                ],
            )
            # Sem preferência, haver perfil de usuário competindo exige escolha explícita
            no_pref = select_material_profile(MaterialIdentity("PLA", ""), tuple(fils), install)
            self.assertIsNone(no_pref.profile)
            self.assertTrue(no_pref.requires_choice)

            # Com preferred_profile_name="ENDER PLA" válido para PLA, pré-seleciona ENDER PLA
            with_pref = select_material_profile(
                MaterialIdentity("PLA", ""),
                tuple(fils),
                install,
                preferred_profile_name="ENDER PLA",
            )
            self.assertIsNotNone(with_pref.profile)
            self.assertEqual(with_pref.profile.name, "ENDER PLA")
            self.assertFalse(with_pref.requires_choice)

            # Nunca aceita perfil preferido de outro material ou variante (ABS-CF para ABS puro)
            wrong_pref = select_material_profile(
                MaterialIdentity("ABS", ""),
                tuple(fils),
                install,
                preferred_profile_name="Minha ABS-CF",
            )
            self.assertIsNone(wrong_pref.profile)

            # Perfil inexistente cai no comportamento padrão seguro
            missing_pref = select_material_profile(
                MaterialIdentity("PLA", ""),
                tuple(fils),
                install,
                preferred_profile_name="Apagado PLA",
            )
            self.assertIsNone(missing_pref.profile)
            self.assertTrue(missing_pref.requires_choice)


if __name__ == "__main__":
    unittest.main()
