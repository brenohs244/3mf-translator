# Plano de Implementação: Suportes Fáceis de Remover e Padrão em Peças Decorativas

**Spec:** `docs/superpowers/specs/2026-11-15-suportes-faceis-e-decorativa-design.md`  
**Fluxo:** TDD → Implementação → Testes Unitários → Fatiamento Real no ELEGOO Slicer → Graphify Update.

## Tasks

### Task 25: Fórmula de suportes de fácil remoção (`supports.py` + `labels.py`)
**Files:** `src/maker_elegoo/supports.py`, `src/maker_elegoo/labels.py`, `tests/test_easy_supports.py`.
- [x] Escrever testes TDD cobrindo `compute_easy_support_settings` para bicos `0.2/0.4/0.8 mm`, alturas `0.08..0.28 mm`, PLA vs PETG/ABS/ASA e estilos `tree` vs `normal`.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar `supports.py` e rótulos PT-BR das chaves novas em `labels.py`.
- [x] Rodar testes até passar.

### Task 26: Pré-configuração automática em `mapping.py` e regras no Professor (`professor.py`)
**Files:** `src/maker_elegoo/mapping.py`, `src/maker_elegoo/professor.py`, `tests/test_easy_supports.py`, `tests/test_professor_v2_etapa2_3.py`.
- [x] Escrever testes TDD cobrindo:
  - `build_conversion` embutindo distâncias de fácil remoção mesmo com `enable_support="0"`, respeitando overrides explícitos já transferidos da origem.
  - `advise_offline` ativando `enable_support="1"` (`default_on=True`) por padrão em `decorativa` com `tree(auto)` / `tree_slim` e recalculando `support_top_z_distance` / `support_bottom_z_distance` / `support_object_xy_distance` após alteração de `layer_height` pela prioridade.
  - `chaveiro_articulado` e `esforco` mantendo `enable_support="0"`, mas mantendo folgas pré-configuradas no 3MF.
  - `validate_change` e resumo em `build_print_summary`.
- [x] Rodar testes e confirmar falha inicial.
- [x] Implementar alterações em `mapping.py` e `professor.py` e atualizar o teste legado de `0.16 mm` em `test_professor_v2_etapa2_3.py`.
- [x] Rodar suíte completa de testes + validação real no `elegoo-slicer.exe` + `graphify update .`.
