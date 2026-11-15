# Design: Suportes Otimizados para Fácil Remoção e Ativação Padrão em Peças Decorativas

**Data:** 2026-11-15  
**Escopo:** `src/maker_elegoo/supports.py`, `src/maker_elegoo/mapping.py`, `src/maker_elegoo/professor.py`, `src/maker_elegoo/labels.py`, testes unitários e validação real no `elegoo-slicer.exe`.

## Problema e objetivo

1. Os perfis oficiais da ELEGOO Centauri Carbon 2 definem valores fixos e pouco amigáveis para remoção de suportes em múltiplas alturas de camada e polímeros:
   - `support_top_z_distance` e `support_bottom_z_distance` fixos em `"0.2"` mm mesmo em `0.12 mm Fine` ou `0.28 mm Draft`.
   - `support_object_xy_distance` apertado em `"0.35"` mm (para bico `0.4 mm`, aproxima demais troncos/galhos das paredes verticais).
   - `support_interface_top_layers` em `"2"` e `support_interface_spacing` em `"0.5"` mm.
   - Além disso, o Professor anterior propunha `"0.16"` mm em peças decorativas, o que aumenta aderência/solda do suporte em PLA em vez de facilitar a remoção.
2. Em peças decorativas (`goal.purpose == "decorativa"`), suportes frequentemente são necessários; o usuário deseja que venham ativados por padrão (mantendo opção visível para desmarcar) e que **todos os projetos convertidos** já carreguem as distâncias Z, XY e camadas de interface calculadas pela altura de camada/bico/material — inclusive quando `enable_support = "0"`, para que ao ativar suportes manualmente no ELEGOO Slicer as distâncias ideais já estejam preenchidas.

## Descoberta empírica no ELEGOO Slicer 1.5.3.5 (`OrcaSlicer 2.4.2`)

Testes reais de fatiamento via `elegoo-slicer.exe --export-3mf` e `--slice 0` comprovaram:
1. Com `independent_support_layer_height = "0"` (padrão dos perfis CC2), o fatiador arredonda a folga vertical **para cima** em múltiplos inteiros de `layer_height` (`ceil(support_top_z_distance / layer_height) * layer_height`). Por exemplo, definir `0.24 mm` em camada de `0.20 mm` faz o G-code saltar para `0.40 mm` de vão livre (2 camadas vazias), enquanto `0.20 mm` gera exatamente `0.20 mm`.
2. Ativar `independent_support_layer_height = "1"` não resolveu melhor (em testes com `lh = 0.12` e `lh = 0.16`, o fatiador reduziu o vão efetivo no G-code para `1 × layer_height`, aumentando o risco de solda).
3. O `--export-3mf` do `elegoo-slicer.exe` preserva integralmente todas as chaves `support_top_z_distance`, `support_bottom_z_distance`, `support_object_xy_distance`, `support_interface_top_layers`, `support_interface_bottom_layers`, `support_interface_spacing`, `support_style` e `support_type` mesmo quando `enable_support = "0"`.

## Fórmula escolhida (`compute_easy_support_settings`)

Entrada: `layer_height` (mm), `nozzle_diameter` (mm), `polymer` (ex.: `PLA`, `PETG`, `ABS`, `ASA`, `TPU`, `PA`), `support_type`.

1. **Polímeros mais pegajosos (`sticky`)**: `PETG`, `ABS`, `ASA`, `PA`, `PC`, `TPU`.
2. **Folga vertical (`support_top_z_distance` e `support_bottom_z_distance`)**:
   - Alvo mínimo ajustado ao bico e polímero:
     - Bico `<= 0.25 mm`: `0.14 mm` (PLA) / `0.16 mm` (sticky).
     - Demais bicos (`>= 0.4 mm`): `0.20 mm` (PLA) / `0.22 mm` (sticky).
   - Teto seguro para evitar vão duplo excessivo que derruba saliências:
     - `max_cap = max(layer_height, round((0.80 * nozzle if (sticky or nozzle <= 0.25) else 0.72 * nozzle), 2))`.
   - Passo múltiplo real da camada (`independent_support_layer_height = "0"`):
     - `k = max(1, math.ceil((desired_min - 1e-6) / layer_height))`
     - Enquanto `k > 1` e `round(k * layer_height, 2) > max_cap + 1e-6`, reduz `k -= 1`.
     - Resultado `round(k * layer_height, 2)` (ex. bico `0.4 mm`: `lh=0.12 → 0.24`, `lh=0.16 → 0.16 (PLA) / 0.32 (PETG/ABS)`, `lh=0.20 → 0.20`, `lh=0.24 → 0.24`, `lh=0.28 → 0.28`).
3. **Folga horizontal XY (`support_object_xy_distance`)**:
   - PLA/padrão: `round(max(0.35, 1.25 * nozzle), 2)` → `0.5 mm` para bico `0.4 mm`.
   - Sticky (`PETG/ABS/ASA/PA/PC/TPU`): `round(max(0.45, 1.50 * nozzle), 2)` → `0.6 mm` para bico `0.4 mm`.
4. **Camadas e espaçamento de interface**:
   - `support_interface_top_layers = "3"` (película coesa de 3 camadas para soltar em peça única).
   - `support_interface_bottom_layers = "2"`.
   - `support_interface_spacing`: `round(min(0.40, max(0.20, 0.75 * nozzle)), 2)` (`"0.3"` em `0.4 mm` PLA) ou `round(min(0.45, max(0.25, 0.85 * nozzle)), 2)` arredondado em passo limpo (`"0.35"` em `0.4 mm` sticky).
5. **Estilo de suporte (`support_style`)**:
   - `"tree_slim"` quando `support_type` começa com `"tree"`; `"snug"` quando começa com `"normal"` (mantendo suporte manual sem interferir na escolha manual caso indicado).

## Comportamento integrado

1. **`mapping.build_conversion`:**
   - Inclui `support_bottom_z_distance`, `support_object_xy_distance`, `support_interface_bottom_layers`, `support_interface_spacing` e `support_interface_pattern` em `TRANSFERABLE` (com validação estrita em `_valid_transfer`).
   - Aplica `compute_easy_support_settings` sobre chaves de suporte existentes em `process_settings` que **não** vieram explicitamente transferidas do `.3mf` de origem (`not in transferred`). Assim todo projeto convertido sai pré-configurado mesmo com `enable_support = "0"`.
2. **`professor.advise_offline`:**
   - Para `goal.purpose == "decorativa"`, quando não há suporte ativo global nem por objeto, propõe `enable_support = "1"` (`default_on=True`) e prefere `support_type = "tree(auto)"` caso o processo use `"normal(auto)"`.
   - Após as regras de prioridade (`layer_height`), recalcula `compute_easy_support_settings` usando a **altura de camada final planejada** e o material de destino, atualizando `support_top_z_distance`, `support_bottom_z_distance`, `support_object_xy_distance`, `support_interface_top_layers`, `support_interface_bottom_layers`, `support_interface_spacing` e `support_style` — inclusive quando `enable_support = "0"`.
   - **Nota honesta:** a eficácia real de desprendimento sem marca e ausência de queda em balanços continua dependendo de conferência visual na prévia e teste físico após resfriamento da peça.
