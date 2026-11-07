# Conversor MakerWorld para ELEGOO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar um aplicativo Windows que lê projetos 3MF do MakerWorld, permite selecionar perfis instalados da Centauri Carbon 2, exporta um projeto ELEGOO, fatia todas as placas para validar e relata adaptações e sugestões opcionais de IA.

**Architecture:** Núcleo Python sem dependências de interface lê 3MF e perfis JSON; um adaptador executa o ELEGOO Slicer pela linha de comando para exportar e validar o projeto. Uma interface Tkinter controla a seleção e exibe o relatório. A IA Gemini só sugere equivalências sujeitas a validação e confirmação.

**Tech Stack:** Python 3.15, biblioteca padrão (tkinter, zipfile, ElementTree, json, pathlib, subprocess, urllib), unittest; PyInstaller para distribuição; Graphify Local e Understand Anything para grafos do repositório.

**Spec:** `docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md`

## Global Constraints

- Windows primeiro; não exigir Bambu Studio nem login MakerWorld.
- Ler perfis da instalação do ELEGOO Slicer e perfis do usuário; suportar bicos 0,2, 0,4 e 0,8 mm da Centauri Carbon 2.
- Nunca sobrescrever o 3MF original, os perfis instalados ou enviar G-code à impressora.
- Marcar sucesso apenas depois de validar a estrutura do arquivo e fatiar todas as placas com o ELEGOO Slicer.
- IA opcional, desligada por padrão; não enviar 3MF/malha; sugestões exigem confirmação e validação por chaves e faixas.
- Tratar PLA, PETG e ABS e permitir um perfil de material por filamento do projeto.
- Código e relatórios em português; funções de integração pequenas, com interfaces testáveis.

## Review Focus

- 3MF inválido ou ZIP hostil: recusar arquivo com entradas duplicadas, caminhos relativos perigosos ou tamanho descompactado excessivo; teste em Task 2.
- Projeto com múltiplos filamentos/placas: manter associação por posição e validar todas as placas; testes em Tasks 2, 4 e 5.
- Perfil herdado ausente ou ciclo de herança: mostrar erro claro, sem carregar configuração incompleta; teste em Task 3.
- Falha/timeout de CLI: resultado não pode receber status de sucesso se apenas o processo terminou sem artefatos; teste em Task 5.
- Sugestão IA inventada ou perigosa: só aceitar chave existente, valor válido e escopo permitido; teste em Task 7.

---

### Task 1: Repositório e execução básica

**Files:** `pyproject.toml`, `.gitignore`, `README.md`, `src/maker_elegoo/__init__.py`, `src/maker_elegoo/__main__.py`, `tests/test_smoke.py`, `AGENTS.md`.

**Interfaces:** `python -m maker_elegoo` abre a interface; `python -m unittest discover -s tests` roda testes.

- [ ] Criar teste de importação e chamada da função `main()` injetando um launcher falso.
- [ ] Rodar teste e confirmar falha inicial.
- [ ] Inicializar Git, criar estrutura `src`, configuração de pacote, ignores de artefatos, README e AGENTS.md com fluxo Superpowers/Graphify/Understand Anything.
- [ ] Implementar entrada mínima e rodar teste até passar.
- [ ] Commit: `chore: initialize maker elegoo project`.

### Task 2: Leitura segura de 3MF

**Files:** `src/maker_elegoo/project.py`, `tests/test_project.py`.

**Interfaces:** `inspect_project(path: Path) -> ProjectInfo`; `ProjectInfo` contém `source_settings`, `filaments`, `plates`, `objects`, `archive_entries` e `warnings`.

- [ ] Escrever testes com 3MF mínimo, ZIP inválido, caminho perigoso, entrada duplicada, arrays de dois filamentos e três placas.
- [ ] Confirmar falhas iniciais.
- [ ] Implementar validação ZIP, leitura JSON/XML, inspeção de filamentos, placas e objetos; limitar recursos descompactados.
- [ ] Rodar testes e inspecionar os três exemplos reais, registrando contagens sem modificar os arquivos.
- [ ] Commit: `feat: inspect 3mf projects safely`.

### Task 3: Descoberta e resolução de perfis ELEGOO

**Files:** `src/maker_elegoo/profiles.py`, `tests/test_profiles.py`.

**Interfaces:** `discover_slicer() -> SlicerInstall`; `list_profiles(install, kind, nozzle) -> list[Profile]`; `resolve_profile(profile, install) -> dict`.

- [ ] Testar detecção de instalação fictícia, seleção por bico, perfil do usuário, herança, pai ausente e ciclo.
- [ ] Confirmar falhas iniciais.
- [ ] Implementar leitura dos diretórios de perfil do app e `%APPDATA%`, herança sem executar código, tipos de perfil e compatibilidade com Centauri Carbon 2.
- [ ] Rodar testes e conferir perfis reais deste PC para 0,2, 0,4 e 0,8 mm.
- [ ] Commit: `feat: discover elegoo profiles`.

### Task 4: Mapeamento e análise de material

**Files:** `src/maker_elegoo/mapping.py`, `src/maker_elegoo/materials.py`, `tests/test_mapping.py`, `tests/test_materials.py`.

**Interfaces:** `build_conversion(source: ProjectInfo, machine: Profile, process: Profile, filaments: list[Profile]) -> ConversionPlan`; `analyze_material_change(source: ProjectInfo, target_filaments: list[Profile]) -> list[Finding]`.

- [ ] Testar associação posicional de filamentos, chaves compartilhadas, prioridade de limites ELEGOO e diferenças PLA/PETG/ABS em temperatura, mesa, ventoinha e vazão.
- [ ] Confirmar falhas iniciais.
- [ ] Implementar lista explícita de parâmetros de processo transferíveis, relatório de chaves sem mapeamento e análise material sem prometer desempenho mecânico.
- [ ] Rodar testes e gerar relatório de prévia para os exemplos reais.
- [ ] Commit: `feat: plan profile and material conversion`.

### Task 5: Exportação e validação pelo ELEGOO Slicer

**Files:** `src/maker_elegoo/slicer.py`, `src/maker_elegoo/converter.py`, `tests/test_slicer.py`, `tests/test_converter.py`.

**Interfaces:** `SlicerCLI.export(source, plan, destination) -> ExportResult`; `SlicerCLI.validate(destination, plate_count) -> ValidationResult`; `convert_project(...) -> ConversionResult`.

- [ ] Testar composição de argumentos sem shell, arquivo de saída ausente, timeout, código de erro, múltiplas placas e comparação estrutural da geometria.
- [ ] Confirmar falhas iniciais.
- [ ] Verificar a CLI real (`--load-settings`, `--load-filaments`, `--export-3mf`, `--slice`) com cópias temporárias dos 3MF; definir os argumentos exatos pelo resultado observado.
- [ ] Implementar presets resolvidos em arquivos temporários, exportação para novo nome, fatiamento de todas as placas, coleta de avisos e relatório de fidelidade.
- [ ] Rodar testes, executar conversão de ao menos um projeto Bambu real e abrir o resultado no ELEGOO Slicer. Se a CLI desta versão não suportar o fluxo, registrar evidência e revisar o adaptador sem declarar sucesso indevido.
- [ ] Commit: `feat: export and validate converted projects`.

### Task 6: Interface desktop e configuração local

**Files:** `src/maker_elegoo/ui.py`, `src/maker_elegoo/settings.py`, `src/maker_elegoo/__main__.py`, `tests/test_settings.py`.

**Interfaces:** `launch_app()`; UI escolhe 3MF, bico, processo e perfil por filamento, mostra prévia, validação e botão para abrir no ELEGOO Slicer.

- [ ] Testar persistência de preferências locais e caminhos não encontrados.
- [ ] Confirmar falhas iniciais.
- [ ] Implementar Tkinter com tarefas longas em thread, atualização segura da UI e erros legíveis; não armazenar API key em texto simples nas preferências.
- [ ] Rodar testes e fazer uma inspeção manual da janela em resolução comum.
- [ ] Commit: `feat: add desktop conversion workflow`.

### Task 7: Análise opcional com Gemini

**Files:** `src/maker_elegoo/ai.py`, `src/maker_elegoo/ui.py`, `tests/test_ai.py`.

**Interfaces:** `suggest_equivalences(unmapped, elegoo_keys, context, api_key) -> list[Suggestion]`; `validate_suggestion(suggestion, schema) -> bool`.

- [ ] Testar corpo de requisição sem geometria, resposta JSON válida, chaves inexistentes, valores fora de faixa, G-code livre e erro de cota/rede.
- [ ] Confirmar falhas iniciais.
- [ ] Implementar cliente HTTPS Gemini por `urllib` com modelo configurável e saída JSON estrita; UI mostra sugestões e exige escolha explícita antes da exportação.
- [ ] Rodar testes com servidor falso; chamada real apenas se usuário fornecer chave.
- [ ] Commit: `feat: add optional ai mapping review`.

### Task 8: Distribuição e grafos de manutenção

**Files:** `scripts/build.ps1`, `docs/DEVELOPMENT.md`, `.gitignore`, `.agents/skills/graphify/*` (se instalado pelo CLI), `.ua/*` e `graphify-out/*` conforme política de artefatos.

**Interfaces:** `scripts/build.ps1` produz executável Windows; Graphify e Understand Anything documentados e executados no código implementado.

- [ ] Criar script de build reproduzível com PyInstaller e testar o executável fora do diretório fonte.
- [ ] Instalar Graphify Local com pacote oficial `graphifyy` no escopo do projeto, gerar grafo e registrar comando de atualização.
- [ ] Executar Understand Anything no repositório, gerar grafo de arquitetura e registrar como atualizar e visualizar.
- [ ] Rodar suíte, compilação/importação e conversão real novamente; documentar limites observados e instruções de instalação em outro Windows.
- [ ] Commit: `build: package app and document development graphs`.

## Self-review

- O plano cobre descoberta de perfis, material por filamento, exportação, fatiamento automático, IA opcional, distribuição e ferramentas de desenvolvimento.
- A compatibilidade de pintura/suportes/G-code por camada depende de testes com amostras; cada perda deve aparecer no relatório.
- Se a CLI ELEGOO não conseguir exportar/fatiar, o aplicativo não poderá marcar sucesso até existir um caminho validado.
