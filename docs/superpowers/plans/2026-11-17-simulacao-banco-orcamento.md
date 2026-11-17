# Plano — Simulação de Fatiamento e Banco SQLite para Orçamento (`v0.3.0`)

**Especificação:** [2026-11-17-simulacao-banco-orcamento.md](../specs/2026-11-17-simulacao-banco-orcamento.md)  
**Fluxo:** Superpowers (TDD RED → GREEN → Verificação → Build → Graphify)

## Task 1 — Extração por slot em `slicer.py` e preferência `quote_db_path` em `settings.py`

**Files:** `src/maker_elegoo/slicer.py`, `src/maker_elegoo/settings.py`, `tests/test_slicer.py`, `tests/test_settings.py`, `.gitignore`

- [ ] Escrever testes TDD em `tests/test_slicer.py` cobrindo leitura de `; filament used [g] = 12.34, 5.67` (por slot) junto com `; total filament used [g] = 18.01`, tanto no resultado por placa quanto consolidado em `ValidationResult.slot_filament_grams`.
- [ ] Escrever teste TDD em `tests/test_settings.py` cobrindo persistência da chave `quote_db_path`.
- [ ] Rodar `tests.test_slicer` e `tests.test_settings` (RED).
- [ ] Implementar `slot_filament_grams` em `slicer.py`, `"quote_db_path"` em `settings.py` e incluir `*.db`, `*.db-wal`, `*.db-shm` em `.gitignore`.
- [ ] Rodar `tests.test_slicer` e `tests.test_settings` (GREEN) e registrar commit.

## Task 2 — Módulo `quote_db.py` (SQLite WAL + Schema v1 + View de Orçamento)

**Files:** `src/maker_elegoo/quote_db.py`, `tests/test_quote_db.py`

- [ ] Escrever testes TDD em `tests/test_quote_db.py` cobrindo:
  - criação idempotente do schema (`PRAGMA user_version = 1`, `PRAGMA journal_mode = wal`, tabelas `schema_metadata`, `simulations`, `simulation_plates`, `simulation_slots` e view `v_simulations_summary`);
  - gravação de simulação de 1 slot e multisslot (incluindo dimensões escaladas, supports, audit G-code, quebras reais de slot vs `NULL` honesto quando sem quebra multisslot);
  - leitura externa concorrente em modo somente leitura (`file:...?mode=ro`, `uri=True`) via `v_simulations_summary` enquanto nova conexão está aberta;
  - cálculo determinístico de `project_sha256` sem armazenar conteúdo `.3mf`/`.gcode`.
- [ ] Rodar `tests.test_quote_db` (RED).
- [ ] Implementar `src/maker_elegoo/quote_db.py`.
- [ ] Rodar `tests.test_quote_db` (GREEN) e registrar commit.

## Task 3 — Botão `Simular fatiamento`, fluxo assíncrono em `ui.py` e exclusividade no botão Simular

**Files:** `src/maker_elegoo/ui.py`, `tests/test_ui_beginner_flow.py`

- [ ] Escrever testes TDD em `tests/test_ui_beginner_flow.py` cobrindo:
  - clique em **`Simular fatiamento`** exige Seção 2 validada/confirmada e executa fatiamento em pasta temporária (sem chamar `filedialog.asksaveasfilename` e sem deixar arquivos temporários);
  - em caso de sucesso, grava exatamente 1 registro nas tabelas `simulations` / `simulation_plates` / `simulation_slots` do SQLite configurado (`MAKER_ELEGOO_QUOTE_DB`);
  - em caso de conversão normal (`_convert` / `Traduzir para minha ELEGOO`), **não** grava registro no banco SQLite de simulações;
  - em caso de falha de fatiamento na simulação, **não** grava orçamento inválido no banco;
  - teardown (`destroy()`) cancela `_simulate_after` sem avisos nem callbacks Tcl inválidos.
- [ ] Rodar `tests.test_ui_beginner_flow` (RED).
- [ ] Implementar botão **`Simular fatiamento`**, fila/poller `_simulate_after` em `_POLL_HANDLE_ATTRS`, itens no menu `Ferramentas` e diálogo de configuração do banco SQLite em `ui.py`.
- [ ] Rodar suíte completa (`python -W default -W error::ResourceWarning -m unittest discover -s tests -v`) — zero falhas/avisos — e registrar commit.

## Task 4 — Documento de integração (`docs/INTEGRATION_QUOTE_DB.md`), Docs, Versão `0.3.0`, Build & Graphify

**Files:** `docs/INTEGRATION_QUOTE_DB.md`, `docs/DEVELOPMENT.md`, `src/maker_elegoo/__init__.py`, `docs/superpowers/plans/2026-11-17-simulacao-banco-orcamento.md`

- [ ] Escrever guia completo [docs/INTEGRATION_QUOTE_DB.md](../../INTEGRATION_QUOTE_DB.md) com orientação arquitetural (sistema separado x integrado), dicionário do schema v1, consultas SQL, exemplos Python e Node.js em modo `WAL`/`mode=ro`, e fórmula sugerida de precificação.
- [ ] Atualizar `docs/DEVELOPMENT.md` e `src/maker_elegoo/__init__.py` (`__version__ = "0.3.0"`).
- [ ] Executar `.\scripts\build.ps1`, `python .\scripts\smoke_exe.py`, `graphify update .`, revalidar suíte completa (`unittest discover -s tests`) e conferir `git ls-files "*.3mf" "*.gcode"` vazio.
- [ ] Marcar checkboxes concluídos e registrar commit final.
