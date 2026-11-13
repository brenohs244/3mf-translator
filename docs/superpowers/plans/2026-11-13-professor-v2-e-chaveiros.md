# Plano Futuro: Professor v2, Modo Chaveiros, Análise de Malha e Redimensionamento

**Base de desenho:** `docs/superpowers/specs/2026-11-13-professor-v2-e-chaveiros-design.md`  
**Alvo único de impressora:** Elegoo Centauri Carbon 2 (CC2)  
**Pré-requisito antes de codar cada bloco:** concluir a rodada de benchmarks locais com os modelos `.3mf` adicionais fornecidos pelo usuário (incluindo chaveiros com e sem partes móveis) e manter todos os `.3mf` fora do Git e fora de APIs de IA.

---

## Etapa 0: Rodada de Benchmark com Modelos Reais (Concluída — Chibi + 8 Projetos de Estudo)
Benchmarks executados localmente no `ElegooSlicer 1.5.3.5`:
- `Our+Lady+of+Guadalupe+Chibi.3mf` (estatueta decorativa detalhada).
- 8 projetos em `PROJETOS ESTUDO/`: `flexi+rex+keychain.3mf`, `Dock Box V3 Rear Mounted.3mf`, `Chaveiro+Nossa+Senhora.3mf`, `CANIVETE.3mf`, `Caballero partes.3mf`, `virgen+de+guadalupe.3mf`, `nossa+senhora+de+nazare+multipartsl.3mf`, `Nossa_Senhora.3mf`.

---

## Etapa 0B: Correções Críticas de Compatibilidade e Multi-Cor (`converter.py`, `slicer.py`, `project.py`, `mapping.py`)
1. **TDD (`tests/test_converter.py`, `tests/test_slicer.py`, `tests/test_project.py`):**
   - Testar `_mesh_shapes` e `compare_geometry` quando múltiplos `<object>` em `3D/3dmodel.model` são separados pelo Slicer em `3D/Objects/*.model` (deve retornar `unchanged=True` se cada malha individual bater dentro de `0,0001 mm`).
   - Testar normalização em `_patched_source` (`slicer.py`) removendo chaves residuais multi-nozzle Bambu H2C (`master_extruder_id` e metadados H2C incompatíveis) preservando `paint_color` e geometria.
   - Testar transferência de `enable_prime_tower` em `mapping.py` (quando o projeto tiver múltiplas cores na mesma placa ou `paint_color`).
   - Testar detecção de `support_type` manual em `source_settings` sem `support_enforcer`/`paint_supports`, leitura de `extruder` por `<part>` + `<object>`, leitura de overrides por objeto (`enable_support`, `layer_height`), e contagem de slots efetivamente usados.
2. **Implementação e Verificação CLI:**
   - Atualizar `converter.py` (`_mesh_shapes` por objeto/malha), `slicer.py` (`_patched_source` limpando `master_extruder_id` e chaves H2C), `mapping.py` (`TRANSFERABLE` com `enable_prime_tower`) e `project.py` (slots realmente usados + overrides por objeto + suporte manual vazio).
   - Reexecutar a bateria dos 8 projetos no `elegoo-slicer.exe` verificando **8/8 aprovações** (`success=True` e `mesh.unchanged=True`).

---

## Etapa 1: Transferência Completa de Qualidade e Suporte (`mapping.py`, `labels.py`, `professor.py`)
1. **TDD (`tests/test_mapping.py`, `tests/test_labels.py`, `tests/test_professor.py`):**
   - Testar transferência de `wall_generator`, `support_style`, `support_top_z_distance`, `support_interface_top_layers`, `support_threshold_angle`, `enable_prime_tower`.
   - Testar validação e limites de `SAFE_PROCESS_KEYS` para `wall_generator`, `support_style`, `support_top_z_distance`, `inner_wall_speed`, `top_surface_speed` e `elefant_foot_compensation`.
   - Testar rótulos amigáveis em `labels.py` para todas as chaves novas.
2. **Implementação:**
   - Atualizar `TRANSFERABLE` e `_valid_transfer` em `src/maker_elegoo/mapping.py`.
   - Atualizar `LABELS` em `src/maker_elegoo/labels.py`.
   - Atualizar `SAFE_PROCESS_KEYS`, `validate_change` e o catálogo de chaves no `ai_client.py` (payload e JSON schema para Gemini).

---

## Etapa 2: Refinamento do Professor, Multi-Cor e Overrides por Objeto (`professor.py`, `ai_client.py`, `ui.py`)
1. **TDD (`tests/test_professor.py`, `tests/test_ui_report.py`):**
   - `decorativa` + `qualidade` em bico `0.4 mm` propõe `wall_generator = "arachne"`, `layer_height = "0.12"` (se aplicável), `wall_loops >= 3`, `inner_wall_speed <= 120`, `top_surface_speed <= 100`.
   - Se `enable_support == "1"` (global **ou** override por objeto em `model_settings.config`) com `tree(auto)`, propor `support_style = "tree_slim"` e `support_top_z_distance = "0.16"` (em PLA).
   - Alerta para `sparse_infill_density <= 8%` (como os `5%` vistos em `Caballero` e `Nossa_Senhora`) sugerindo `>= 10–12%` ou `top_shell_layers >= 4–5` contra afundamento de topo.
   - Alerta para suporte manual sem bloqueadores/reforçadores (`Dock Box`: `normal(manual)` com `0` suportes gerados).
   - Painel/relatório **"Guia por Placa & Troca de Cores"**: mapear placa → peças → slot/cor realmente usada (`ui.py`), diferenciar troca de carretel entre placas vs troca automática na mesma placa, alertar quando uma placa exigir `> 4` cores simultâneas para CC2 + Canvas (`virgen`: 5 cores) e ignorar/ocultar slots declarados mas não usados (`CANIVETE` / `flexi+rex`).
   - Corrigir texto do alerta quando `Metadata/layer_heights_profile.txt` existir: informar preservação no `.3mf` + comportamento fixo no fatiamento CLI atual.
2. **Implementação:**
   - Atualizar regras em `advise_offline` (`src/maker_elegoo/professor.py`), `_render_filaments` / relatório em `src/maker_elegoo/ui.py` e contexto de prompt em `src/maker_elegoo/ai_client.py`.

---

## Etapa 3: Modo Chaveiros (`chaveiro_rigido` e `chaveiro_articulado`)
*(Validado em CLI com `Chaveiro+Nossa+Senhora.3mf` e `flexi+rex+keychain.3mf`.)*
1. **TDD (`tests/test_professor.py`, `tests/test_labels.py`, `tests/test_ai_client.py`, `tests/test_ui_profiles.py`):**
   - Testar `chaveiro_rigido`: `arachne`, `wall_loops >= 3` (`4` em equilíbrio/qualidade, preservando `>= 6` se origem já for maior), `top_shell_layers >= 5`, `bottom_shell_layers >= 4`, `sparse_infill_density >= 20%` `gyroid`, velocidades moderadas (`outer <= 60–70`), `ironing_type = "top"` opcional (`default_on=False`), alertas de orientação do olhal, PLA sob calor/carro e **dica de Pausa/Troca de Cor por Camada** quando houver relevo chapado em cor única.
   - Testar `chaveiro_articulado`: mesmas garantias estruturais e de acabamento **mais** `brim_type = "no_brim"` (PLA/PETG), `ironing_type = "no ironing"`, ajuste de `elefant_foot_compensation` (`>= 0.1–0.15 mm`), alerta sobre `enable_support` acidental e alerta contra redução de escala.
   - Diferenciar peça articulada (`flexi+rex`: exige `no_brim`) de montagem multi-peças com componentes pequenos/esbeltos (`CANIVETE`: pino `8×8 mm`, lâmina `1,7 mm`, cabo `82×12×27,8 mm`, preservando/alertando `elefant_foot_compensation = 0`).
2. **Implementação:**
   - Estender `PURPOSES` em `professor.py` e `PURPOSE_LABELS` em `labels.py`.
   - Adicionar regras dedicadas em `advise_offline` e instruções específicas no prompt de `ai_client.py`.
   - Garantir exibição e persistência corretas no ComboBox de Uso em `ui.py` e `settings.py`.

---

## Etapa 4: Análise Geométrica Pré-Conversão e Alerta de Triângulos (`project.py` / `geometry_check.py` / `professor.py`)
1. **TDD (`tests/test_orientation.py`, `tests/test_professor.py`):**
   - Extrair métricas leves reutilizáveis em streaming sem abortar acima de `3.000.000` de triângulos (`Nossa_Senhora` tem `3.978.826`) e sem quebrar projetos multiplaca/multiobjeto: contagem de triângulos por objeto, peças pequenas/esbeltas (`< 20 mm` ou esbeltez alta, ex.: `terco.stl`, `coroa_2`, pinos do `CANIVETE`), área de base (`contact_mm2`), overhang `> 45°` e dimensões `(X, Y, Z)`.
   - Alerta automático quando `triangle_count > 500_000` (destaque acima de `1_000_000`) sem alterar a malha.
   - Sugestão de `no_brim` em PLA quando base for ampla (`>= 1_000 mm²` sem esbeltez extrema), alerta quando peças altas/pequenas estiverem com `no_brim` explícito (`Nossa_Senhora`) e alerta quando houver overhang relevante sem suporte ativo.
2. **Implementação:**
   - Criar helper leve de diagnóstico geométrico reaproveitando o parser streaming de `orientation.py` (lendo tanto `3D/3dmodel.model` quanto `3D/Objects/*.model`).
   - Integrar as métricas no resumo textual enviado ao Professor (Offline e Gemini, mantendo fora qualquer malha/arquivo bruto).

---

## Etapa 5: Redimensionamento Uniforme e Detector de Perda de Qualidade (`scale.py` / `ui.py`)
1. **TDD:**
   - Redimensionar uniformemente um projeto de peça única por **% de escala** ou **altura alvo Z (mm)** garantindo `Z_min = 0`, centralização na mesa ECC2 (`256 × 256 × 256 mm`), remoção segura de `Metadata/layer_heights_profile.txt` obsoleto e rejeição caso ultrapasse o volume útil.
   - Regras de risco de escala:
     - `scale < 0.85` em bico `0.4`: recomendar `0.12 mm` + `arachne` + parede externa `<= 60 mm/s`.
     - `scale < 0.65` ou dimensões/espessuras críticas próximas ao limite do bico: alertar necessidade de bico `0.2 mm`.
     - Uso `moveis` ou `chaveiro_articulado` com `scale < 0.98`: bloqueio preventivo / aviso forte de travamento de folgas.
2. **Implementação e Verificação CLI:**
   - Implementar transformação + pré-validação geométrica e controles opcionais na UI (`ui.py`).
   - Validar cada cenário no `elegoo-slicer.exe` (fatiamento real + conferência de `max_z` e parâmetros no G-code e no `.3mf` exportado).

---

## Critérios de Aceitação Final da Fase 2
- Suíte unitária completa (`python -m unittest discover -s tests`) verde com 100% de passagem.
- Fatiamento real no `elegoo-slicer.exe` com **100% de aprovação (8/8 em `PROJETOS ESTUDO` + Chibi)** — zero falhas, malha preservada nos casos sem escala, dimensões exatas nos casos redimensionados, chaves aplicadas confirmadas no `Metadata/project_settings.config` e G-code.
- Atualização do grafo de conhecimento (`graphify update .`) após cada bloco de alteração de código.
