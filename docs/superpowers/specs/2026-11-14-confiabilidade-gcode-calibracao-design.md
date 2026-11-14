# Design Spec: 5 Camadas Extras de Confiabilidade (Auditoria de G-code, Calibração, Pré-Aquecimento Passivo, Pescoços/Carga e Prévia Visual)

**Data:** 2026-11-14  
**Escopo:** Melhorias técnicas pós-v2 para aumentar a previsibilidade prática na ELEGOO Centauri Carbon 2 sem prometer o que o software não pode medir fisicamente.  
**Princípio central:** Todo `.3mf` e `.gcode` permanece local e fora do Git/IA; nenhuma garantia não medida é apresentada como fato.

---

## 1. Melhoria 1 — Auditoria Profunda do G-code Real (`gcode_audit.py` + `slicer.py`)
O `SlicerCLI.validate()` passa a auditar cada `plate_*.gcode` gerado antes de remover a pasta temporária:
- **Dados extraídos (`PlateGcodeAudit`):**
  - Contagem de camadas (`layer_count`).
  - Temperaturas comandadas reais (`M104`/`M109` para bico, `M140`/`M190` para mesa).
  - Ventoinhas comandadas (`M106 P0` peça, `P2` auxiliar, `P3` exaustor; `M107` desligado).
  - Detecção explícita de pré-aquecimento passivo (`G4 S<sec>` / `G4 P<ms>` >= 30 s).
  - Vazão volumétrica máxima estimada em `mm³/s` a partir de extrusão `dE`, seção do filamento (`1,75 mm` padrão) e avanço `F`.
  - Menor tempo de camada estimada a partir da camada 2 (`min_layer_time_s`) e quantidade de camadas curtas (`< 6 s`).
  - Velocidade máxima de impressão e saltos bruscos de velocidade (`>= 120 mm/s` entre segmentos/tipos adjacentes).
  - Caixa envolvente da 1ª camada, contagem de ilhas separadas (`layer1_island_count`) e segmentos amostrados para prévia local.
- **Evidência:** Apresentado em **Verificado no G-code real / Verificado pelo fatiamento**, com alertas práticos quando a vazão ultrapassar `filament_max_volumetric_speed`, houver camadas curtas críticas ou ventoinha alta de peça em ABS/ASA.

## 2. Melhoria 2 — Peça Rápida de Calibração + Contração & Folga Medida (`calibration.py` + `history.py`)
- **Gerador paramétrico offline:** `export_calibration_3mf()` cria uma malha 3MF minimalista e fechada (barra nominal de `50,00 mm × 12,00 mm × 4,00 mm` + pinos/ranhuras de folga `0,15 / 0,20 / 0,30 mm`), exportada e validada com o perfil selecionado de bico, processo e filamento da CC2.
- **Histórico com calibração física:** `FeedbackRecord` ganha campos opcionais com defaults seguros (`filament_brand`, `profile_name`, `measured_bar_mm`, `fitted_clearance_mm`).
- **Aplicação honesta:** `compute_shrinkage_stats()` calcula contração observada `(1 - medido/50) * 100` e `filament_shrink` correspondente (`(medido/50) * 100%`, ex.: `49,70 mm` → `99.4%`). O Professor sugere ajuste somente quando existir medição salva para o polímero/marca correspondente.

## 3. Melhoria 3 — Pré-Aquecimento Passivo Opcional para ABS/ASA (`professor.py` + `slicer.py`)
- Na ELEGOO Centauri Carbon 2 (`support_chamber_temp_control = "0"`), não há aquecedor ativo de câmara.
- Quando o destino for ABS/ASA/ABS-CF/ASA-CF, o Professor oferece um ajuste **opcional (`default_on=False`)**: `scope="machine"`, `key="passive_preheat_seconds"` (valores permitidos `180`, `300`, `480`, `600` s; teto rígido `<= 900` s).
- `inject_passive_preheat_gcode()` insere `G4 S<segundos>` logo após o comando `M190` em `machine_start_gcode`, mantendo apenas chaves válidas do ELEGOO Slicer. A auditoria real de G-code confirma a presença do `G4`.

## 4. Melhoria 4 — Detector de "Pescoços" na Malha + Orientação Guiada pela Carga (`geometry_check.py` + `orientation.py` + `orientation_service.py`)
- **`geometry_check.py`:** `_sample_z_cross_sections()` amostra fatias horizontais da malha em Z, detecta gargalos onde a seção útil cai para `<= 28%` do pico abaixo/acima ou onde a largura mínima de segmento funcional fica crítica (`<= 4,0 mm` em peças altas `>= 25 mm`), populando `NeckFinding`, `has_thin_neck` e `neck_findings`.
- **`orientation.py` & `orientation_service.py`:** `rank_orientations(..., load_type="nao_sei")` mantém comportamento idêntico para uso decorativo/`nao_sei`. Quando `load_type` indicar esforço direcional (`tracao_eixo_z`, `flexao_lateral`, `impacto`), orientações deitadas que alinham as camadas ao maior vão passam a ponderar o compromisso **carga × camadas × suportes**, gerando `load_note` explícito sem nunca prometer carga de ruptura.

## 5. Melhoria 5 — Prévia Visual Local da 1ª Camada/Overhangs + "Receitas Validadas" (`layer_preview.py` + `history.py` + `ui.py`)
- **`layer_preview.py`:** Renderizador 100% offline em PPM (`P6`) carregável diretamente em `tk.PhotoImage`, exibindo grade da mesa CC2 (`256×256 mm`), pegada/ilhas da 1ª camada (do G-code fatiado se disponível ou dos triângulos da base da malha) e projeção dos overhangs críticos em amarelo/laranja.
- **Receitas Validadas:** `find_validated_recipes()` busca registros locais `aprovado` no mesmo polímero/marca/bico para destacar configurações já validadas fisicamente **na impressora do próprio usuário**.
