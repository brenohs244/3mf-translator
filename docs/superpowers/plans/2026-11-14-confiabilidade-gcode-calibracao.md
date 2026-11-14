# Plano de Implementação: 5 Camadas Extras de Confiabilidade

**Spec:** `docs/superpowers/specs/2026-11-14-confiabilidade-gcode-calibracao-design.md`  
**Fluxo:** TDD → Implementação → Testes Unitários → Fatiamento Real no ELEGOO Slicer → Graphify Update.

## Tasks

### Task 20: Auditoria profunda de G-code real (`gcode_audit.py` + `slicer.py`)
**Files:** `src/maker_elegoo/gcode_audit.py`, `src/maker_elegoo/slicer.py`, `src/maker_elegoo/ui.py`, `tests/test_gcode_audit.py`, `tests/test_slicer.py`.
- [x] Escrever testes TDD para parsing de `plate_*.gcode` (camadas, temperaturas M104/M109/M140/M190, ventoinhas M106 P0/P2/P3, `G4` pré-aquecimento, vazão volumétrica máxima, tempo mínimo de camada `< 6 s`, saltos de velocidade, ilhas da 1ª camada).
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar `gcode_audit.py` e acoplar em `SlicerCLI.validate()`, `ValidationResult`, `PlateValidationMetric` e `format_conversion_report`.
- [x] Rodar testes até passar.

### Task 21: Pré-aquecimento passivo opcional ABS/ASA (`professor.py` + `slicer.py`)
**Files:** `src/maker_elegoo/professor.py`, `src/maker_elegoo/labels.py`, `tests/test_passive_preheat.py`.
- [x] Escrever testes TDD para oferta opt-in (`default_on=False`) em ABS/ASA com câmara passiva (`support_chamber_temp_control == "0"`), limites rígidos (`180..900 s`), injeção idempotente após `M190` em `machine_start_gcode` e limpeza sem chaves inválidas.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar `SAFE_MACHINE_KEYS`, `inject_passive_preheat_gcode`, validação em `validate_change` e aplicação em `apply_advice`.
- [x] Rodar testes até passar.

### Task 22: Detector de pescoços na malha e orientação guiada por carga (`geometry_check.py`, `orientation.py`, `orientation_service.py`, `professor.py`)
**Files:** `src/maker_elegoo/geometry_check.py`, `src/maker_elegoo/orientation.py`, `src/maker_elegoo/orientation_service.py`, `src/maker_elegoo/professor.py`, `tests/test_geometry_necks_and_load.py`.
- [x] Escrever testes TDD para detecção de gargalo/pescoço em malha tipo ampulheta/chaveiro e estabilidade sem falso positivo em bloco simples, além de pontuação guiada por `load_type` em `rank_orientations` mantendo compatibilidade total quando `load_type="nao_sei"`.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar amostragem Z de seções transversais em `geometry_check.py`, bônus/nota de carga em `orientation.py`/`orientation_service.py` e alerta honesto no Professor.
- [x] Rodar testes até passar.

### Task 23: Gerador rápido 3MF de calibração + contração/folga e "Receitas Validadas" (`calibration.py`, `history.py`, `professor.py`)
**Files:** `src/maker_elegoo/calibration.py`, `src/maker_elegoo/history.py`, `src/maker_elegoo/professor.py`, `tests/test_calibration_and_recipes.py`.
- [x] Escrever testes TDD para geração de malha 3MF estanque (`50,00 mm` + folgas `0,15/0,20/0,30 mm`), cálculo de contração/`filament_shrink`, gravação/leitura de `FeedbackRecord` estendido e descoberta de "Receitas Validadas" sem falsas garantias.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar `calibration.py`, extensão retrocompatível de `history.py` e sugestão baseada em medição física local no Professor.
- [x] Rodar testes até passar.

### Task 24: Prévia visual offline da 1ª camada/overhangs e integração UI (`layer_preview.py`, `ui.py`)
**Files:** `src/maker_elegoo/layer_preview.py`, `src/maker_elegoo/ui.py`, `tests/test_layer_preview.py`, `tests/test_ui_beginner_flow.py`.
- [x] Escrever testes TDD para renderização PPM `P6` da 1ª camada + overhangs e visualização no UI, botões de calibração/prévia visual e exibição de Receitas Validadas e Auditoria G-code.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar `layer_preview.py` e acoplar diálogos/resumos em `ui.py` sem complicar o fluxo principal para iniciantes.
- [x] Rodar todos os testes unitários + validação real com `elegoo-slicer.exe` + `graphify update .`.
