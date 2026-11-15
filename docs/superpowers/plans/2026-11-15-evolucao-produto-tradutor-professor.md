# Tradutor simples e Professor consistente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans para implementar tarefa por tarefa. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover inconsistências de material e recomendações antes de simplificar a experiência de tradução para Centauri Carbon 2.

**Architecture:** Preservar núcleo Python/Tkinter, perfis locais e ELEGOO Slicer. Centralizar restrições compartilhadas por Professor, IA e comparador; adicionar apresentação progressiva sem reescrever o aplicativo.

**Tech Stack:** Python 3.11+, Tkinter, unittest, ELEGOO Slicer instalado.

**Spec:** `docs/superpowers/specs/2026-11-15-avaliacao-produto-tradutor-professor.md`.

**Status:** plano proposto, não executado. Complementa a revisão de 15/11 (Tasks 27–31), sem reabrir automaticamente suas tarefas concluídas. Primeiro marco: Tasks 1–3. Segundo: Tasks 4–5. Aceitação: Task 6.

## Global Constraints

- Arquivos 3MF do usuário fora do Git e de serviços de IA; resumo textual apenas após autorização explícita.
- Não declarar compatibilidade sem fatiamento real de todas as placas no ELEGOO Slicer.
- Fatiamento não comprova resistência, acabamento ou folgas físicas.
- Preservar origem e perfis instalados; trabalhar em cópias.
- Escopo atual: Centauri Carbon 2; sem ampliar suporte de impressoras neste plano.
- Sem nova dependência obrigatória de IA. Não aplicar mudanças de comportamento durante a auditoria.

## Review Focus

- Nome de perfil enganoso ou ausência de material correspondente: bloquear divergência; Task 1.
- Múltiplos slots com polímeros diferentes: confirmar por slot e não sobrescrever silenciosamente; Task 1.
- IA com valor sintaticamente válido mas inadequado ao uso: restrições locais prevalecem; Task 2.
- Fatiamento aprovado com geometria alterada, falha total ou métricas ausentes: não recomendar; Task 3.
- Usuário não sabe uso/carga e fecha janela durante worker: mensagem honesta e encerramento sem callback inválido; Tasks 4 e 6.

## Task 1 — Identidade do material e confirmação por slot (P0)

**Files:** criar `src/maker_elegoo/material_selection.py`; modificar `ui.py`; testes em `tests/test_material_selection.py` e `tests/test_ui_beginner_flow.py`.

**Interfaces:** `MaterialIdentity(polymer: str, variant: str)`; `MaterialSelection(profile: Profile | None, reason: str, requires_choice: bool)`; `select_material_profile(identity: MaterialIdentity, profiles: tuple[Profile, ...], install: SlicerInstall) -> MaterialSelection`. Resolver metadados com `resolve_profile`, não substring do nome. Variantes desconhecidas exigem escolha explícita. Confirmação será por slot usado, invalidada quando material/perfil muda.

- [x] Escrever testes: ABS não escolhe ABS-CF; perfil renomeado com `filament_type=ABS` é elegível; sem candidato retorna `profile is None`; dois candidatos equivalentes exigem escolha; PLA+TPU não vira ABS+ABS sem decisão explícita; slot não usado não bloqueia.
- [x] Rodar `python -m unittest discover -s tests -p test_material_selection.py` e confirmar falha antes de implementar.
- [x] Implementar seleção e integrar validação de correspondência imediatamente antes de construir/converter o plano; diferenciar material planejado de carregado no texto.
- [x] Rodar testes de seleção e `test_ui_beginner_flow.py`; aceitar somente divergência bloqueada e escolhas por slot preservadas.
- [x] Revisar diff e registrar commit específico.

## Task 2 — Restrições comuns ao Professor, IA e prioridades (P0)

**Files:** criar `src/maker_elegoo/advice_policy.py`, `tests/test_advice_policy.py`; modificar `professor.py`, `ui.py` e `tests/test_revisao_ai_optimization.py`.

**Interfaces:** `PolicyResult(accepted: tuple[Advice, ...], rejected: tuple[Advice, ...], reasons: tuple[str, ...])`; `enforce_advice_policy(project: ProjectInfo, plan: ConversionPlan, goal: PrintGoal, proposals: tuple[Advice, ...]) -> PolicyResult`. Manter tipos existentes de Advice/PrintGoal; evitar import circular com imports de tipos. Classificar explicitamente quais regras de uso/material restringem alternativas e quais são opcionais.

- [x] Testar conselho local de 4 paredes versus IA de 1: rejeição explicada do rebaixamento; valor IA fora de faixa rejeitado; conselho adicional compatível aceito; ABS móvel não recebe brim automático por sugestão IA; alteração de velocidade não invalida proteção de folgas.
- [x] Rodar `python -m unittest discover -s tests -p test_advice_policy.py` e confirmar falhas.
- [x] Implementar política aplicada após combinar sugestões e novamente sobre alterações aprovadas. Conflito não deve desaparecer silenciosamente; preservar revisão pelo usuário.
- [x] Rodar testes da política, Professor e IA; verificar precedência material/uso/prioridade e valores efetivos resultantes.
- [x] Revisar diff e registrar commit específico.

## Task 3 — Alternativas coerentes e elegibilidade integral (P0/P1)

**Files:** modificar `optimization.py`, `tests/test_optimization.py`, `tests/test_revisao_ai_optimization.py`.

**Interfaces:** `is_recommendable(variant: Variant) -> bool`; `_recommended_objective(...) -> str | None`. Exigir `result.success`, validação aprovada e métricas finitas utilizáveis. Acrescentar `Variant.changes_by_scope: dict[str, dict[str, str]]` com default vazio, preservando `changed` para compatibilidade. Usar política da Task 2 para cada alternativa.

- [x] Testar sucesso de fatiamento com geometria alterada: não elegível; todas falham: retorno None e mensagem “Nenhuma alternativa validada”; métricas ausentes/NaN não entram em comparação; alternativa válida continua disponível quando outra falha.
- [x] Testar uso móvel em velocidade com Professor real e perfil sintético completo: não aumentar camada por fallback; testar alteração de filamento/AUX aparecendo no relatório; não rotular variantes idênticas como ganho medido.
- [x] Rodar `python -m unittest discover -s tests -p test_optimization.py` e os testes de revisão; confirmar falhas novas.
- [x] Remover caminho que força camada fora da política, centralizar geração e corrigir recomendação/relatório. Identificar tempos e gramas como estimativas do fatiador, não medição de impressão.
- [x] Rodar testes até passar, revisar diff e registrar commit específico.

## Task 4 — Jornada progressiva e evidência compreensível (P1)

**Files:** modificar `ui.py`, `professor.py`, `labels.py`, `tests/test_ui_beginner_flow.py`, `tests/test_professor_confiavel.py`.

**Interfaces:** `goal_context_completeness(goal: PrintGoal) -> tuple[str, list[str]]` substitui significado público de `goal_confidence`; manter wrapper interno durante migração. Não usar completude para elevar confiança física de Advice. Estados visíveis: informações fornecidas, regras/estimativas, fatiamento e teste físico.

- [ ] Testar decorativa+PLA: pode ter contexto completo, mas nunca evidência de resistência validada; “Não sei” preservado; perguntas mecânicas condicionais ao uso; troca de objetivo revela perguntas e não inventa respostas.
- [ ] Testar acesso a qualidade/equilíbrio/velocidade no resultado sem abrir avançado; detalhes técnicos continuam disponíveis; aprovação agrupada exibe mudanças e conflitos da política antes de aplicar.
- [ ] Rodar testes direcionados e confirmar falhas.
- [ ] Implementar apresentação progressiva arquivo → material → uso/prioridade → resumo → resultado. Exibir em destaque no máximo três decisões, com acesso ao restante; não esconder bloqueios.
- [ ] Verificar testes e janela a 1366×768 com escala de 100% e 150%, navegação por teclado e textos extensos; registrar evidências. Revisar e registrar commit.

## Task 5 — Professor orientado à aplicação e aprendizado (P2)

**Files:** criar `src/maker_elegoo/teaching.py`, `tests/test_teaching.py`; modificar `ui.py`, `professor.py` e documentação de desenvolvimento.

**Interfaces:** `Lesson(observed: str, reason: str, proposal: str, tradeoff: str, verification: str, evidence_class: str)`; `build_lessons(project: ProjectInfo, plan: ConversionPlan, goal: PrintGoal, advices: tuple[Advice, ...]) -> tuple[Lesson, ...]`. Reutilizar Advice.why/expected_effect/what_to_check; não criar segundo motor de recomendação.

- [ ] Testar cenários decorativa PLA, funcional PLA→ABS, articulada ABS e carga em Z: cinco campos legíveis preenchidos, ausência de garantia mecânica, teste sugerido coerente com uso.
- [ ] Testar explicação ABS distinguindo resfriamento da peça, AUX e câmara; nenhuma regra de percentual universal ou afirmação de câmara quente baseada só em tempo de pré-aquecimento.
- [ ] Rodar `python -m unittest discover -s tests -p test_teaching.py` e confirmar falhas.
- [ ] Implementar lições com fonte, condição de aplicação e limites; usar perfis reais como valores, referências técnicas como explicação. Identificar projetos com usos mistos como limitação do objetivo global, sem inferir função pela aparência.
- [ ] Rodar testes, revisar textos com cenários da spec e registrar commit específico.

## Task 6 — Aceitação técnica e com iniciantes

**Files:** modificar `tests/test_ui_beginner_flow.py`, `ui.py` apenas se necessário para encerramento; atualizar `docs/DEVELOPMENT.md`; criar `docs/validation/tradutor-professor-acceptance.md`.

- [ ] Reproduzir aviso de `_poll_worker` após fechar janela, escrever regressão e ajustar cancelamento de callbacks se confirmado. Rodar suíte sem callbacks Tcl inválidos; investigar ResourceWarning separadamente.
- [ ] Executar `python -m unittest discover -s tests -v`; registrar contagem, falhas, skips e avisos, sem equiparar testes simulados a compatibilidade.
- [ ] Usar amostras locais, sem upload, para decorativa PLA, funcional PLA→ABS, móvel ABS, multisslot e multiplacas. Registrar versão do Slicer, perfis, parâmetros finais, integridade da geometria, resultado por placa, tempo e material estimados. Exportações em temporário fora do Git.
- [ ] Abrir resultados no ELEGOO Slicer e conferir suportes, cores, folgas e avisos. Só então declarar compatibilidade desses casos específicos. Resistência/união/folgas exigem impressão e teste; manter pendente se não realizados.
- [ ] Observar três iniciantes: preparar caso simples sem ajuda sobre nomes de perfil; identificar material destino, mudanças e pendências; encontrar comparação sem instrução. Meta proposta: os três completam e distinguem “fatiou” de “resistência testada”; registrar desistências e dúvidas sem maquiar resultado.
- [ ] Reconstruir executável com `scripts/build.ps1`, executar `scripts/smoke_exe.py`; atualizar Graphify com `graphify update .` e Understand Anything conforme DEVELOPMENT após mudanças de código.
- [ ] Revisar cobertura dos requisitos e diff; conferir ausência de 3MF/G-code rastreados; registrar resultados e commit final.

## Fora do próximo marco

Outras impressoras ELEGOO, inferência automática da função de cada objeto, simulação mecânica/FEA e ajuste autônomo com promessa de resistência. Esses itens exigem especificações e evidências próprias. O Professor continuará capaz de dizer que não sabe e orientar como verificar.
