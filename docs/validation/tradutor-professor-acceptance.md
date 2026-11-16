# Aceitação Técnica — Evolução Tradutor + Professor (Elegoo Centauri Carbon 2)

Data de execução: 2026-11-15  
Especificação de referência: [2026-11-15-avaliacao-produto-tradutor-professor.md](../superpowers/specs/2026-11-15-avaliacao-produto-tradutor-professor.md)  
Plano de referência: [2026-11-15-evolucao-produto-tradutor-professor.md](../superpowers/plans/2026-11-15-evolucao-produto-tradutor-professor.md)

## 1. Escopo e regra de honestidade

- Impressora alvo única validada neste marco: **Elegoo Centauri Carbon 2 (bico 0,4 mm, câmara passiva `support_chamber_temp_control = 0`)**.
- O fatiamento real via `elegoo-slicer.exe` valida **exportação de 3MF, geração de G-code por placa, integridade geométrica e estimativas do fatiador (tempo e gramas)**.
- Testes unitários e fatiamento em CLI **não comprovam** resistência mecânica final, solda entre camadas, temperatura real de câmara passiva, ausência de warping, folga real após resfriamento nem facilidade visual de remoção de suportes. Esses pontos seguem explicitamente pendentes de revisão visual no ELEGOO Slicer e impressão física.

## 2. Correções de encerramento e avisos na Etapa 6

- **Bug reproduzido e corrigido (`ui.py`):** chamadas concorrentes/manuais aos pollers `_poll_*` sobrescreviam os handles `self.*_after` sem cancelar o timer anterior, deixando callbacks `_poll_worker` órfãos em Tcl após `destroy()`, emitindo `invalid command name "..._poll_worker"` quando outro event loop (`app.update()`) rodava na sequência.
  - Corrigido com `_POLL_HANDLE_ATTRS`, `_should_stop_polling()`, `_schedule_poll()` (cancela handle anterior antes de reagendar e respeita `_closing`), proteção no callback assíncrono de `_configure_gemini_key` e guarda em todos os 8 pollers + `destroy()`.
  - Teste de regressão adicionado: `tests/test_ui_beginner_flow.py::UIBeginnerFlowTests::test_task6_close_teardown_cancels_all_pollers_without_invalid_command_or_worker_crash` (validado antes em RED falhando `24 <= 8` e em GREEN com 0 ocorrências de `invalid command name`).
- **`ResourceWarning` investigado e corrigido (`ai.py`, `ai_client.py`):** no Python 3.15.1, `urllib.error.HTTPError(..., None)` instancia wrapper temporário que emite `ResourceWarning: Implicitly cleaning up <HTTPError 429: 'Quota'>` durante o GC se não fechado.
  - Adicionado `exc.close()` antes de relançar exceções tratadas nos 3 handlers `except error.HTTPError` em `src/maker_elegoo/ai.py` e `src/maker_elegoo/ai_client.py`.
  - Regressão adicionada em `tests/test_ai_client.py::AIClientTest::test_gemini_test_connection_and_429_status_and_layer_limits` (verificado RED com 1 `ResourceWarning` e GREEN com 0).

## 3. Suíte automatizada de testes

- Comando executado:
  ```powershell
  $env:PYTHONPATH='src'; python -W default -m unittest discover -s tests -v
  $env:PYTHONPATH='src'; python -W error::ResourceWarning -m unittest discover -s tests -q
  ```
- Resultado observado: **`Ran 173 tests in 6.842s — OK`** (`0 failures`, `0 errors`, `0 skips`, `0 invalid command name`, `0 warnings`).
- Teste programático de viewport e DPI em `test_task4_...`: `1366x768` com `tk scaling` em `1.0` (100%) e `1.5` (150%), `main_canvas` presente, quebra de texto (`wraplength > 300`) e foco sequencial por teclado (`tk_focusNext`).

## 4. Fatiamento real com amostras locais no ELEGOO Slicer (sem upload)

- **Slicer utilizado:** `C:\Program Files\ElegooSlicer\elegoo-slicer.exe` (versão PE `FileVersion` / `ProductVersion`: **`1.5.3.5`**; nota: `--version` retorna `Invalid option --version` nessa CLI).
- **Máquina base:** `Elegoo Centauri Carbon 2 0.4 nozzle`.
- **Saídas temporárias (fora do Git):** `%TEMP%\maker-elegoo-acceptance\`. Nenhum `.3mf` ou `.gcode` entrou no repositório (`git ls-files "*.3mf" "*.gcode"` vazio).

| Cenário | Arquivo local (origem) | Perfil de processo e filamento(s) | Principais ajustes aplicados | Integridade da geometria | Placas / Resultado CLI | Estimativa total (por placa) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Decorativa PLA** | `Our+Lady+of+Guadalupe+Chibi.3mf` (`Bambu Lab H2C`, `0.16`) | `0.16mm Optimal @Elegoo CC2 0.4 nozzle` + `Elegoo PLA @ECC2` | `layer_height=0.12`, `wall_loops=3`, `outer_wall_speed=60`, `inner_wall_speed=120`, `top_surface_speed=100`, `seam_position=back`, suportes `Z=0.24 / XY=0.5 / interface 3 camadas / 0.3 mm`, bico `210 °C`, mesa `60 °C`, fan `50–100%`, AUX `0%` | `unchanged=True` | **1/1 aprovada** (`Todas as placas foram fatiadas`) | **11271 s** (~3h08m) · **31.23 g** (Placa 1: `11271 s`, `31.23 g`) |
| **2. Funcional PLA → ABS** | `Projekt+standard++-++small+(up+to+11,55mm+thickness).3mf` (`Bambu Lab X1 Carbon`, `0.2`) | `0.20mm Standard @Elegoo CC2 0.4 nozzle` + `Elegoo ABS @ECC2` | `wall_loops=5`, `sparse_infill_density=30%`, `sparse_infill_pattern=gyroid`, `brim_type=outer_only`, `outer_wall_speed=100`, `fan_max_speed=25%`, `overhang_fan_speed=40%`, `close_fan_the_first_x_layers=3`, `slow_down_layer_time=6 s`, bico `270 °C`, mesa `90 °C`; alertas de câmara passiva, carga vs camadas e UV/sol em ABS | `unchanged=True` | **1/1 aprovada** | **3671 s** (~1h01m) · **19.92 g** (Placa 1: `3671 s`, `19.92 g`) |
| **3. Encaixes / tampa-base ABS multiplacas** *(nota 1)* | `Lip+stick+case+-+keychain.3mf` (`Bambu Lab A1`, `0.16`, pasta local `Downloads`) | `0.16mm Optimal @Elegoo CC2 0.4 nozzle` + `Elegoo ABS @ECC2` | `brim_type=no_brim`, `elefant_foot_compensation=0.15`, `wall_loops=3`, `sparse_infill_density=20%` `gyroid`, `outer_wall_speed=80`, `fan_max_speed=35%`, `overhang_fan_speed=55%`, `close_fan_the_first_x_layers=3`, `slow_down_layer_time=6 s`, `support_style=tree_slim`, bico `270 °C`, mesa `90 °C` | `unchanged=True` | **3/3 aprovadas** | **19751 s** (~5h29m) · **84.15 g** (P1: `6380 s` / `28.15 g`; P2: `6387 s` / `27.71 g`; P3: `6984 s` / `28.29 g`) |
| **4. Multisslot PETG + TPU (multiplacas)** | `Gardena_quick_connectors.3mf` (`Bambu Lab P1S`, `0.12`) | `0.12mm Fine @Elegoo CC2 0.4 nozzle` + S1 `Elegoo PETG @ECC2`, S2 `Elegoo TPU 95A @ECC2` | `brim_type=no_brim`, `elefant_foot_compensation=0.15`, `outer_wall_speed=80`, `seam_position=back`, `support_style=tree_slim` (`Z=0.24 / XY=0.6`), alerta de polímeros incompatíveis nos slots + alertas específicos PETG/TPU | `unchanged=True` | **2/2 aprovadas** | **45651 s** (~12h41m) · **125.62 g** (P1 PETG: `44782 s` / `122.84 g`; P2 TPU: `869 s` / `2.78 g`) |
| **5. Multiplacas 4 slots PLA multicolor** | `PANETONE+PAPAI+NOEL+OK+CONFIG+OK+A1+sem+ams+com+pausa+.3mf` (`Elegoo Centauri Carbon 2`, `0.2`) | `0.20mm Standard @Elegoo CC2 0.4 nozzle` + 4× `Elegoo PLA @ECC2` | `support_object_xy_distance=0.5`, `support_interface_top_layers=3`, `support_interface_spacing=0.3`, alerta de suporte por objeto e lição sobre limitação global de vários objetos | `unchanged=True` | **3/3 aprovadas** | **20752 s** (~5h46m) · **225.30 g** (P1: `5605 s` / `50.90 g`; P2: `14275 s` / `168.83 g`; P3: `872 s` / `5.57 g`) |

> *(Nota 1 — Cenário 3):* A amostra local utilizada (`Lip+stick+case+-+keychain.3mf`) representa peças com tampa, encaixes justos e múltiplos corpos distribuídos em 3 placas avaliadas sob objetivo `moveis` + `encaixe_justo` em ABS. Nenhuma amostra `.3mf` local do tipo dobradiça monolítica *print-in-place* estava em disco para fatiamento em ABS; as regras dessa classe (`chaveiro_articulado` / `partes_moveis`) foram cobertas por testes unitários dedicados e continuam dependendo de conferência visual de folga e impressão física.

### Comparação real de objetivos no Cenário 2 (`compare_objectives`)

Executada sobre o mesmo projeto e perfil base do Cenário 2 (`0.20mm Standard`, `Elegoo ABS @ECC2`, objetivo `esforco` / `equilibrio` / `flexao_lateral` / `calor_sol`):

- **`original`:** `2457 s` (~41 min) · `14.77 g` (`success=True`, `recommendable=True`)
- **`qualidade` (`layer_height=0.16`, `wall_loops=5`, `fan_max_speed=25%`):** `4712 s` (~1h19m) · `20.25 g` (`success=True`, `recommendable=True`)
- **`velocidade` (`layer_height=0.24`, piso estrutural mantido `wall_loops=5`, `sparse_infill_density=30%`, `fan_max_speed=25%`):** `3077 s` (~52 min) · `19.75 g` (`success=True`, `recommendable=True`)
- **`equilibrio` (`layer_height=0.20`, `wall_loops=5`, `sparse_infill_density=30%`, `fan_max_speed=25%`):** `3666 s` (~1h02m) · `19.91 g` (`success=True`, `recommendable=True`)
- **`economia` (`layer_height=0.20`, `wall_loops=5`, `sparse_infill_density=30%`, `fan_max_speed=25%`):** `3669 s` (~1h02m) · `19.92 g` (`success=True`, `recommendable=True`) — corretamente sinalizada pelo sistema como **parâmetros efetivos idênticos à alternativa `equilibrio` pelas restrições de perfil/política**.

## 5. Build, smoke e grafos de código

- **`.\scripts\build.ps1`:** concluído (`PyInstaller 6.22.3`, `Python 3.15.1`), gerou `dist/MakerElegoo.exe` e `dist/MakerElegoo-Windows.zip`.
- **`python .\scripts\smoke_exe.py`:** passou (`Janela principal abriu com sucesso.`).
- **Graphify (`graphify update .`):** concluído após alterações de código (`Rebuilt: 1170 nodes, 3860 edges, 66 communities`).

## 6. Itens ainda pendentes (não marcados como concluídos)

- [ ] **Inspeção visual interativa no ELEGOO Slicer:** abrir as 5 exportações geradas em `%TEMP%\maker-elegoo-acceptance\*_ELEGOO.3mf` na GUI do ELEGOO Slicer e conferir camada a camada suportes, interface, costura, associação visual de cores nos 4 slots/multisslot, folgas e ausência de colisão antes de imprimir.
- [ ] **Impressão física e ensaios na Centauri Carbon 2:** validar aderência, ausência de warping em ABS (câmara passiva), encaixes/folgas após resfriamento, facilidade de remoção dos suportes e resistência mecânica sob carga real (especialmente em Eixo Z).
- [ ] **Teste de usabilidade com 3 usuários iniciantes reais:** executar o protocolo com 3 iniciantes sem instrução prévia sobre nomes de perfil e registrar dúvidas, desistências e compreensão entre "fatiou" e "resistência testada".
- [ ] **Understand Anything:** executar `/understand --language pt-BR` no ambiente interativo do assistente caso deseje atualizar `.ua/knowledge-graph.json` para esta revisão final.
