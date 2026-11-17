# Plano — Memória do Último Tipo de Material e Último Perfil Usado

**Especificação:** [2026-11-17-memoria-material-perfil.md](../specs/2026-11-17-memoria-material-perfil.md)  
**Fluxo:** Superpowers (TDD RED → GREEN → Verificação → Build → Graphify)

## Task 1 — Persistência segura em `settings.py` e suporte a perfil preferido em `material_selection.py`

**Files:** `src/maker_elegoo/settings.py`, `src/maker_elegoo/material_selection.py`, `tests/test_settings.py`, `tests/test_material_selection.py`

- [ ] Escrever testes TDD em `tests/test_settings.py` cobrindo leitura/gravação de `last_physical_material` e `last_profile_by_material` (incluindo fallback seguro quando `last_profile_by_material` vier corrompido ou não-dicionário em `settings.json`).
- [ ] Escrever testes TDD em `tests/test_material_selection.py` cobrindo `select_material_profile(..., preferred_profile_name="ENDER PLA")`:
  - desempata a favor de `"ENDER PLA"` mesmo havendo vários perfis `PLA` do usuário/sistema;
  - ignora `preferred_profile_name` se o perfil salvo divergir do material pedido (ex.: `"ABS-CF"` quando alvo é `"ABS"`) ou se não existir na lista disponível.
- [ ] Rodar `tests.test_settings` e `tests.test_material_selection` e confirmar falhas (RED).
- [ ] Implementar chaves em `DEFAULTS` + helpers `load_material_memory` / `save_material_memory` em `settings.py`, e parâmetro opcional `preferred_profile_name: str | None = None` em `select_material_profile` (`material_selection.py`).
- [ ] Rodar `tests.test_settings` e `tests.test_material_selection` (GREEN) e registrar commit.

## Task 2 — Pré-seleção automática e atualização segura na interface (`ui.py`)

**Files:** `src/maker_elegoo/ui.py`, `tests/test_ui_beginner_flow.py`

- [ ] Escrever testes TDD em `tests/test_ui_beginner_flow.py` cobrindo ponta a ponta:
  - primeira execução sem histórico inicia em `"Não sei informar"`;
  - usuário seleciona `"PLA"`, escolhe `"ENDER PLA"` manualmente (entre 2+ perfis PLA), confirma e fecha o app;
  - ao reabrir o app com o mesmo `MAKER_ELEGOO_CONFIG_DIR` e analisar um novo 3MF de 1 slot: `physical_material_var` já vem pré-selecionado em `"PLA"`, o perfil do slot já vem em `"ENDER PLA"`, e `physical_filament_confirmed_var` permanece `False` (exige clique para liberar conversão);
  - usuário troca para `"ABS"` e depois volta para `"PLA"`: `"ENDER PLA"` é novamente pré-selecionado automaticamente;
  - projetos multisslot não aplicam o último material global sobre slots de polímeros diferentes, mas aplicam a memória de perfil correspondente a cada slot.
- [ ] Rodar `tests.test_ui_beginner_flow` e confirmar falhas (RED).
- [ ] Implementar carga/gravação da memória e rastreamento `_manual_slot_profiles` em `ui.py` (`__init__`, `_inspect_file`, `_render_filaments`, `_apply_material_selection_for_slot`, `_on_physical_filament_changed`, `_on_slot_target_changed`, `_on_slot_profile_manually_changed`, `_on_slot_confirmed_toggled`, `_convert`, `_save_preferences`), preservando integralmente o bloqueio de confirmação e o fluxo sem `.3mf` presumido.
- [ ] Rodar toda a suíte (`python -W default -m unittest discover -s tests -v`) e confirmar zero regressões, zero avisos Tcl e zero `ResourceWarning`; registrar commit.

## Task 3 — Documentação, Build, Smoke Test, Graphify e Publicação

**Files:** `docs/DEVELOPMENT.md`, `docs/superpowers/plans/2026-11-17-memoria-material-perfil.md`

- [ ] Atualizar `docs/DEVELOPMENT.md` descrevendo o comportamento de memória segura de material/perfil (sem auto-confirmação).
- [ ] Atualizar versão (`__version__`) se for gerar nova Release (`v0.2.1`), rebuildar com `.\scripts\build.ps1`, rodar `python .\scripts\smoke_exe.py` e atualizar o grafo com `graphify update .`.
- [ ] Atualizar checkboxes deste plano e registrar commit final (e publicar Release se autorizado pelo usuário).
