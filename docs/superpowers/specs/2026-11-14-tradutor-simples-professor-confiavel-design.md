# Desenho: Tradutor Simples com Professor Confiável (CC2)

**Data:** 2026-11-14  
**Base:** `docs/superpowers/plans/2026-11-13-professor-v2-e-chaveiros.md:97-128` e `docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md`  
**Alvo único:** Elegoo Centauri Carbon 2 (CC2), mantendo arquivos `.3mf`, malhas e `.gcode` estritamente fora do Git e de serviços de IA.

## 1. Fluxo principal para iniciantes ("Traduzir para minha ELEGOO")

- A tela principal prioriza 3 passos simples e oculta parâmetros técnicos em **"Detalhes avançados"** (retrátil, fechado por padrão):
  1. **Escolher 3MF** (`Escolher 3MF` + `Analisar`).
  2. **Confirmar bico instalado e filamento físico carregado**: nunca presumir que o filamento físico corresponde ao declarado no 3MF. Ao abrir um novo projeto, a confirmação física inicia **desmarcada** (`physical_filament_confirmed = False`) e o seletor simplificado exige escolha explícita (para 1 slot usado, confirmação única; para múltiplos slots usados, lista resumida dos slots usados com confirmação explícita).
  3. **Uso real e Prioridade**, seguidos de um **Cartão Curto Pré-Conversão** atualizado em tempo real contendo:
     - Material declarado no 3MF → filamento físico e perfil ELEGOO de destino;
     - Placas e cores efetivamente usadas (troca manual entre placas vs. multi-cor na mesma placa);
     - Perfis ELEGOO sugeridos (bico, máquina, processo pela altura de camada original e filamento);
     - Mudanças relevantes e riscos/ambiguidades que exigem decisão.
- **Ação principal:** botão destacado **"Traduzir para minha ELEGOO"**.
- **Intervenção sob demanda:** `_convert()` exige confirmação do filamento físico e abre o diálogo de revisão do Professor **apenas** quando `needs_user_intervention(...)` detectar ambiguidade (ex.: `"Não sei"` em uso crítico/carga/folgas), incompatibilidade (`>4` cores na mesma placa, suporte manual sem área marcada, PLA sob calor, risco de escala), troca térmica relevante (`PLA/PETG → ABS/ASA`, salto grande de velocidade) ou ajustes de processo/filamento aplicáveis.

## 2. Professor orientado ao uso real e correção de `is_original_pla`

- `PrintGoal` passa a incluir campos opcionais retrocompatíveis (padrão `"nao_sei"`):
  - `load_type`: `nao_sei | decorativa | tracao_eixo_z | flexao_lateral | compressao | impacto`
  - `criticality`: `nao_sei | baixa | media | alta`
  - `fit_clearance`: `nao_sei | sem_encaixe | encaixe_justo | partes_moveis`
  - `heat_exposure`: `nao_sei | interno | calor_sol | agua_externo`
  - `physical_material`: `nao_sei | PLA | PETG | ABS | ASA | TPU`
- `goal_confidence(goal)` reduz a confiança da recomendação (`Alta` → `Média` → `Baixa`) sempre que houver `"Não sei"` nas perguntas relevantes ou divergência sem confirmação física, emitindo alerta transparente.
- `Advice` recebe metadados didáticos retrocompatíveis: `expected_effect`, `what_to_check`, `evidence_class`, `requires_physical_test` e `confidence`.
- O diálogo do Professor separa **ajustes de configuração** (`scope != "alert"`), **avisos informativos** e **alertas que dependem de ensaio físico** (`requires_physical_test=True`).
- **Correção de `is_original_pla` (`professor.py`):** substituir a verificação antiga `("PLA", "PETG")` pela classificação explícita `_inspect_source_materials(project)` considerando apenas os slots efetivamente usados (fallback para todos se vazio): diferencia origem **PLA**, **PETG**, **Mista** (`PLA + PETG` etc.) e demais polímeros. Nunca rotular `PETG → ABS` como `PLA → ABS`.

## 3. Diagnóstico específico para troca PLA/PETG → ABS/ASA e linguagem honesta

- Função `build_abs_asa_checklist(project, plan, goal)` gera checklist explícito usando o perfil ELEGOO resolvido e orientando conferir a etiqueta/datasheet do fabricante:
  1. **Contração e folgas** (diferenciando origem PLA vs. PETG vs. mista);
  2. **Empenamento (warping)**;
  3. **Adesão à mesa** (temperaturas do perfil ELEGOO + limpeza do PEI texturizado);
  4. **Temperatura do material/perfil** (comparando origem → ELEGOO sem alterar temperatura automaticamente);
  5. **Ambiente/câmara** (`support_chamber_temp_control = 0`: câmara passiva na CC2; software não mede temperatura real da câmara);
  6. **Ventilação da peça × Exaustão do ambiente** (diferença prática entre resfriar o cordão/saliência e extrair vapores/calor para fora da impressora).
- Eliminar todas as garantias não medidas (`"garantir boa solda térmica"`, `"garante rigidez"`, `"garante topo fechado"`, etc.) de `build_print_summary` e `advise_offline`. Declarar claramente o que é hipótese de ajuste, o que é estimativa do fatiador e o que exige peça de teste/ensaio físico.
- Ajustes de ventoinha, velocidades, brim, paredes e preenchimento respeitam limites reais do perfil resolvido (`fan_min_speed <= fan_max_speed`, `ABS-CF`/`ASA-CF`, `validate_change`), geometria (`contact_mm2`, `overhang_mm2`, `has_slender_parts`) e explicam trade-offs (ventilação em saliências × adesão entre camadas; brim × articulações/encaixes).

## 4. Quatro classes de evidência, comparação por placa e histórico local opcional

- Toda conclusão (`build_preconversion_card`, `build_print_summary`, `format_conversion_report`, `format_objective_comparison`) exibe as **4 classes de evidência**:
  1. **Verificado no 3MF**
  2. **Verificado pelo fatiamento**
  3. **Estimado por regra/IA**
  4. **Depende de teste físico**
  incluindo o lembrete explícito: *"Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica."*
- `SlicerCLI.validate()` passa a registrar `plate_metrics: tuple[PlateValidationMetric, ...]` (tempo e gramas **por placa** vindos do G-code real).
- `optimization.py` alinha `OBJECTIVES` para `original`, `qualidade`, `velocidade`, `equilibrio` e `economia`, exibindo tempo, gramas e parâmetros alterados **por placa**, sem recomendar `"mais forte"` apenas por paredes/preenchimento e considerando direção da carga/orientação com resistência marcada como **não comprovada**.
- Novo módulo `src/maker_elegoo/history.py`: registro local opcional de resultado visual/funcional pós-impressão (`MAKER_ELEGOO_CONFIG_DIR` / `%APPDATA%/MakerElegoo/print_feedback_history.json`) usado apenas localmente para contextualizar futuras recomendações, sem enviar 3MF, malha ou G-code a nenhum serviço externo.
