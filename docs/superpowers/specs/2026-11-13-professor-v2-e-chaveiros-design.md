# Desenho Futuro: Professor v2, Análise Geométrica, Redimensionamento e Modo Chaveiros

**Escopo de máquina:** Elegoo Centauri Carbon 2 (CC2), mantendo os arquivos `.3mf` do usuário exclusivamente locais, fora do Git e sem envio de malhas/G-code para serviços externos de IA.

**Motivação (evidência de benchmark real):**
O teste comparativo com `Our+Lady+of+Guadalupe+Chibi.3mf` (`1.942.037` triângulos, `48,25 × 39,83 × 98,08 mm`) no `ElegooSlicer 1.5.3.5` mostrou que o tradutor atual garante segurança elétrica/térmica e geometria intacta, mas perde qualidade e eficiência porque:
1. Descarta chaves decisivas da origem e herda padrões agressivos/grosseiros da ECC2 (`wall_generator = classic`, `support_style = default`, `support_top_z_distance = 0.2`, `inner_wall_speed = 200`, `top_surface_speed = 200`, `wall_loops = 2`).
2. O fatiamento CLI ignora `Metadata/layer_heights_profile.txt` (`612` camadas saíram em `0,16 mm` fixo mesmo com o `.txt` preservado no `.3mf`), tornando impreciso o aviso atual de que a curva *"será mantida"*.
3. Ainda não analisa contagem de triângulos, área de base/overhangs, perda de detalhe por redução de escala ou o binômio **acabamento + resistência** exigido por **chaveiros** (rígidos ou com partes móveis).

---

## 1. Melhorias de Tradução e Professor Descobertas no Benchmark

### 1.1 Ampliação de transferência e limites seguros
- **Novas chaves em `TRANSFERABLE` (`mapping.py`):**
  - `wall_generator` (`"classic"`, `"arachne"`)
  - `support_style` (`"default"`, `"grid"`, `"snug"`, `"tree_slim"`, `"tree_hybrid"`, `"tree_strong"`, `"tree_organic"`)
  - `support_top_z_distance`, `support_interface_top_layers`, `support_threshold_angle`
- **Novas chaves permitidas no Professor (`SAFE_PROCESS_KEYS` / `validate_change`):**
  - `wall_generator` (`{"classic", "arachne"}`)
  - `support_style` (lista válida do perfil ECC2, destacando `"tree_slim"` para decorativas/miniaturas)
  - `support_top_z_distance` (`0.08` a `0.28 mm`, limitada a `<= 0.75 × bico`)
  - `inner_wall_speed` e `top_surface_speed` (`30 mm/s` até o valor do perfil ELEGOO — apenas redução)
  - `elefant_foot_compensation` (`0` a `0.4 mm`, já presente nos perfis ECC2)
- Todas as novas chaves ganham rótulos amigáveis em `labels.py` e entram no resumo textual/schema do modo Gemini.

### 1.2 Regra refinada para `decorativa` + `qualidade`
- Em bico `0.4 mm`, quando a peça for decorativa com prioridade **Qualidade visual**:
  - Ativar/propor **`wall_generator = "arachne"`** para preservar micro-relevos e paredes estreitas sem surtos de *Gap infill*.
  - Propor **`layer_height = 0.12 mm`** (respeitando `min_layer_height` da máquina) quando a peça não aplicar curva variável ou for pequena/orgânica.
  - Propor **`wall_loops >= 3`** especialmente para filamentos claros ou quando o preenchimento for `<= 15%`, evitando transparência do núcleo.
  - Reduzir além da parede externa (`60–80 mm/s`) também **`inner_wall_speed` (`<= 120`)** e **`top_surface_speed` (`<= 100`)**.
  - Se `enable_support == "1"` com `tree(auto)` em PLA, propor **`support_style = "tree_slim"`** e **`support_top_z_distance = "0.16"`** (corrigindo a folga `0.20` do perfil padrão ECC2).

### 1.3 Correção honesta da Curva de Camada Variável
- Enquanto o CLI do ELEGOO Slicer não aplicar `Metadata/layer_heights_profile.txt` automaticamente:
  - O alerta em `professor.py` deve informar com precisão que o arquivo de curva variável foi **preservado no `.3mf`**, porém o **fatiamento automático da validação usou altura fixa**; se o usuário quiser variação por altura, deve revisar/reaplicar **Variable Layer Height** na interface do ELEGOO Slicer (ou escolher `0,12 mm` no Professor).

---

## 2. Análise Geométrica Leve e Alerta de Triângulos

Reaproveitando e evoluindo a leitura streaming existente em `orientation.py` (para projetos de 1 objeto / 1 placa, sem quebrar projetos multiplaca):
1. **Alta contagem de triângulos (`triangle_count`):**
   - **Nunca simplificar/dizimar automaticamente** dentro do conversor (manter a garantia de `compare_geometry` / fidelidade intacta).
   - Emitir **alerta informativo** quando `triangle_count > 500_000` (e destaque extra acima de `1_000_000`), explicando que a malha original foi preservada e que, em caso de lentidão no preview/fatiamento, o usuário pode usar *Simplificar modelo (nível Alto)* dentro do próprio ELEGOO Slicer.
2. **Base e overhangs (`contact_mm2` e área `> 45°`):**
   - Se a base plana for ampla (`contact_mm2 >= 1_000 mm²`) em **PLA** e a peça não for alta/esbelta crítica, sugerir `brim_type = "no_brim"` para evitar rebarbas na base.
   - Se a peça tiver overhang expressivo (`> 45°` ou múltiplas ilhas descendentes) e `enable_support == "0"`, emitir alerta/sugestão de suporte árvore (`tree_slim`).

---

## 3. Redimensionamento Uniforme e Análise de Perda de Qualidade

- **Funcionalidade (fase dedicada após benchmark):** permitir ao usuário informar **escala uniforme (%)** ou **altura alvo em mm** para modelos de instância única, aplicando a escala na matriz/vértices do `.3mf` e recentralizando em `Z = 0` na mesa da CC2 (`256 × 256 × 256 mm`).
- **Invalidação segura de metadados dependentes de Z:** ao alterar a escala, remover/descartar `Metadata/layer_heights_profile.txt` antigo (pois as alturas Z não correspondem mais à peça redimensionada) e reavaliar dimensões e limites da mesa.
- **Analisador automático de risco de redução:**
  - Calcular fator de escala resultante e dimensões finais `(X, Y, Z)`.
  - Se houver redução (`scale < 0.85`) em bico `0.4 mm`:
    - Recomendar/ativar `wall_generator = "arachne"`, `layer_height = "0.12"` e `outer_wall_speed <= 60 mm/s`.
    - Estimar risco em regiões finas/estreitas próximas à largura mínima de linha (`< 0.85 mm` / `2 × 0.42 mm`) e alertar quando detalhes pequenos podem exigir **bico `0.2 mm`**.
  - Se o uso escolhido envolver **partes móveis** (`moveis` ou chaveiro articulado) e `scale < 0.98`, bloquear com aviso explícito ou exigir confirmação destacada porque as folgas encolherão e podem fundir.

---

## 4. Avaliação e Desenho do Modo "Chaveiros" (Com e Sem Partes Móveis)

### 4.1 Por que um modo próprio para chaveiros?
Os usos existentes atuais atendem apenas parcialmente:
- `decorativa` enfraquece paredes/infill (`2` paredes, `12%`) — olhais e hastes quebram fácil no bolso/mochila.
- `esforco` prioriza núcleo (`30%` infill), mas não prioriza acabamento fino de letras/logos (`arachne`, `ironing`, velocidades de topo/externa) e não protege juntas móveis.
- `moveis` protege contra brim, mas não reforça argola/paredes nem ajusta acabamento fino de superfície.

Em chaveiros, **acabamento visual** e **resistência mecânica localizada** precisam andar juntos.

### 4.2 Decisão de UX e regras propostas
Adicionar **duas opções explícitas** em `Uso da Peça` (`PURPOSES` / `PURPOSE_LABELS` / prompt Gemini), mantendo a simplicidade de 1 clique na tela principal:

1. **`chaveiro_rigido` — "Chaveiro rígido (acabamento + resistência)"**
   - **Acabamento:** `wall_generator = "arachne"` (letras, logos e contornos finos sem lacunas); `outer_wall_speed <= 70 mm/s` (`60` em qualidade); `inner_wall_speed <= 120`; `top_surface_speed <= 100`; `seam_position = "back"`.
   - **Alisamento (`ironing_type`):** sugerir `"top"` **desmarcado por padrão** (ou ativado para peças chapadas quando prioridade for `qualidade`) explicando que deixa o topo espelhado em chaveiros planos/tags, mas deve ficar desligado em chaveiros esculpidos em 3D.
   - **Resistência do olhal/corpo:** `wall_loops >= 3` (`4` em equilíbrio/qualidade — torna sólido o anel onde vai a argola metálica); `top_shell_layers >= 5`; `bottom_shell_layers >= 4`; `sparse_infill_density >= 20%` (`25%` em equilíbrio/qualidade) com padrão `gyroid`.
   - **Alertas didáticos:**
     - **Orientação do furo/argola:** se o olhal for impresso em pé, a tração puxa entre camadas (eixo Z); orientar imprimir deitado sempre que possível.
     - **Calor (PLA em chaveiro de carro/sol):** alertar que PLA pode deformar acima de `~45–50 °C` dentro de carros fechados; para chaveiro automotivo ou mochila exposta ao sol, recomendar **PETG** ou **ABS/ASA**.

2. **`chaveiro_articulado` — "Chaveiro com partes móveis (articulado / flexi / fidget)"**
   - **Resistência + detalhe dos elos:** `wall_generator = "arachne"`, `wall_loops >= 3`, `top_shell_layers >= 5`, `bottom_shell_layers >= 4`, `sparse_infill_density >= 20%`, `sparse_infill_pattern = "gyroid"`, velocidades moderadas (`outer <= 70`, `inner <= 120`, `top <= 100`).
   - **Proteção rigorosa das folgas móveis:**
     - `brim_type = "no_brim"` em PLA/PETG (brim funde elos e pinos).
     - `ironing_type = "no ironing"` (evita escorrimento de material nas frestas pequenas entre peças móveis).
     - Manter/ajustar **`elefant_foot_compensation`** (`>= 0.1 mm`, sugerindo `0.15 mm` quando `0` em peça articulada) para evitar travamento na 1ª camada.
   - **Alertas didáticos:**
     - Proibição prática de reduzir escala (`< 100%`) sob risco de colar as articulações.
     - Conferir se **`enable_support`** veio ligado na origem sem necessidade (suporte acidental dentro das juntas trava o chaveiro).
     - Alerta específico em troca PLA → ABS pela contração (`0,5–0,8%`) e necessidade de brim somente em ABS.

---

## 5. Processo Contínuo de Benchmark com Novos Modelos 3MF

Antes de implementar a Fase 2 no código, novos modelos `.3mf` fornecidos pelo usuário passarão pelo mesmo protocolo local (em pasta temporária/scratch fora do repositório):
1. Análise geométrica + metadados originais.
2. Comparativo CLI real: configuração atual do `Maker → ELEGOO` vs configuração ideal de referência.
3. Registro de novas regras, exceções e limites descobertos (ex.: peças funcionais com rosca/encaixe, print-in-place/chaveiros articulados, chaveiros multicoloridos chapados, peças grandes em PETG/ABS) para consolidar um conjunto robusto de casos antes da codificação em TDD.

---

## 6. Achados da Bateria de 8 Projetos Reais (`PROJETOS ESTUDO`)

Testes completos de inspeção, conversão (`--export-3mf`) e fatiamento CLI (`--slice 0`) em `ElegooSlicer 1.5.3.5` nos 8 arquivos revelaram **2 bugs críticos de compatibilidade**, **lacunas em troca de cores / multi-partes** e **novas ferramentas de alto valor para o usuário CC2**:

### 6.1 Bugs críticos descobertos (corrigir antes/junto da Fase 2)
1. **Falso positivo de "geometria alterada" (`converter.py` / `Dock Box` e `Nossa_Senhora`):**
   - Projetos Bambu que armazenam vários `<object>` diretamente em `3D/3dmodel.model` passam no `--export-3mf` e no `--slice 0` (`722,86 g` e `95,55 g` fatiados normalmente), porém o `ElegooSlicer` extrai cada `<object>` para um arquivo separado `3D/Objects/*.model`.
   - Como `_geometry_hashes()` e `_mesh_shapes()` agregam por nome de arquivo `.model` (1 entrada → 3 ou 4 entradas), `compare_geometry()` marca `unchanged = False` e reporta falha falsa.
   - **Correção planejada:** comparar por **malha/objeto geométrico individual** (contagem de vértices, triângulos e tolerância `0,0001 mm` por objeto), independente do fatiador reorganizar `3D/3dmodel.model` em `3D/Objects/*.model`.
2. **Crash `3221225477` (`0xC0000005`) em projetos Bambu Lab H2C / multi-extrusor com `paint_color` (`virgen+de+guadalupe.3mf`):**
   - A Placa 1 (chaveiro pintado em 5 cores, vindo de uma Bambu Lab H2C dual-extruder) travou no `--slice 1` devido à chave residual **`"master_extruder_id": "2"`** no `Metadata/project_settings.config` (além de chaves H2C de 2 extrusores/10 filamentos ausentes no perfil da CC2).
   - Teste isolado comprovou que apenas remover `"master_extruder_id"` (e limpar chaves exclusivas multi-nozzle H2C no `_patched_source`) faz a conversão e o fatiamento completo (`--slice 0`, 2 placas, 184–195 trocas `M6211` em 5 cores) passarem com sucesso (`91,87 g`, `20.394 s`).
   - Além disso, quando houver pintura/multicor na mesma placa, preservar/garantir `enable_prime_tower = "1"` em `TRANSFERABLE` / Professor (o fallback atual para `"0"` remove a torre de limpeza!).

### 6.2 Melhorias para Multi-Partes, Multi-Placas e Troca de Cores na CC2
3. **Filtro e detecção real de slots de filamento usados (`project.py`, `mapping.py`, `ui.py`):**
   - Arquivos como `CANIVETE.3mf` (`5` slots declarados, `1` usado), `flexi+rex+keychain.3mf` (`4` slots, `1` usado) e `Dock Box` (`3` slots, `2` usados) obrigam o usuário a escolher 3–5 filamentos mesmo quando só 1 ou 2 existem nos objetos/partes.
   - **Solução:** inspecionar `extruder` tanto em `<object>` quanto em `<part>` (e atributos `paint_color`), identificar **slots realmente utilizados por placa** e exibir claramente *"X de Y slots realmente usados"* (ocultando/preenchendo automaticamente slots ociosos ou permitindo mapeamento simplificado, sem falsos alertas de material).
4. **Painel "Guia de Impressão por Placa / Troca de Cores" (UI & relatório):**
   - Projetos multi-placas monocromáticos por placa (`Caballero`, `Nazare`, `Nossa_Senhora`) não usam AMS/Canvas durante a impressão — cada placa imprime 1 cor e o usuário troca o carretel entre placas. Exibir um resumo claro: **Placa → Peças → Filamento/Cor → Estimativa g/tempo**, destacando **peças minúsculas/frágeis** (ex.: `terco.stl` `6,4 × 18,2 × 4,7 mm`, `coroa_2` `8 × 8 × 7,6 mm`).
   - Quando uma **mesma placa** exigir múltiplas cores (como `virgen` com **5** cores), emitir orientação prática para **Centauri Carbon 2 + Canvas (4 slots)**: alertar que 5 cores excedem os 4 canais simultâneos do Canvas (exige pausa/troca de 1 cor em slot compartilhado ou redução de cores), além de estimar trocas `M6211` (`184–195` trocas ≈ `+90 g` e `+4h45` extras).
   - Para chaveiros em relevo por altura em slot único (`Chaveiro+Nossa+Senhora.3mf`, base `~1,1 mm` + relevo até `2,2 mm`), ensinar/lembrar a inserção de **Pausa / Troca de Filamento por Camada** na prévia do ELEGOO Slicer para imprimir em 2 cores sem Canvas.
5. **Leitura de overrides por objeto em `Metadata/model_settings.config` (`project.py` / `professor.py`):**
   - `virgen+de+guadalupe.3mf` tem `enable_support = "0"` global, mas `enable_support = "1"` + `support_type = "tree(auto)"` **por objeto**; `Caballero` usa `layer_height = "0.12"` e `sparse_infill_density = "15%"` nos dois olhos enquanto o corpo global está em `0.20` e `5%` — e o CLI da ELEGOO **respeita** esses overrides por objeto no fatiamento.
   - O `Professor` deve ler esses overrides efetivos por objeto/placa antes de emitir sugestões globais que possam contrariar ou ignorar ajustes locais úteis.

### 6.3 Novos Guardrails do Professor & Análise Geométrica
6. **Alerta de suporte manual vazio (`Dock Box`):** checar também `source_settings["support_type"]` em `_detect_advanced_features`. Se `enable_support == "1"` com `normal(manual)`/`tree(manual)` e não houver `support_enforcer` nem `paint_supports=`, avisar que **0 suportes** foram gerados no fatiamento.
7. **Infill ultra-baixo (`5%` em `Caballero` e `Nossa_Senhora`):** além de reduzir preenchimentos exagerados (`> 15%`), alertar ou sugerir elevar de `5%` para `>= 10–12%` (ou aumentar `top_shell_layers >= 4–5`) para evitar afundamento (*pillowing*) e baixa rigidez.
8. **Limite de triângulos em `orientation.py` (`Nossa_Senhora` = `3.98M` triângulos):** o limite atual `max_triangles = 3_000_000` bloqueia análise se um projeto grande de placa única exceder 3M; o helper leve de pré-análise deve contar triângulos/dimensões em streaming mesmo acima de 3M sem abortar o resumo principal, emitindo o alerta de simplificação.
9. **Brim inteligente em peças estreitas vs articuladas (`CANIVETE` vs `flexi+rex`):**
   - Confirmado em CLI: em `flexi+rex+keychain.3mf`, o padrão `auto_brim` gerou brim indesejado (`Brim: 1`), enquanto a receita `chaveiro_articulado` (`no_brim`, `arachne`, `3` paredes, `20% gyroid`, `elefant_foot = 0.15`, `70 mm/s`) zerou o brim e reduziu `Gap infill` em **4×** (`451 → 115`).
   - Em `Chaveiro+Nossa+Senhora.3mf` (`24` unidades), `chaveiro_rigido` (`arachne`, `6` paredes preservadas, `ironing = top`, `60 mm/s`) reduziu `Gap infill` em **12×** (`288 → 24`) com apenas **+3 min** no lote de `4h44m → 4h47m`.
   - Já em conjuntos de peças pequenas/esbeltas separadas (`CANIVETE`: pino `8×8×3,35 mm`, lâmina `1,7 mm`, cabo vertical `82×12×27,8 mm`), diferenciar peça **articulada/print-in-place** (exige `no_brim`) de **montagem multi-peças** (onde `brim` / `outer_only` evita tombamento de peças pequenas e `elefant_foot_compensation = 0` original merece alerta se o perfil CC2 impuser `0.1`).
