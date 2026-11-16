import json
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.converter import ConversionResult
from maker_elegoo.professor import Advice, PrintGoal
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.slicer import ExportResult, PlateValidationMetric, ValidationResult
from maker_elegoo.ui import MakerElegooApp


def _setup_fake_slicer_env(root: Path) -> dict[str, str]:
    data_dir = root / "AppData" / "ElegooSlicer"
    exe_dir = root / "ProgramFiles" / "ElegooSlicer"
    exe_dir.mkdir(parents=True)
    (exe_dir / "elegoo-slicer.exe").touch()
    base = "Elegoo Centauri Carbon 2 0.4 nozzle"
    entries = [
        (
            "system/Elegoo/machine/ECC2/base.json",
            {
                "type": "machine",
                "name": base,
                "printer_model": "Elegoo Centauri Carbon 2",
                "nozzle_diameter": ["0.4"],
                "min_layer_height": ["0.08"],
                "max_layer_height": ["0.28"],
                "support_chamber_temp_control": "0",
            },
        ),
        (
            "system/Elegoo/process/ECC2/std.json",
            {
                "type": "process",
                "name": "0.20mm Standard @Elegoo CC2 0.4 nozzle",
                "layer_height": "0.20",
                "wall_loops": "2",
                "top_shell_layers": "3",
                "bottom_shell_layers": "3",
                "sparse_infill_density": "15%",
                "sparse_infill_pattern": "grid",
                "compatible_printers": [base],
            },
        ),
        (
            "system/Elegoo/filament/Generic/pla.json",
            {
                "type": "filament",
                "name": "Elegoo PLA @ECC2",
                "filament_type": ["PLA"],
                "fan_min_speed": ["60"],
                "fan_max_speed": ["100"],
                "compatible_printers": [base],
            },
        ),
        (
            "system/Elegoo/filament/Generic/abs.json",
            {
                "type": "filament",
                "name": "Elegoo ABS @ECC2",
                "filament_type": ["ABS"],
                "fan_min_speed": ["10"],
                "fan_max_speed": ["40"],
                "overhang_fan_speed": ["80"],
                "nozzle_temperature": ["270"],
                "textured_plate_temp": ["90"],
                "compatible_printers": [base],
            },
        ),
        (
            "system/Elegoo/filament/Generic/petg.json",
            {
                "type": "filament",
                "name": "Elegoo PETG @ECC2",
                "filament_type": ["PETG"],
                "fan_min_speed": ["20"],
                "fan_max_speed": ["50"],
                "compatible_printers": [base],
            },
        ),
        (
            "system/Elegoo/filament/Generic/tpu.json",
            {
                "type": "filament",
                "name": "Elegoo TPU 95A @ECC2",
                "filament_type": ["TPU"],
                "fan_min_speed": ["50"],
                "fan_max_speed": ["80"],
                "compatible_printers": [base],
            },
        ),
        (
            "system/Elegoo/filament/Generic/abs_cf.json",
            {
                "type": "filament",
                "name": "Generic ABS-CF @ECC2",
                "filament_type": ["ABS-CF"],
                "fan_min_speed": ["10"],
                "fan_max_speed": ["30"],
                "compatible_printers": [base],
            },
        ),
    ]
    for rel, payload in entries:
        path = data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "APPDATA": str(root / "AppData"),
        "ProgramFiles": str(root / "ProgramFiles"),
        "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs"),
    }


def _collect_all_label_texts(widget) -> str:
    texts: list[str] = []
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
            if text:
                texts.append(str(text))
        except Exception:
            pass
        texts.append(_collect_all_label_texts(child))
    return "\n".join(texts)


class UIBeginnerFlowTests(unittest.TestCase):
    def test_beginner_main_flow_hides_advanced_details_never_presumes_filament_and_measures_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = _setup_fake_slicer_env(root)

            # 1) Jornada 1: Peça 1-filamento simples, iniciante quer fluxo rápido sem abrir detalhes avançados
            proj_single = ProjectInfo(
                root / "chaveiro.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Chaveiro",),
                (),
                (),
                used_filament_slots=("1",),
            )
            # 2) Jornada 2: Multi-filamento declarado (5 slots declarados, slots 1-2 usados com materiais distintos)
            proj_multi = ProjectInfo(
                root / "multi.3mf",
                {"printer_model": "Bambu Lab P1S", "layer_height": "0.20"},
                (
                    FilamentInfo(1, "PLA", "#FFFFFF", "Slot 1"),
                    FilamentInfo(2, "TPU", "#111111", "Slot 2"),
                    FilamentInfo(3, "ABS-ESD", "#222222", "Slot 3 não usado"),
                    FilamentInfo(4, "PLA", "#333333", "Slot 4 não usado"),
                    FilamentInfo(5, "PLA", "#444444", "Slot 5 não usado"),
                ),
                (
                    PlateInfo(1, 1, ("1",), ("1",), ("1",)),
                    PlateInfo(2, 2, ("2", "3"), ("1", "2"), ("1", "2")),
                ),
                ("Parte A", "Parte B", "Parte C"),
                (),
                (),
                used_filament_slots=("1", "2"),
            )

            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    # Botão principal orientado ao iniciante e detalhes avançados recolhidos por padrão
                    self.assertEqual(app.convert_button.cget("text"), "Traduzir para minha ELEGOO")
                    self.assertFalse(app.advanced_visible.get())
                    self.assertEqual(app.advanced_frame.winfo_manager(), "")

                    # Abrir detalhes avançados e recolher novamente funciona
                    app._toggle_advanced()
                    self.assertTrue(app.advanced_visible.get())
                    self.assertNotEqual(app.advanced_frame.winfo_manager(), "")
                    app._toggle_advanced()
                    self.assertFalse(app.advanced_visible.get())

                    for jornada, proj, mat_choice in (
                        ("1-filamento", proj_single, "PLA"),
                        ("multi-placa", proj_multi, "ABS"),
                    ):
                        t0 = time.monotonic()
                        decisions = 0

                        with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                            app.file_var.set(str(proj.path))
                            app._inspect_file()  # Decisão 1: escolher 3MF

                        # Regra de ouro: NUNCA presumir filamento físico == 3MF
                        self.assertFalse(app.physical_filament_confirmed_var.get())
                        card_unconfirmed = app.preconversion_var.get()
                        self.assertIn("PENDENTE", card_unconfirmed)

                        if jornada == "1-filamento":
                            # Decisão 2: confirmar filamento físico explicitamente
                            app.physical_material_var.set(mat_choice)
                            app.physical_filament_confirmed_var.set(True)
                            app._on_physical_filament_changed()
                            decisions += 2  # (1) 3MF + (2) confirmação de filamento físico

                            card_ready = app.preconversion_var.get()
                            self.assertIn("CARTÃO PRÉ-CONVERSÃO", card_ready)
                            self.assertIn("Confirmado", card_ready)
                            self.assertIn(f"{len(proj.plates)} placa", card_ready)
                        else:
                            # Multisslot PLA+TPU: escolher ABS global NÃO transforma em ABS+ABS nem confirma slots
                            app.physical_material_var.set("ABS")
                            app.physical_filament_confirmed_var.set(True)
                            app._on_physical_filament_changed()
                            self.assertFalse(app.physical_filament_confirmed_var.get())
                            self.assertIn("PLA", app.filament_vars[0].get())
                            self.assertNotIn("ABS", app.filament_vars[1].get())

                            # Confirmação é explícita por slot usado (slot 3 não usado não bloqueia)
                            app.slot_target_vars[1].set("PLA")
                            app.slot_target_vars[2].set("TPU 95A")
                            self.assertIn("TPU", app.filament_vars[1].get())
                            app.slot_confirmed_vars[1].set(True)
                            app._on_slot_confirmed_toggled(1)
                            app.slot_confirmed_vars[2].set(True)
                            app._on_slot_confirmed_toggled(2)
                            decisions += 2

                            card_ready = app.preconversion_var.get()
                            self.assertIn("CARTÃO PRÉ-CONVERSÃO", card_ready)
                            self.assertIn("Confirmado", card_ready)
                            self.assertIn(f"{len(proj.plates)} placa", card_ready)

                        # Quando usuário indica uso mecânico sem preencher detalhes ('Não sei'), confiança cai para baixa
                        from maker_elegoo.labels import purpose_label

                        app.purpose_var.set(purpose_label("esforco"))
                        self.assertIn("incompleto", app.confidence_var.get().lower())
                        app.purpose_var.set(purpose_label("decorativa"))

                        # Sem ambiguidade/risco quando advices=() e confirmado -> não interrompe usuário
                        out_path = root / f"out_{jornada}.3mf"
                        fake_res = ConversionResult(
                            True,
                            out_path,
                            "Todas as placas foram fatiadas",
                            ExportResult(True, out_path, "Projeto ELEGOO exportado"),
                            ValidationResult(
                                True,
                                len(proj.plates),
                                "Todas as placas foram fatiadas",
                                (),
                                1800,
                                14.5,
                                tuple(PlateValidationMetric(p.number, 900, 7.25) for p in proj.plates),
                            ),
                            None,
                            proj,
                            {},
                            proj.plates,
                        )
                        with patch("maker_elegoo.ui.filedialog.asksaveasfilename", return_value=str(out_path)), \
                             patch("maker_elegoo.ui.advise_offline", return_value=[]), \
                             patch("maker_elegoo.ui.convert_project", return_value=fake_res), \
                             patch.object(app, "_show_professor_dialog") as modal_spy:
                            app._convert()  # Decisão 3: Traduzir para minha ELEGOO
                            decisions += 1
                            deadline = time.monotonic() + 3.0
                            while app.result is not fake_res and time.monotonic() < deadline:
                                app.update()
                                time.sleep(0.01)
                            modal_spy.assert_not_called()

                        elapsed = time.monotonic() - t0
                        self.assertLessEqual(decisions, 3)
                        self.assertLess(elapsed, 3.0)
                        self.assertEqual(app.result, fake_res)
                finally:
                    app.destroy()

    def test_contextual_questions_confidence_professor_dialog_details_and_local_feedback_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = _setup_fake_slicer_env(root)
            proj = ProjectInfo(
                root / "suporte.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Suporte",),
                (),
                (),
                used_filament_slots=("1",),
            )
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app.file_var.set(str(proj.path))
                        app._inspect_file()

                    # Preenche todas as perguntas contextuais -> confiança Alta
                    from maker_elegoo.labels import (
                        criticality_label,
                        fit_label,
                        heat_exposure_label,
                        load_type_label,
                        priority_label,
                        purpose_label,
                    )

                    app.purpose_var.set(purpose_label("esforco"))
                    app.priority_var.set(priority_label("equilibrio"))
                    app.load_type_var.set(load_type_label("tracao_eixo_z"))
                    app.criticality_var.set(criticality_label("alta"))
                    app.fit_clearance_var.set(fit_label("encaixe_justo"))
                    app.heat_exposure_var.set(heat_exposure_label("calor_sol"))
                    app.physical_material_var.set("ABS")
                    app.physical_filament_confirmed_var.set(True)
                    app._on_physical_filament_changed()

                    self.assertIn("completo", app.confidence_var.get().lower())

                    goal = app._current_goal()
                    self.assertEqual(goal.load_type, "tracao_eixo_z")
                    self.assertEqual(goal.criticality, "alta")
                    self.assertEqual(goal.fit_clearance, "encaixe_justo")
                    self.assertEqual(goal.heat_exposure, "calor_sol")
                    self.assertEqual(goal.physical_material, "ABS")

                    plan = app._selected_profiles()
                    conv_plan = app._build_current_plan(*plan)
                    advices = [
                        Advice(
                            scope="process",
                            slot=None,
                            key="wall_loops",
                            current="2",
                            proposed="4",
                            title="Aumentar Paredes (4)",
                            why="Maior casca perimetral.",
                            default_on=True,
                            expected_effect="Eleva espessura e massa.",
                            what_to_check="Faça ensaio físico com carga real.",
                            evidence_class="estimado_regra_ia",
                            requires_physical_test=False,
                            confidence="alta",
                        ),
                        Advice(
                            scope="alert",
                            slot=None,
                            key="",
                            current="",
                            proposed="",
                            title="Carga no Eixo Z",
                            why="Esforço perpendicular às camadas.",
                            default_on=False,
                            expected_effect="Evitar falso senso de segurança.",
                            what_to_check="Rotacione no Slicer e teste fisicamente.",
                            evidence_class="depende_teste_fisico",
                            requires_physical_test=True,
                            confidence="alta",
                        ),
                    ]
                    dialog = app._show_professor_dialog(conv_plan, str(root / "out.3mf"), advices)
                    try:
                        all_text = _collect_all_label_texts(dialog).lower()
                        self.assertIn("efeito esperado:", all_text)
                        self.assertIn("o que conferir:", all_text)
                        self.assertIn("depende de teste físico", all_text)
                    finally:
                        dialog.destroy()

                    # Testar registro de feedback local opt-in sem rede/3MF
                    from maker_elegoo.history import load_feedback_history

                    app.save_history_var.set(True)
                    rec = app._record_feedback(
                        target_material="ABS",
                        purpose="esforco",
                        visual_result="empenou_soltou",
                        notes="Canto levantou sem brim.",
                    )
                    self.assertIsNotNone(rec)
                    saved_records = load_feedback_history()
                    self.assertEqual(len(saved_records), 1)
                    self.assertEqual(saved_records[0].visual_result, "empenou_soltou")
                finally:
                    app.destroy()

    def test_task27_ux_safety_missing_slicer_unknown_material_invalid_open_and_feedback(self):
        from maker_elegoo.history import load_feedback_history
        from maker_elegoo.labels import PURPOSE_LABELS
        from maker_elegoo.profiles import ProfileError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_empty = {
                "APPDATA": str(root / "EmptyAppData"),
                "ProgramFiles": str(root / "EmptyProgramFiles"),
                "MAKER_ELEGOO_CONFIG_DIR": str(root / "prefs_empty"),
            }
            with patch.dict(os.environ, env_empty):
                app_no_slicer = MakerElegooApp()
                try:
                    self.assertIsNone(app_no_slicer.install)
                    self.assertFalse(app_no_slicer.advanced_visible.get())
                    self.assertNotEqual(app_no_slicer.missing_slicer_banner.winfo_manager(), "")
                finally:
                    app_no_slicer.destroy()

            env = _setup_fake_slicer_env(root)
            proj = ProjectInfo(
                root / "peca.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Peca",),
                (),
                (),
                used_filament_slots=("1",),
            )
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app.file_var.set(str(proj.path))
                        app._inspect_file()

                    # Não permite confirmar 'Não sei informar'
                    app.physical_filament_confirmed_var.set(True)
                    app._on_physical_filament_changed()
                    self.assertFalse(app.physical_filament_confirmed_var.get())

                    with patch("maker_elegoo.ui.messagebox.showwarning") as warn_spy, \
                         patch("maker_elegoo.ui.messagebox.askyesno") as ask_spy:
                        app._convert()
                        warn_spy.assert_called_once()
                        ask_spy.assert_not_called()
                        self.assertFalse(app.physical_filament_confirmed_var.get())

                    # Falha com arquivo existente no disco NÃO pode liberar Abrir no ELEGOO Slicer
                    out_file = root / "saida_invalida.3mf"
                    out_file.write_bytes(b"fake")
                    bad_res = ConversionResult(
                        False, out_file, "Validação falhou",
                        ExportResult(True, out_file, "ok"),
                        ValidationResult(False, 0, "Falha"),
                        None, proj, {}, proj.plates,
                    )
                    plan_obj = app._build_current_plan(*app._selected_profiles())
                    app.worker_queue.put((bad_res, plan_obj, (), (), None, None))
                    app._poll_worker()
                    self.assertEqual(str(app.open_button.cget("state")), "disabled")
                    self.assertEqual(str(app.open_folder_button.cget("state")), "disabled")
                    self.assertIn("NÃO imprima", app.result_banner_var.get())

                    good_res = ConversionResult(
                        True, out_file, "Todas as placas foram fatiadas",
                        ExportResult(True, out_file, "ok"),
                        ValidationResult(True, 1, "Todas as placas foram fatiadas", (), 600, 12.0),
                        None, proj, {}, proj.plates,
                    )
                    app.worker_queue.put((good_res, plan_obj, (), (), None, None))
                    app._poll_worker()
                    self.assertEqual(str(app.open_button.cget("state")), "normal")
                    self.assertEqual(str(app.open_folder_button.cget("state")), "normal")
                    self.assertIn("Pronto", app.result_banner_var.get())

                    # Erro em _update_context_preview não deixa cartão antigo preso
                    app.preconversion_var.set("CARTAO ANTIGO STALE")
                    with patch.object(app, "_selected_profiles", side_effect=ProfileError("Sem perfil")):
                        app._update_context_preview()
                    self.assertNotIn("CARTAO ANTIGO STALE", app.preconversion_var.get())
                    self.assertIn("Não foi possível", app.preconversion_var.get())

                    # Feedback usa rótulos amigáveis e pede confirmação ao limpar
                    app.save_history_var.set(True)
                    app._record_feedback(target_material="PLA", purpose="esforco", visual_result="aprovado")
                    dlg = app._open_feedback_dialog()
                    try:
                        combos = []
                        def _walk(w):
                            for ch in w.winfo_children():
                                if ch.winfo_class() == "TCombobox":
                                    combos.append(tuple(ch.cget("values")))
                                _walk(ch)
                        _walk(dlg)
                        purpose_vals = next(v for v in combos if PURPOSE_LABELS["esforco"] in v)
                        self.assertNotIn("chaveiro_rigido", purpose_vals)
                        clear_btn = None
                        def _find_btn(w):
                            nonlocal clear_btn
                            for ch in w.winfo_children():
                                if ch.winfo_class() == "TButton" and str(ch.cget("text")) == "Limpar histórico":
                                    clear_btn = ch
                                _find_btn(ch)
                        _find_btn(dlg)
                        self.assertIsNotNone(clear_btn)
                        with patch("maker_elegoo.ui.messagebox.askyesno", return_value=False) as confirm_clear:
                            clear_btn.invoke()
                            confirm_clear.assert_called_once()
                        self.assertEqual(len(load_feedback_history()), 1)
                    finally:
                        dlg.destroy()

                    # Fila dedicada para calibração (sem self.after de worker thread)
                    self.assertTrue(hasattr(app, "calib_queue"))
                finally:
                    app.destroy()

    def test_task1_blocks_missing_material_resets_confirmation_on_change_and_supports_planned_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "OnlyComposite" / "AppData" / "ElegooSlicer"
            exe_dir = root / "OnlyComposite" / "ProgramFiles" / "ElegooSlicer"
            exe_dir.mkdir(parents=True)
            (exe_dir / "elegoo-slicer.exe").touch()
            base = "Elegoo Centauri Carbon 2 0.4 nozzle"
            for rel, payload in (
                ("system/Elegoo/machine/ECC2/base.json", {"type": "machine", "name": base, "printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]}),
                ("system/Elegoo/process/ECC2/std.json", {"type": "process", "name": "0.20mm Standard @Elegoo CC2 0.4 nozzle", "layer_height": "0.20", "compatible_printers": [base]}),
                ("system/Elegoo/filament/Generic/pla.json", {"type": "filament", "name": "Generic PLA @ECC2", "filament_type": ["PLA"], "compatible_printers": [base]}),
                ("system/Elegoo/filament/Generic/abs_cf.json", {"type": "filament", "name": "Generic ABS-CF @ECC2", "filament_type": ["ABS-CF"], "compatible_printers": [base]}),
            ):
                p = data_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(payload), encoding="utf-8")
            env_comp = {
                "APPDATA": str(root / "OnlyComposite" / "AppData"),
                "ProgramFiles": str(root / "OnlyComposite" / "ProgramFiles"),
                "MAKER_ELEGOO_CONFIG_DIR": str(root / "OnlyComposite" / "prefs"),
            }
            proj = ProjectInfo(
                root / "peca.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Peca",),
                (),
                (),
                used_filament_slots=("1",),
            )
            with patch.dict(os.environ, env_comp):
                app = MakerElegooApp()
                try:
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app.file_var.set(str(proj.path))
                        app._inspect_file()
                    app.physical_material_var.set("PLA")
                    app.physical_filament_confirmed_var.set(True)
                    app._on_physical_filament_changed()
                    self.assertTrue(app.physical_filament_confirmed_var.get())

                    # Selecionar ABS sem ABS puro (apenas ABS-CF): NÃO seleciona ABS-CF, NÃO mantém PLA confirmado e BLOQUEIA conversão
                    app.physical_material_var.set("ABS")
                    app._on_physical_filament_changed()
                    self.assertFalse(app.physical_filament_confirmed_var.get())
                    self.assertEqual(app.filament_vars[0].get(), "")
                    with patch("maker_elegoo.ui.messagebox.showwarning") as warn_spy, \
                         patch("maker_elegoo.ui.filedialog.asksaveasfilename") as save_spy:
                        app._convert()
                        warn_spy.assert_called_once()
                        save_spy.assert_not_called()
                finally:
                    app.destroy()

            # Ambiente completo: troca de perfil invalida confirmação; modo planejado diferencia texto de carregado
            env_full = _setup_fake_slicer_env(root / "Full")
            with patch.dict(os.environ, env_full):
                app2 = MakerElegooApp()
                try:
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app2.file_var.set(str(proj.path))
                        app2._inspect_file()
                    app2.physical_material_var.set("PLA")
                    app2.physical_filament_confirmed_var.set(True)
                    app2._on_physical_filament_changed()
                    self.assertTrue(app2.physical_filament_confirmed_var.get())

                    # Mudança manual de perfil invalida confirmação e cria bloqueio de divergência
                    app2.filament_vars[0].set("Elegoo ABS @ECC2")
                    self.assertFalse(app2.physical_filament_confirmed_var.get())
                    self.assertIn("diverge", app2.slot_issue_vars[1].get().lower())

                    # Modo planejado: diferencia texto e nunca afirma que está carregado
                    app2.material_readiness_var.set("planejado")
                    app2.physical_material_var.set("PLA")
                    app2.physical_filament_confirmed_var.set(True)
                    app2._on_physical_filament_changed()
                    card = app2.preconversion_var.get()
                    self.assertIn("Material PLANEJADO", card)
                    self.assertIn("NÃO afirmado como carregado", card)
                finally:
                    app2.destroy()

    def test_task4_progressive_flow_conditional_mechanics_quick_results_grouped_dialog_and_viewport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = _setup_fake_slicer_env(root)
            proj = ProjectInfo(
                root / "modelo.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Peca",),
                (),
                (),
                used_filament_slots=("1",),
            )
            with patch.dict(os.environ, env):
                app = MakerElegooApp()
                try:
                    # 1. Decorativa oculta perguntas mecânicas condicionais e mantém 'Não sei informar'
                    from maker_elegoo.labels import load_type_label, purpose_label
                    app.purpose_var.set(purpose_label("decorativa"))
                    app.load_type_var.set(load_type_label("nao_sei"))
                    app.update_idletasks()
                    self.assertEqual(app.mechanics_frame.winfo_manager(), "")

                    # 2. Troca para 'esforco' revela perguntas mecânicas sem inventar respostas
                    app.purpose_var.set(purpose_label("esforco"))
                    app.update_idletasks()
                    self.assertNotEqual(app.mechanics_frame.winfo_manager(), "")
                    self.assertEqual(app.load_type_var.get(), load_type_label("nao_sei"))
                    self.assertIn("incompleto", app.confidence_var.get().lower())

                    # 3. No resultado, acesso rápido a Qualidade/Equilíbrio/Velocidade sem abrir Avançado
                    self.assertEqual(app.advanced_frame.winfo_manager(), "")
                    self.assertTrue(hasattr(app, "quick_compare_frame"))
                    self.assertNotEqual(app.quick_compare_frame.winfo_manager(), "")
                    self.assertEqual(app.quick_qualidade_btn.cget("text"), "Qualidade")
                    self.assertEqual(app.quick_equilibrio_btn.cget("text"), "Equilíbrio")
                    self.assertEqual(app.quick_velocidade_btn.cget("text"), "Velocidade")

                    # 4. Janela 1366x768 @ 100% e 150% DPI com scroll, quebra de texto extenso e foco por teclado
                    app.preconversion_var.set("Texto extenso de teste " * 12)
                    app.geometry("1366x768")
                    for scale in (1.0, 1.5):
                        app.tk.call("tk", "scaling", scale)
                        app.update()
                        self.assertLessEqual(app.winfo_reqwidth(), 1366)
                        self.assertTrue(hasattr(app, "main_canvas"))
                        self.assertGreater(int(app.preconversion_label.cget("wraplength")), 300)
                        first_focus = app.purpose_combo
                        first_focus.focus_set()
                        nxt = first_focus.tk_focusNext()
                        self.assertNotEqual(nxt, first_focus)

                    # 5. Aprovação agrupada mostra no máx 3 destaques inicialmente e conflitos visíveis
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app.file_var.set(str(proj.path))
                        app._inspect_file()
                    plan = app._build_current_plan(*app._selected_profiles())
                    advices = [
                        Advice("process", None, "wall_loops", "2", "4", "Ajuste 1", "Motivo 1", True),
                        Advice("process", None, "top_shell_layers", "3", "5", "Ajuste 2", "Motivo 2", True),
                        Advice("process", None, "sparse_infill_density", "15%", "30%", "Ajuste 3", "Motivo 3", True),
                        Advice("process", None, "seam_position", "aligned", "back", "Ajuste 4 extra", "Motivo 4", True),
                        Advice("process", None, "outer_wall_speed", "160", "80", "Ajuste 5 extra", "Motivo 5", False),
                        Advice(
                            "alert", None, "", "", "",
                            "Conflito com política conservadora (IA)",
                            "IA propôs 1 parede; mantido piso de 4 paredes.",
                            False,
                        ),
                    ]
                    dlg = app._show_professor_dialog(plan, str(root / "out.3mf"), advices)
                    try:
                        dlg.update_idletasks()
                        texts = []

                        def _walk(w):
                            try:
                                t = str(w.cget("text"))
                                if t:
                                    texts.append(t)
                            except tk.TclError:
                                pass
                            for c in w.winfo_children():
                                _walk(c)

                        _walk(dlg)
                        joined = " | ".join(texts).lower()
                        self.assertIn("conflito", joined)
                        self.assertIn("mais 2", joined)
                        self.assertTrue(hasattr(dlg, "_extra_adjustments_frame"))
                        self.assertEqual(dlg._extra_adjustments_frame.winfo_manager(), "")
                        dlg._toggle_extra_adjustments()
                        dlg.update_idletasks()
                        self.assertNotEqual(dlg._extra_adjustments_frame.winfo_manager(), "")
                    finally:
                        dlg.destroy()
                finally:
                    app.destroy()

    def test_task6_close_teardown_cancels_all_pollers_without_invalid_command_or_worker_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = _setup_fake_slicer_env(root)
            proj = ProjectInfo(
                root / "modelo.3mf",
                {"printer_model": "Bambu Lab A1", "layer_height": "0.20"},
                (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
                (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                ("Peca",),
                (),
                (),
                used_filament_slots=("1",),
            )
            after_attrs = (
                "_worker_after",
                "_ai_after",
                "_professor_after",
                "_orientation_after",
                "_comparison_after",
                "_inspect_after",
                "_preview_after",
                "_calib_after",
            )
            with patch.dict(os.environ, env), tempfile.TemporaryFile() as stderr_cap:
                old_fd = os.dup(2)
                try:
                    sys.stderr.flush()
                    os.dup2(stderr_cap.fileno(), 2)
                    app = MakerElegooApp()
                    try:
                        # Simular re-disparo manual/repetido de todos os pollers antes de fechar
                        for _ in range(2):
                            app._poll_worker()
                            app._poll_ai()
                            app._poll_professor()
                            app._poll_orientation()
                            app._poll_comparison()
                            app._poll_inspect()
                            app._poll_preview()
                            app._poll_calib()
                        # Não pode acumular múltiplos callbacks para os mesmos pollers
                        self.assertLessEqual(len(app.tk.call("after", "info")), len(after_attrs))
                    finally:
                        app.destroy()

                    self.assertTrue(getattr(app, "_closing", False))
                    for attr in after_attrs:
                        self.assertIsNone(getattr(app, attr, None))

                    # Nova janela rodando event loop após ~180ms não pode disparar "invalid command name"
                    app2 = MakerElegooApp()
                    try:
                        time.sleep(0.18)
                        app2.update()
                    finally:
                        app2.destroy()

                    # Pollers recebendo resultados atrasados após destroy() não podem falhar nem reagendar
                    app3 = MakerElegooApp()
                    with patch("maker_elegoo.ui.inspect_project", return_value=proj):
                        app3.file_var.set(str(proj.path))
                        app3._inspect_file()
                    plan_obj = app3._build_current_plan(*app3._selected_profiles())
                    good_res = ConversionResult(
                        True,
                        root / "out.3mf",
                        "OK",
                        ExportResult(True, root / "out.3mf", "ok"),
                        ValidationResult(True, 1, "OK", (), 300, 8.0),
                        None,
                        proj,
                        {},
                        proj.plates,
                    )
                    app3.worker_queue.put((good_res, plan_obj, (), (), None, None))
                    app3.professor_queue.put((proj, plan_obj, PrintGoal("decorativa", "equilibrio"), str(root / "out.3mf"), "gemini-3.8-flash", [], None))
                    app3.ai_queue.put(([], None))
                    app3.comparison_queue.put(((), None))
                    app3.inspect_queue.put((app3._inspect_generation, proj.path, None))
                    app3.calib_queue.put((root / "cal.3mf", good_res, None))
                    app3.destroy()

                    app3._poll_worker()
                    app3._poll_professor()
                    app3._poll_ai()
                    app3._poll_comparison()
                    app3._poll_inspect()
                    app3._poll_preview()
                    app3._poll_calib()
                    app3._poll_orientation()
                    for attr in after_attrs:
                        self.assertIsNone(getattr(app3, attr, None))
                finally:
                    sys.stderr.flush()
                    os.dup2(old_fd, 2)
                    os.close(old_fd)
                stderr_cap.seek(0)
                err_text = stderr_cap.read().decode("utf-8", errors="replace")
                self.assertNotIn("invalid command name", err_text)


