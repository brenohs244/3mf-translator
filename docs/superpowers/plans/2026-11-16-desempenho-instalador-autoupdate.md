# Plano — Desempenho, Instalador Windows (`--onedir`) e Atualização Automática

**Especificação:** [2026-11-16-desempenho-instalador-autoupdate.md](../specs/2026-11-16-desempenho-instalador-autoupdate.md)

## Task 1 — Cache de perfis e eliminação de leituras repetidas (`profiles.py`, `material_selection.py`)

**Files:** `src/maker_elegoo/profiles.py`, `src/maker_elegoo/material_selection.py`, `tests/test_performance.py`

- [x] Escrever testes TDD em `tests/test_performance.py` verificando que chamadas repetidas a `list_profiles`, `resolve_profile`, `select_material_profile` e `build_conversion` não releem o mesmo JSON múltiplas vezes, e que modificações no disco ou `clear_profile_cache()` invalidam o cache.
- [x] Rodar `tests/test_performance.py` e confirmar falha (RED) antes da implementação.
- [x] Implementar cache thread-safe por `(data_dir, kind)` com validação leve em `profiles.py` + `clear_profile_cache()` e reuso de metadados/tier em `material_selection.py` sem quebrar nenhuma assinatura existente.
- [x] Rodar testes de perfis, seleção de material e `test_performance.py` (GREEN) + registrar commit.

## Task 2 — UI sem engasgos: inspeção pesada em background, pollers sob demanda e menos relayout (`project.py`, `ui.py`)

**Files:** `src/maker_elegoo/project.py`, `src/maker_elegoo/ui.py`, `tests/test_performance.py`, `tests/test_project.py`, `tests/test_ui_beginner_flow.py`

- [x] Escrever testes TDD em `tests/test_performance.py` e `tests/test_project.py` cobrindo:
  - `_scan_models_paint_and_supports` otimizado mantendo detecção exata de `paint_color`/`paint_supports`;
  - `inspect_project(..., include_model_scan=False)` pulando XML pesado da malha mantendo placas/filamentos/objetos;
  - `_inspect_file` na UI rodando varredura pesada na thread em background via `inspect_queue` e atualizando projeto/slots quando finaliza;
  - Pollers `_poll_*` não ficando agendados continuamente em janela ociosa, mas funcionando imediatamente ao iniciar worker e limpando corretamente no `destroy()`;
  - Sem recriação redundante de widgets nem escrita síncrona repetida em disco em cliques rápidos.
- [x] Rodar testes e confirmar falhas esperadas (RED).
- [x] Implementar otimizações em `project.py` e `ui.py`, preservando todos os fluxos e testes existentes.
- [x] Medir tempos antes/depois em `Our+Lady+of+Guadalupe+Chibi.3mf` e UI, rodar toda a suíte `unittest` e registrar commit.

## Task 3 — Atualizador seguro via GitHub Releases + credencial DPAPI opcional (`updater.py`, `credentials.py`, `ui.py`)

**Files:** `src/maker_elegoo/updater.py`, `src/maker_elegoo/credentials.py`, `src/maker_elegoo/settings.py`, `src/maker_elegoo/ui.py`, `tests/test_updater.py`, `tests/test_credentials.py`

- [x] Escrever testes TDD em `tests/test_updater.py` cobrindo: comparação de versões (`v0.2.0 > 0.1.0`), parsing de release da API GitHub, erro claro em repo privado HTTP 404 com `exc.close()` (sem `ResourceWarning`), rejeição de URL não-HTTPS, falha fechada quando checksum SHA-256 estiver ausente ou inválido, e sucesso com checksum válido + comando de atualização silenciosa (`/VERYSILENT ...`).
- [x] Rodar `tests/test_updater.py` e confirmar falhas (RED).
- [x] Implementar `updater.py`, helpers de token GitHub via DPAPI (`credentials.py`), preferências (`update_repo`, `auto_check_updates` em `settings.py`), e comandos/menu na UI (`Verificar atualizações...`, `Configurar atualizações (GitHub)...`).
- [x] Rodar testes de updater, credenciais, configurações e UI (GREEN) e registrar commit.

## Task 4 — Build `--onedir`, Instalador Inno Setup 6, Checksums SHA-256, Verificação e Graphify

**Files:** `src/maker_elegoo/__init__.py`, `scripts/installer.iss`, `scripts/build.ps1`, `scripts/smoke_exe.py`, `scripts/publish_release.ps1`, `scripts/install.ps1`, `scripts/README-DISTRIBUTION.txt`, `docs/DEVELOPMENT.md`, `docs/validation/performance-installer-updater.md`

- [x] Atualizar versão (`__version__ = "0.2.0"` ou parametrizada em `__init__.py`) e criar `scripts/installer.iss` para Inno Setup 6 instalando o pacote `--onedir` em `%LOCALAPPDATA%\Programs\MakerElegoo`, com desinstalador nativo, Menu Iniciar, atalho no Desktop e suporte `/VERYSILENT` + relançamento opcional pós-update.
- [x] Atualizar `scripts/build.ps1` para gerar `--onedir` (`dist/MakerElegoo/MakerElegoo.exe`), `.zip` portátil `--onedir`, `dist/MakerElegoo-Setup-v<versao>.exe` via `ISCC.exe` e `dist/checksums-v<versao>.txt` (SHA-256); atualizar `scripts/smoke_exe.py` para validar o `--onedir` (e checar o instalador).
- [x] Adicionar `scripts/publish_release.ps1` para auxiliar criação de Releases via `gh`.
- [x] Rodar suíte completa (`python -W default -m unittest discover -s tests -v`), `.\scripts\build.ps1`, `python .\scripts\smoke_exe.py`, teste de instalação silenciosa em pasta temporária ou revisão do `.exe` gerado, `graphify update .`, conferência `git ls-files "*.3mf" "*.gcode"` vazia e registrar commit final.
