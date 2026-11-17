# Validação — Desempenho, Instalador (`--onedir`) e Atualização Automática (`v0.2.0`)

Data: 2026-11-16  
Especificação: [2026-11-16-desempenho-instalador-autoupdate.md](../superpowers/specs/2026-11-16-desempenho-instalador-autoupdate.md)  
Plano: [2026-11-16-desempenho-instalador-autoupdate.md](../superpowers/plans/2026-11-16-desempenho-instalador-autoupdate.md)

## 1. Comparativo de desempenho medido (antes vs. depois)

Medições executadas localmente sobre a instalação real do ELEGOO Slicer (`%APPDATA%\ElegooSlicer`: 115 máquinas, 310 processos, 743 filamentos) e projeto `Our+Lady+of+Guadalupe+Chibi.3mf` (29 MB / ~166 MB XML descomprimido):

| Operação | Antes (sem cache / síncrono) | Depois (cache + background + sob demanda) |
| :--- | :--- | :--- |
| `list_profiles("machine", "0.4")` | `443,8 ms` (`230` leituras JSON) | `19,85 ms` (`115` leituras na 1ª carga) |
| `list_profiles("process", "0.4")` | `1.266,4 ms` (`735` leituras JSON) | `53,80 ms` (`310` leituras na 1ª carga) |
| `list_profiles("filament", "0.4")` | `3.517,5 ms` (`1.601` leituras JSON) | `109,85 ms` (`743` na 1ª carga) · `36,04 ms` (`0` leituras em cache) |
| `select_material_profile("PLA")` | `3.599,6 ms` (**`34.968`** leituras JSON) | **`13,67 ms`** (`0` leituras JSON) |
| `build_conversion(...)` | `153,6 ms` (`1.286` leituras JSON) | **`7,09 ms`** (`0` leituras JSON) |
| `app._inspect_file` (29 MB 3MF) | **`11.321,2 ms`** travado na UI | **`19,8–25,1 ms`** na UI (varredura pesada em background) |
| `app._on_physical_filament_changed("PLA")` | **`11.674,7 ms`** travado na UI | **`23,8 ms`** isolado (`892,9 ms` concorrendo com unzip 166 MB em background) |
| Timers ociosos na janela parada | 8 pollers a cada `100–150 ms` | **`0`** timers em repouso (`_begin_poll` sob demanda) |

## 2. Instalador Windows (`--onedir`) e auto-update

- **Empacotamento (`.\scripts\build.ps1`):**
  - Bundle `--onedir`: `dist/MakerElegoo/MakerElegoo.exe` + `_internal/` (abertura no `smoke_exe.py`: **`1.14 s`** sem extração em `%TEMP%`).
  - Instalador Windows: `dist/MakerElegoo-Setup-v0.2.0.exe` (`13.354.347` bytes, Inno Setup `6.7.3`, instala por usuário em `%LOCALAPPDATA%\Programs\MakerElegoo` sem exigir UAC, com atalhos e desinstalador `unins000.exe`).
  - Pacote ZIP portátil: `dist/MakerElegoo-Windows-Portable.zip` (`14.935.231` bytes).
  - Manifesto SHA-256: `dist/checksums-v0.2.0.txt`.
- **Teste de instalação e desinstalação silenciosa:**
  - `MakerElegoo-Setup-v0.2.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR=%TEMP%\maker-elegoo-setup-smoke` → **`ExitCode 0`** (`MakerElegoo.exe`, `_internal`, `unins000.exe` verificados).
  - `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` → **`ExitCode 0`**.
- **Atualizador (`src/maker_elegoo/updater.py` + `ui.py`):**
  - Menus: `Ferramentas → Verificar atualizações...` e `Ferramentas → Configurar atualizações (GitHub)...`.
  - Aceita apenas HTTPS, valida manifesto SHA-256 antes de lançar `/VERYSILENT /NORESTART /CLOSEAPPLICATIONS`, fecha `HTTPError.close()` (0 `ResourceWarning`) e suporta Token GitHub salvo com Windows DPAPI ou repositório público dedicado a Releases.

## 3. Pendências operacionais (dependem de ação do usuário no GitHub / outro PC)

- [ ] Enviar commits (`git push`) e publicar a primeira Release com `.\scripts\publish_release.ps1` (atualmente `brenohs244/3mf-translator` é privado e não possui Releases publicadas).
- [ ] Instalar `MakerElegoo-Setup-v0.2.0.exe` no PC Ryzen 5 2600X e validar fluidez de uso na máquina alvo.
- [ ] Se optar por manter `brenohs244/3mf-translator` privado sem colocar token no outro PC, configurar um repositório público só de Releases (ou informar token read-only em `Ferramentas → Configurar atualizações (GitHub)...`).
