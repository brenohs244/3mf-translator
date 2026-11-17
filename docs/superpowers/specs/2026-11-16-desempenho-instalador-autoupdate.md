# Especificação — Desempenho da Interface, Instalador Windows (`--onedir`) e Atualização Automática

Data: 2026-11-16  
Projeto: Conversor MakerWorld → ELEGOO (`Centauri Carbon 2`)

## 1. Problema observado

1. **Engasgos severos na interface (especialmente em PCs como AMD Ryzen 5 2600X + 16 GB RAM):**
   - `profiles.py` (`list_profiles`, `resolve_profile`, `machine_family_names`) lê e faz `json.loads()` repetidamente de centenas de arquivos JSON em `%APPDATA%\ElegooSlicer` sem cache em memória.
   - Medições locais antes da correção:
     - `select_material_profile('PLA')` leu `_read_profile` **34.968 vezes** (`3.599,6 ms` no PC rápido).
     - `app._on_physical_filament_changed('PLA')` travou a UI por **`11.674,7 ms`**.
     - `app._inspect_file` em `.3mf` de 29 MB (`Our+Lady+of+Guadalupe+Chibi.3mf`, 166 MB XML) travou a UI por **`11.321,2 ms`** (`7.235,5 ms` só na varredura síncrona `obj_re` sobre XML da malha + recarga completa de processo e filamentos).
     - `build_conversion` em cada atualização do cartão pré-conversão releu **`1.286` JSONs (`153,6 ms`)** na thread principal.
   - 8 pollers `_poll_*` acordavam continuamente a thread Tkinter a cada `100–150 ms` mesmo quando ociosos, somado ao empacotamento `--onefile` que descompacta Tcl/Tk 9 e Python 3.15 em `%TEMP%` a cada execução.

2. **Distribuição e atualização manual em múltiplos PCs:**
   - Copiar `.exe` manualmente entre computadores é trabalhoso e o build `--onefile` agrava a lentidão na inicialização/Windows Defender.
   - O repositório remoto (`brenohs244/3mf-translator`) encontra-se **privado** no GitHub: chamadas anônimas à API de Releases retornam HTTP 404 sem token.

## 2. Objetivos e decisões de arquitetura

### A. Eliminação dos engasgos (Desempenho + Responsividade)

1. **Cache em memória de perfis e identidades (`profiles.py`, `material_selection.py`):**
   - Cache thread-safe (`threading.RLock`) por `(data_dir, kind)` para índices brutos `_candidate_index`, dicionários resolvidos por herança (`resolve_profile`), famílias de máquina (`machine_family_names`), listagens (`list_profiles`) e pares `(MaterialIdentity, tier)`.
   - Validação leve por assinatura de diretório/arquivos ou TTL curto + invalidação explícita (`clear_profile_cache()`), garantindo que testes unitários que alteram JSONs em disco continuem vendo mudanças sem leituras redundantes em loop.
   - Meta medida: reduzir leituras JSON de ~35.000 em `select_material_profile` e ~1.286 em `build_conversion` para **0 releituras em cache quente** (`< 10 ms`).

2. **Análise rápida síncrona + varredura pesada em background (`project.py`, `ui.py`):**
   - Em `project.py`: otimizar `_scan_models_paint_and_supports` (só executar regex `<object ...>` e `paint_color=` em chunks onde realmente existam esses marcadores) e adicionar parâmetro `include_model_scan: bool = True` em `inspect_project`.
   - Em `ui._inspect_file()`: ler metadados leves síncronos com `include_geometry=False, include_model_scan=False` (retorna em milissegundos, preservando contratos síncronos dos testes de UI e preenchendo placas/filamentos/objetos imediatamente), e executar tanto `analyze_project_geometry` quanto a varredura pesada de `3D/*.model` (`paint_color`/`paint_supports`) na thread em segundo plano via `inspect_queue`.
   - Em `_refresh_profiles()` e `_refresh_dependents()`: evitar chamar `list_profiles("machine", ...)` duas vezes e evitar reconstruir combos/perfis quando `install`, bico e máquina não mudaram.

3. **Pollers sob demanda e redução de relayout (`ui.py`):**
   - Ativar cada poller (`_poll_worker`, `_poll_ai`, `_poll_professor`, `_poll_orientation`, `_poll_comparison`, `_poll_inspect`, `_poll_preview`, `_poll_calib`) **apenas quando houver tarefa em execução** (desligando automaticamente quando a fila estiver vazia e sem worker pendente; mantendo compatibilidade com chamadas diretas nos testes).
   - Evitar recriação redundante dos widgets em `_render_section2_slots` quando o conjunto de slots/estados exibidos não mudou, aplicar debounce leve (`250 ms`) na gravação em disco de `_save_preferences` (com flush garantido em `destroy()`) e atualizar `wraplength` no evento `<Configure>` apenas quando a largura mudar mais que 8 px.

### B. Instalador Windows rápido (`--onedir` + Inno Setup 6)

1. **Empacotamento `--onedir` (`scripts/build.ps1`, `scripts/installer.iss`, `scripts/smoke_exe.py`):**
   - Gerar pasta `--onedir` (`dist/MakerElegoo/MakerElegoo.exe` + `_internal/`) eliminando a extração para `%TEMP%` em toda abertura.
   - Manter compatibilidade opcional (`-IncludeOneFile` ou geração do `.zip` portátil da pasta `--onedir`).
   - Compilar instalador nativo Windows via **Inno Setup 6 (`ISCC.exe`)**:
     - Arquivo: `dist/MakerElegoo-Setup-v<versao>.exe`.
     - Instalação por usuário em `%LOCALAPPDATA%\Programs\MakerElegoo` (sem exigir UAC/administrador), entrada padrão em "Programas instalados / Desinstalar" (`unins000.exe`), atalho no Menu Iniciar e opção de atalho na Área de Trabalho (marcada por padrão).
     - Suporte completo a execução silenciosa (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS`) e relançamento pós-instalação para auto-update.

### C. Atualização automática via GitHub Releases (`src/maker_elegoo/updater.py`, `credentials.py`, `ui.py`)

1. **Fonte de atualização e segurança:**
   - Repositório configurável (`MAKER_ELEGOO_UPDATE_REPO`, preferência `update_repo` na UI; padrão `brenohs244/3mf-translator`), apontando opcionalmente para um repositório público dedicado apenas às Releases (mantendo o código-fonte privado, caso desejado) ou usando token GitHub read-only armazenado criptografado via Windows DPAPI (`save_github_token`/`get_github_token`/`clear_github_token` em `credentials.py`, `GITHUB_TOKEN` env var ou fallback opcional para `gh auth token` CLI).
   - Apenas URLs HTTPS (`https://api.github.com/...` e `https://github.com/...` / `objects.githubusercontent.com`).
   - **Verificação criptográfica obrigatória:** baixar asset de instalador (`MakerElegoo-Setup-*.exe`) **e** manifesto `checksums-*.txt` da mesma Release; calcular SHA-256 local do instalador e **recusar executar** se o checksum não existir ou divergir.
   - Fechar `HTTPError.close()` em erros HTTP (zero `ResourceWarning`). Informar claramente em português caso o repo esteja privado sem token (HTTP 404), sem internet ou sem releases publicadas.

2. **Experiência na UI:**
   - Novo item em `Ferramentas`: **`Verificar atualizações...`** e **`Configurar atualizações (GitHub)`** + exibição da versão atual (`__version__`) no título/rodapé ou janela de atualização.
   - Checagem assíncrona discreta na inicialização (pode ser habilitada/desabilitada nas preferências) que apenas notifica na barra de status caso haja versão mais nova — **nunca baixa nem reinicia o app sem consentimento explícito do usuário**.
   - Script auxiliar `scripts/publish_release.ps1` para gerar build, checksums SHA-256 e publicar Release no GitHub via `gh release create`.

## 3. Critérios de aceitação

1. Suíte `unittest` completa verde (`0` falhas, `0` skips, `0` `ResourceWarning`, `0` callbacks Tcl inválidos).
2. Testes de regressão de desempenho provando redução drástica de leituras JSON em cache quente (`select_material_profile`, `build_conversion`) e não-bloqueio da UI na varredura pesada de `.3mf` e pollers ociosos zerados em repouso.
3. Benchmark antes/depois medido em `Our+Lady+of+Guadalupe+Chibi.3mf` e `select_material_profile('PLA')` documentado.
4. Build completo via `.\scripts\build.ps1` produzindo `dist/MakerElegoo/` (`--onedir`), `dist/MakerElegoo-Setup-v<versao>.exe`, `dist/checksums-v<versao>.txt`, `dist/MakerElegoo-Windows-Portable.zip` e passando em `python .\scripts\smoke_exe.py`.
5. `graphify update .` executado ao final e nenhum `.3mf`/`.gcode`/token embutido no Git ou nos binários.
