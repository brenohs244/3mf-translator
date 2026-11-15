# Design: Revisão Crítica de UX para Iniciantes, Confiabilidade do Professor e Consistência das Ferramentas

**Data:** 2026-11-15  
**Base verificada:** Auditoria estática e de perfis reais da Centauri Carbon 2 após o commit `38cd1dc` (`139` testes unitários passando em `python -m unittest discover -s tests`).  
**Alvo:** `src/maker_elegoo/ui.py`, `src/maker_elegoo/professor.py`, `src/maker_elegoo/ai_client.py`, `src/maker_elegoo/optimization.py`, `src/maker_elegoo/slicer.py`, planos e testes correspondentes.

---

## 1. Objetivo

Fechar as lacunas práticas observadas na avaliação sob o olhar de um usuário real de ELEGOO Centauri Carbon 2 que baixa projetos `.3mf` do MakerWorld (Bambu Lab) e espera:
1. Um tradutor que **não trave a janela**, guie quando algo faltar e **nunca habilite saída inválida** para impressão.
2. Ferramentas coerentes entre si (`Comparar 5 alternativas` respeitando o mesmo motor do Professor, sem contradições).
3. Um Professor determinístico e IA (Gemini) **sem regressões silenciosas**, cobrindo os materiais, ventilações de câmara passiva, folgas móveis e tipos de carga que já oferece na interface.

---

## 2. Melhorias Especificadas

### A. Experiência do Iniciante, Segurança de Saída e Responsividade (`ui.py`, `slicer.py`)
1. **Localização visível do ELEGOO Slicer:** quando `self.install is None`, exibir alerta/botão visível `"Localizar ELEGOO Slicer"` diretamente na Seção 2 e adicionar atalho no menu `Ferramentas`, em vez de manter o único botão dentro de `Detalhes avançados`.
2. **Bloqueio de abertura em conversão reprovada:** em `_poll_worker` e retorno de orientação, habilitar `Abrir no ELEGOO Slicer` **apenas** quando `result.success and result.destination.exists()` (seguindo o mesmo critério já usado em `_poll_ai` para Codex). Em falha, exibir orientação explícita para não imprimir o arquivo; em sucesso, oferecer diálogo prático com `"Abrir no ELEGOO Slicer"` e `"Abrir pasta"`.
3. **Proibir confirmação de `"Não sei informar"` como filamento físico:** em `_convert`, bloquear confirmação se `physical_material_var == "Não sei informar"`, orientando o usuário a escolher o polímero carregado no carretel (`PLA`, `PETG`, `ABS`, `ASA`, etc.) antes de prosseguir.
4. **Thread principal do Tkinter sempre responsiva:**
   - Executar `inspect_project(..., include_geometry=True)` e `render_layer1_and_overhang_preview(...)` fora da thread principal (com captura explícita de erros e alerta amigável).
   - Substituir chamadas diretas `self.after(0, ...)` vindas da thread `run_calib` por fila (`queue.Queue`) com polling seguro na thread principal.
5. **Estado consistente e erros compreensíveis:**
   - Ao falhar `_update_context_preview`, limpar ou explicar erro em `preconversion_var` para nunca exibir o cartão de um projeto anterior.
   - Em `slicer._details`, antepor resumo em PT-BR com possíveis causas antes do trecho técnico final retornado pelo CLI.
   - Em `_convert`, após salvar chave Gemini ausente com sucesso, retomar a conversão pendente em vez de exigir novo clique e escolha de destino.
   - Em `_open_feedback_dialog`, exibir rótulos legíveis (`PURPOSE_LABELS.values()`) em vez de códigos internos e pedir confirmação (`askyesno`) antes de apagar histórico local.
   - Consolidar/clarificar fluxos de IA na interface e oferecer `"Converter novamente agora"` após aprovação em `_review_suggestions`.

### B. Correções de Bugs no Motor do Professor (`professor.py`, `ai_client.py`)
1. **Suporte padrão em peças `decorativa` para qualquer prioridade:** corrigir a indentação em `advise_offline` que hoje prende `enable_support = "1"` e `support_type = "tree(auto)"` dentro de `if goal.priority == "qualidade":`. Ativar `default_on=True` quando `geom.overhang_mm2 >= 250` (ou quando não houver resumo geométrico) e `default_on=False` quando a peça verificada tiver pouco overhang (`< 250 mm²`).
2. **Precedência explícita Material > Uso > Prioridade:** impedir `goal.priority == "economia"` de sobrescrever com `"10%"` o reforço de preenchimento definido para `ABS/ASA` ou outros usos críticos.
3. **Brim em ABS/ASA com partes móveis (`moveis`, `chaveiro_articulado`, `partes_moveis`):** propor `brim_type = "no_brim"` (ou alternativa segura quando suportada) mesmo em ABS/ASA, evitando que o `auto_brim` implícito dos perfis CC2 funda folgas na 1ª camada — mantendo o alerta claro sobre mesa limpa e pré-aquecimento passivo. Reavaliar também o alerta de peça esguia contra o `brim_type` planejado.
4. **Sincronização do modo Gemini com regras locais:**
   - Atualizar `merge_with_offline_alerts` para preservar ajustes locais (`process`, `filament`, `machine`) não cobertos pela IA e consolidar com `_consolidate_advices`.
   - Em `advise_gemini`, converter `slot` com segurança (`int`) evitando falha silenciosa quando vier como texto, filtrar `target_materials` aos slots usados e informar no prompt que a Centauri Carbon 2 possui câmara passiva sem aquecedor ativo (`support_chamber_temp_control = 0`).
5. **Proteção de camadas em peças articuladas e resumo preciso:** impedir `velocidade` de elevar `layer_height` para `0.24 mm` em `moveis`, `chaveiro_articulado` e `partes_moveis`; corrigir `build_print_summary` para validar se `additional_cooling_fan_speed` dos slots ABS está efetivamente em `"0"` (sem assumir `"0%"` apenas pela presença da chave).

### C. Coerência do Comparador, Cobertura de Materiais, Ventilação e Cargas (`optimization.py`, `professor.py`)
1. **Comparador alinhado ao Professor:** `compare_objectives` passa a partir de `apply_advice(plan, defaults_offline)` respeitando pisos do Professor por uso/material, verifica destino com `next_available_destination` antes de fatiar e exibe `priority_label(rec)` no texto final.
2. **Tabela por polímero e mistura incompatível de slots:** cobrir explicitamente `PETG`, `TPU`, `PA/PC` (incluindo secagem e empenamento), compostos `-CF/-GF` (alerta de bico endurecido), correção de precedência `PC-ABS` em `_base_polymer`, aviso UV para ABS em uso externo (sugerindo ASA) e alerta quando slots usados misturam polímeros termicamente incompatíveis (ex.: PLA + ABS).
3. **Ventilação avançada de câmara passiva e validação progressiva:** inspecionar e permitir ajustes controlados em `close_fan_the_first_x_layers`, `slow_down_layer_time` e `fan_cooling_layer_time` (observados nos perfis reais CC2) para peças ABS pequenas; permitir aumentos seguros dentro dos limites de máquina/filamento em `validate_change` e validar contra o estado progressivo em `apply_advice`.
4. **Uso completo de `LOAD_TYPES`:** diferenciar recomendações e alertas para `impacto`, `compressao` e `flexao_lateral`, além de `tracao_eixo_z`, propondo também alívio inicial de pé de elefante em `moveis`/`partes_moveis`.

---

## 3. Critérios de Aceitação e Verificação
- Nenhum `.3mf` ou `.gcode` entra no Git ou é enviado a APIs externas.
- Todos os itens corrigidos devem nascer com testes TDD unitários antes da implementação.
- Projetos reais da pasta local devem ser fatiados no `elegoo-slicer.exe` em diretórios temporários após as correções antes de declarar compatibilidade.
- Planos antigos com checkboxes defasados devem ser auditados junto com `graphify update .` ao término da execução.
