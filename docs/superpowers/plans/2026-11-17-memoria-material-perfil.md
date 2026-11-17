# Plano — Memória Completa da Seção 2 e Botão "Confirmar tudo"

**Especificação:** [2026-11-17-memoria-material-perfil.md](../specs/2026-11-17-memoria-material-perfil.md)  
**Fluxo:** Superpowers (TDD RED → GREEN → Verificação → Build → Graphify)

## Task 1 — Persistência completa da Seção 2 em `settings.py` e perfil preferido em `material_selection.py`

**Files:** `src/maker_elegoo/settings.py`, `src/maker_elegoo/material_selection.py`, `tests/test_settings.py`, `tests/test_material_selection.py`

- [ ] Escrever testes TDD em `tests/test_settings.py` cobrindo `last_physical_material`, `last_material_readiness` (normalização/fallback para `"carregado"`) e `load_material_memory` / `save_material_memory` (`last_profile_by_material` JSON válido e corrompido).
- [ ] Escrever testes TDD em `tests/test_material_selection.py` cobrindo `select_material_profile(..., preferred_profile_name="ENDER PLA")`:
  - desempata a favor de `"ENDER PLA"` mesmo havendo vários perfis `PLA` competindo;
  - rejeita `preferred_profile_name` se o perfil divergir nos metadados (ex.: `"ABS-CF"` para `"ABS"`) ou não existir para o bico/máquina atual.
- [ ] Rodar `tests.test_settings` e `tests.test_material_selection` e confirmar falhas (RED).
- [ ] Implementar chaves e helpers em `settings.py` e `preferred_profile_name` em `select_material_profile` (`material_selection.py`).
- [ ] Rodar `tests.test_settings` e `tests.test_material_selection` (GREEN) e registrar commit.

## Task 2 — Pré-seleção completa da Seção 2 e botão `Confirmar tudo` na UI (`ui.py`)

**Files:** `src/maker_elegoo/ui.py`, `tests/test_ui_beginner_flow.py`

- [ ] Escrever testes TDD em `tests/test_ui_beginner_flow.py` cobrindo ponta a ponta:
  - primeira execução sem histórico inicia em `"Não sei informar"` e `"carregado"`;
  - usuário seleciona `"PLA"`, escolhe `"ENDER PLA"` entre múltiplos perfis PLA, alterna carretel para `"planejado"`, confirma e fecha o app;
  - ao reabrir com o mesmo `MAKER_ELEGOO_CONFIG_DIR` e analisar novo 3MF: Seção 2 já abre pré-selecionada com bico, `"PLA"`, `"ENDER PLA"` e `"planejado"`, mantendo confirmações em `False` para revisão;
  - clicar no botão **`Confirmar tudo`** em projeto de 1 slot marca todas as confirmações e libera conversão;
  - clicar em **`Confirmar tudo`** em projeto multisslot marca todos os slots válidos de uma vez, e **bloqueia** se houver `"Não sei informar"` ou perfil ambíguo/divergente;
  - trocar de `"PLA"` para `"ABS"` e voltar para `"PLA"` recupera `"ENDER PLA"` automaticamente.
- [ ] Rodar `tests.test_ui_beginner_flow` e confirmar falhas (RED).
- [ ] Implementar memória completa da Seção 2 e `_confirm_all_section2()` + botão `Confirmar tudo` em `ui.py`, preservando todas as regras de segurança e testes existentes.
- [ ] Rodar toda a suíte (`python -W default -m unittest discover -s tests -v`) e confirmar zero falhas, zero skips e zero avisos; registrar commit.

## Task 3 — Documentação, Build (`v0.2.1`), Smoke Test e Graphify

**Files:** `src/maker_elegoo/__init__.py`, `docs/DEVELOPMENT.md`, `docs/superpowers/plans/2026-11-17-memoria-material-perfil.md`

- [ ] Atualizar `docs/DEVELOPMENT.md` documentando memória da Seção 2 e botão `Confirmar tudo` (mantendo exigência de revisão/confirmação explícita).
- [ ] Atualizar `__version__ = "0.2.1"`, reconstruir instalador com `.\scripts\build.ps1`, validar `python .\scripts\smoke_exe.py`, atualizar grafo com `graphify update .` e conferir `git ls-files "*.3mf" "*.gcode"` vazio.
- [ ] Atualizar checkboxes deste plano e registrar commit final.
