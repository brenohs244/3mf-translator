# Local ELEGOO Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Descobrir e selecionar automaticamente os perfis locais da Centauri Carbon 2 em cada computador.

**Architecture:** A descoberta lê os JSON de sistema e usuário no AppData local e resolve a herança antes de filtrar. A interface oferece máquinas locais e usa a máquina selecionada para listar perfis compatíveis e converter.

**Tech Stack:** Python, Tkinter, unittest, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-09-local-profiles-design.md`

## Global Constraints

- Nenhum perfil do arquivo de referência entra no executável ou no Git.
- Nenhum 3MF do usuário entra no Git ou em serviços de IA.
- Sucesso de conversão continua exigindo fatiamento real.

## Review Focus

- Perfil personalizado sem `nozzle_diameter` próprio usa o diâmetro herdado.
- Perfil de processo com nome arbitrário usa compatibilidade herdada.
- Máquina personalizada pode usar processo compatível com sua máquina ancestral.
- Perfis de outro modelo ou bico não aparecem na seleção errada.
- Contas de usuário fora de `default` também são descobertas.

---

### Task 1: Descoberta e compatibilidade local

**Files:** `src/maker_elegoo/profiles.py`, `tests/test_profiles.py`.

- [ ] Escrever testes de descoberta, herança, bico e compatibilidade e confirmar falha.
- [ ] Implementar descoberta dos diretórios locais e filtros por dados resolvidos.
- [ ] Rodar testes de perfil até passar.

### Task 2: Seleção de máquina na interface e conversão

**Files:** `src/maker_elegoo/ui.py`, `src/maker_elegoo/mapping.py`, `tests/test_mapping.py`.

- [ ] Escrever teste que aceite máquina personalizada com processo compatível com a máquina ancestral e confirmar falha.
- [ ] Exibir máquinas e bicos locais; usar a máquina selecionada ao converter.
- [ ] Rodar suíte completa.

### Task 3: Distribuição

**Files:** `docs/DEVELOPMENT.md`, `scripts/README-DISTRIBUTION.txt`.

- [ ] Documentar descoberta local e ausência de perfis embutidos.
- [ ] Atualizar Graphify e Understand Anything conforme instruções do projeto.
- [ ] Recompilar, verificar ZIP e executar smoke test do executável.
