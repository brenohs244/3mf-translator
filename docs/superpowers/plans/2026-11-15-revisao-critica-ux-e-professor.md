# Plano de Implementação: Revisão Crítica de UX, Coerência e Professor

**Spec:** `docs/superpowers/specs/2026-11-15-revisao-critica-ux-e-professor-design.md`  
**Fluxo:** TDD → Implementação → Testes Unitários → Fatiamento Real no ELEGOO Slicer → Graphify Update.  
**Restrições:** Manter `.3mf` e `.gcode` fora do Git e de serviços de IA; validar no `elegoo-slicer.exe` antes de declarar compatibilidade.

---

## Tasks

### Task 27: UX Iniciante, Bloqueio de Saída Inválida e Responsividade da UI
**Files:** `src/maker_elegoo/ui.py`, `src/maker_elegoo/slicer.py`, `tests/test_ui_beginner_flow.py`, `tests/test_ui_report.py`, `tests/test_slicer.py`.
- [x] Escrever testes TDD cobrindo:
  - Bloqueio do botão `Abrir no ELEGOO Slicer` quando `ConversionResult.success == False` (mesmo que `destination.exists()`), inclusive no fluxo de orientação.
  - Recusa em `_convert` ao tentar confirmar `"Não sei informar"` como filamento físico carregado.
  - Banner/atalho visível `"Localizar ELEGOO Slicer"` na área principal e no menu `Ferramentas` quando `self.install is None`.
  - Limpeza/mensagem explicativa de `preconversion_var` quando `_update_context_preview` falha, resumo PT-BR em `slicer._details` e confirmação `askyesno` antes de `clear_feedback_history()`.
  - Conversão de `_open_feedback_dialog` para exibir rótulos legíveis (`PURPOSE_LABELS.values()`).
- [x] Rodar testes e confirmar falha inicial.
- [x] Mover `inspect_project(..., include_geometry=True)` e `render_layer1_and_overhang_preview(...)` para worker threads com fila + polling, e converter `run_calib` de `self.after(0, ...)` em thread para fila + polling seguro na thread principal.
- [x] Adicionar diálogo pós-sucesso (`Abrir no ELEGOO Slicer` / `Abrir pasta`), retomada após configurar chave Gemini no meio de `_convert`, botão/opção `"Converter novamente"` após aprovar sugestões de IA, e os ajustes cobertos pelos testes acima.
- [x] Rodar testes até passar.

### Task 28: Correções Críticas no Professor Offline (`professor.py`)
**Files:** `src/maker_elegoo/professor.py`, `tests/test_easy_supports.py`, `tests/test_professor_confiavel.py`, `tests/test_professor_v2_etapa2_3.py`.
- [x] Escrever testes TDD cobrindo:
  - `goal.purpose == "decorativa"` ativando `enable_support = "1"` + `tree(auto)` também em `"equilibrio"` e `"velocidade"` (respeitando `default_on=True` quando `overhang_mm2 >= 250` ou geometria ausente, e `default_on=False` quando `overhang_mm2 < 250`).
  - Precedência `Material > Uso > Prioridade`: `ABS + funcional_leve/externa/moveis/decorativa + economia` mantendo preenchimento mínimo seguro de ABS (`>= 20%`, sem rebaixar para `10%`).
  - `ABS/ASA` em `moveis`, `chaveiro_articulado` e `partes_moveis` propondo `brim_type = "no_brim"` para evitar fusão por `auto_brim` implícito, mantendo o alerta de risco térmico/mesa limpa e avaliando alerta de peça esguia sobre o brim planejado.
  - `velocidade` preservando `layer_height` em peças articuladas (`moveis`, `chaveiro_articulado`, `partes_moveis`).
  - `build_print_summary` verificando valor real `"0"` de `additional_cooling_fan_speed` nos slots ABS em vez da mera presença da chave em qualquer slot.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar correções em `professor.py` e rodar testes até passar.

### Task 29: Alinhamento do Modo Gemini e do Comparador de 5 Alternativas
**Files:** `src/maker_elegoo/professor.py`, `src/maker_elegoo/ai_client.py`, `src/maker_elegoo/optimization.py`, `src/maker_elegoo/ui.py`, `tests/test_ai_client.py`, `tests/test_optimization.py`.
- [x] Escrever testes TDD cobrindo:
  - `merge_with_offline_alerts` preservando ajustes locais não sobrescritos pela IA (`passive_preheat_seconds`, `fan_max_speed`, `support_*`) e aplicando `_consolidate_advices`.
  - `advise_gemini` tratando `slot="1"` (string) sem `TypeError`, filtrando `target_materials` aos slots usados e explicitando câmara passiva (`support_chamber_temp_control = 0`) no prompt.
  - `compare_objectives` herdando pisos do Professor offline (`esforco` com 4 paredes/30%, `ABS` com `>= 20%` Gyroid), sem abortar por colisão de nome (`next_available_destination`) e exibindo `priority_label(rec)` no relatório.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar alterações em `professor.py`, `ai_client.py`, `optimization.py` e `ui.py`; rodar testes até passar.

### Task 30: Expansão por Polímero, Ventilação Avançada ABS, Folgas e Tipos de Carga
**Files:** `src/maker_elegoo/professor.py`, `src/maker_elegoo/materials.py`, `tests/test_professor_confiavel.py`, `tests/test_materials.py`.
- [x] Escrever testes TDD cobrindo:
  - Regras e alertas específicos para `PETG`, `TPU`, `PA/PC` (secagem + warping), compostos `-CF/-GF` (bico endurecido), detecção correta de `PC-ABS` e alerta para slots usados com polímeros incompatíveis (ex.: `PLA + ABS`).
  - Alerta UV para `ABS` em uso `externa`/`calor_sol` sugerindo `ASA`.
  - Inspeção/regras para `close_fan_the_first_x_layers`, `slow_down_layer_time` e `fan_cooling_layer_time` em ABS pequeno, além de validação progressiva em `apply_advice` quando `fan_min_speed` e `fan_max_speed` mudam juntos e permissão de aumentos seguros dentro dos limites de máquina/filamento.
  - Diferenciação real dos tipos de carga `impacto`, `compressao` e `flexao_lateral` + `elefant_foot_compensation` inicial para `moveis`/`partes_moveis`.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar alterações mantendo compatibilidade com perfis reais CC2 e rodar testes até passar.

### Task 31: Verificação Real no ELEGOO Slicer, Reconciliação de Planos Legados e Graphify
**Files:** `docs/superpowers/plans/2026-11-07-makerworld-elegoo.md`, `docs/superpowers/plans/2026-11-09-local-profiles.md`, `docs/superpowers/plans/2026-11-11-codex-geometry-ai.md`, `docs/superpowers/plans/2026-11-11-figure-orientation.md`, `docs/superpowers/plans/2026-11-15-revisao-critica-ux-e-professor.md`.
- [x] Rodar toda a suíte unitária (`python -m unittest discover -s tests -v`).
- [x] Validar no `elegoo-slicer.exe` real (em diretório temporário fora do Git):
  - Projeto decorativo em prioridade `Equilíbrio` (confirmando suporte árvore ativado + folgas sincronizadas).
  - Projeto `ABS` articulado + `Economia` (confirmando `no_brim` e infill mínimo de segurança preservados).
  - Comparador de 5 alternativas em projeto funcional e em ABS.
  - Teste visual/orientação e reconstrução + smoke test do executável Windows (`scripts/build.ps1`), atualizando checkboxes pendentes nos planos legados (`2026-11-07` a `2026-11-11`) conforme evidência real (inspeção manual na GUI do slicer mantida pendente nos planos legados).
- [x] Atualizar `graphify update .` e conferir ausência de `.3mf`/`.gcode` rastreados antes do commit final.
