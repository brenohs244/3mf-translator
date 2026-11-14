# Plano de Implementação: Tradutor Simples com Professor Confiável

**Spec:** `docs/superpowers/specs/2026-11-14-tradutor-simples-professor-confiavel-design.md`  
**Alvo:** Centauri Carbon 2 · `.3mf` sempre fora do Git e de APIs de IA.

## Tasks (TDD → Implementação → Verificação Real → Graphify)

### Task 15: Labels, confiança "Não sei", histórico local opcional e correção `is_original_pla`
**Files:** `src/maker_elegoo/labels.py`, `src/maker_elegoo/history.py`, `src/maker_elegoo/settings.py`, `src/maker_elegoo/professor.py`, `tests/test_professor_confiavel.py`.
- [x] Escrever testes TDD para:
  - Separação estrita `PLA`, `PETG` e origem `mista` em `_inspect_source_materials` / `advise_offline` (PETG → ABS não pode ser rotulado como PLA → ABS).
  - Perguntas reais do Professor (`load_type`, `criticality`, `fit_clearance`, `heat_exposure`, `physical_material`) e redução de confiança com `"nao_sei"`.
  - Explicações estruturadas (`current`, `proposed`, `why`, `expected_effect`, `what_to_check`) e separação de alertas que dependem de ensaio físico (`requires_physical_test`).
  - Histórico local opcional (`history.py`): gravação, leitura, limpeza e ajuste contextual de recomendações sem rede.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar rótulos, histórico local, configurações opcionais e atualização do motor do Professor.
- [x] Rodar testes até passar.

### Task 16: Checklist PLA/PETG → ABS/ASA, revisão de limites/linguagem e 4 classes de evidência
**Files:** `src/maker_elegoo/professor.py`, `src/maker_elegoo/ai_client.py`, `tests/test_professor_confiavel.py`, `tests/test_ui_professor.py`, `tests/test_ai_client.py`.
- [x] Escrever testes TDD para:
  - Remoção de promessas/garantias em `build_print_summary` e `advise_offline` (sem `"garantir boa solda térmica"`).
  - Presença obrigatória das 4 classes de evidência (**Verificado no 3MF**, **Verificado pelo fatiamento**, **Estimado por regra/IA**, **Depende de teste físico**).
  - Checklist específico PLA/PETG → ABS/ASA distinguindo ventilação da peça vs. exaustão do ambiente e considerando perfil (`fan_min_speed`, `ABS-CF`/`ASA-CF`) e geometria (`overhang_mm2`, articulação).
  - Conflitos explícitos (ventilação saliências × adesão camadas; brim × articulações/encaixes).
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar checklist, revisão de limites e atualização de `ai_client.py`.
- [x] Rodar testes até passar.

### Task 17: Métricas por placa no Slicer e comparação de alternativas (`original`, `qualidade`, `velocidade`, `equilibrio`, `economia`)
**Files:** `src/maker_elegoo/slicer.py`, `src/maker_elegoo/optimization.py`, `tests/test_slicer.py`, `tests/test_optimization.py`.
- [x] Escrever testes TDD para:
  - `ValidationResult.plate_metrics` extraindo tempo e gramas por placa no `SlicerCLI.validate()`.
  - `compare_objectives` e `format_objective_comparison` comparando `original`, `qualidade`, `velocidade`, `equilibrio` e `economia` por placa antes de destacar opção, com direção da carga considerada e resistência marcada como não comprovada.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar extração por placa e formatador comparativo com as 4 classes de evidência.
- [x] Rodar testes até passar.

### Task 18: Fluxo principal para iniciantes ("Traduzir para minha ELEGOO"), Cartão Curto e Relatório com Evidências
**Files:** `src/maker_elegoo/ui.py`, `README.md`, `tests/test_ui_beginner_flow.py`, `tests/test_ui_professor.py`, `tests/test_ui_report.py`.
- [x] Escrever testes TDD simulando fluxo de iniciante com 1 e múltiplos filamentos/placas:
  - Medição de decisões exigidas (bico + confirmação explícita de filamento físico + "Traduzir para minha ELEGOO") e tempo até o primeiro resultado (sem abrir detalhes avançados).
  - Nunca presumir que filamento físico = declarado no 3MF (inicia não confirmado ao inspecionar novo 3MF).
  - "Detalhes avançados" retrátil contendo máquina, processo, lista completa de filamentos, Codex, escala e ajuste sem API, preservando todos os controles e testes existentes.
  - Cartão curto pré-conversão, intervenção apenas para ambiguidade/incompatibilidade/risco (`needs_user_intervention`), separação visual de testes físicos e registro local de feedback pós-impressão.
  - `format_conversion_report` exibindo as 4 classes de evidência e o aviso `"Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica."`.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar na UI mantendo compatibilidade total com `test_ui_profiles.py`, `test_ui_codex.py`, `test_ui_orientation.py`, `test_scale.py`.
- [x] Rodar toda a suíte unitária (`python -m unittest discover -s tests -v`).

### Task 19: Verificação Real no ELEGOO Slicer, Graphify e Atualização do Plano
**Files:** `docs/superpowers/plans/2026-11-13-professor-v2-e-chaveiros.md`, `docs/superpowers/plans/2026-11-14-tradutor-simples-professor-confiavel.md`.
- [x] Executar fatiamento real no `elegoo-slicer.exe` (Centauri Carbon 2) para:
  - Decorativo (`Our+Lady+of+Guadalupe+Chibi.3mf` ou `Chaveiro+Nossa+Senhora.3mf`),
  - Funcional / esforço (`Dock Box V3 Rear Mounted.3mf`),
  - Articulado (`flexi+rex+keychain.3mf`),
  - `PETG → ABS` (`CANIVETE.3mf`) e `PLA → ABS` (`flexi+rex+keychain.3mf`),
  - Comparativo real `original / qualidade / velocidade / equilibrio / economia` por placa.
- [x] Conferir no G-code real tempo, gramas por placa, parâmetros aplicados e ausência de regressões de malha.
- [x] Atualizar `graphify update .`, atualizar estado dos planos e manter `.3mf`/`.gcode` estritamente fora do Git.
