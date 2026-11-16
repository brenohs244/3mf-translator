# Avaliação de produto: tradutor Bambu → ELEGOO e Professor

Data: 2026-11-15. Base: `f09f8c3393bd3f20a1f08959bffd7f992e7f7158`.
Status: diagnóstico e proposta para revisão; não é implementação nem certificação de impressão.

## Veredito

Atende parcialmente e tem uma base funcional relevante. Já oferece conversão local, perfis ELEGOO, Professor offline, troca de material, perguntas sobre uso/carga/folgas, prioridades incluindo equilíbrio, comparação de alternativas e validação por fatiamento. O próximo investimento deve ser consistência e facilidade de decisão, antes de acrescentar mais IA ou mais opções.

O público suportado hoje é Centauri Carbon 2, não qualquer impressora ELEGOO: o destino é explicitamente conferido em `converter.py:153`. A comunicação deve manter essa delimitação; ampliar modelos exige adaptadores e validação próprios.

## Evidência e limites desta avaliação

- Consultados Graphify e Understand Anything, especificação inicial, plano inicial e revisão já executada de 15/11. O grafo UA aponta para `0b415ab` e está desatualizado; código atual confirmou os achados.
- Executado `python -m unittest discover -s tests`: 150 testes, OK, saída 0. Houve avisos de ResourceWarning e callbacks Tkinter `_poll_worker` após destruição de janela; aprovação dos testes não significa ausência desses defeitos.
- Executadas reproduções sintéticas em memória para seleção de perfil, confiança, combinação IA/local e elegibilidade do comparador. Nenhum arquivo do usuário foi enviado à IA.
- Revisão da jornada baseada nos controles e handlers da interface, com testes existentes. Não foi realizado teste observado com usuário iniciante, inspeção visual completa da aplicação, novo fatiamento real ou ensaio físico nesta auditoria. Evidências históricas dos planos não equivalem a revalidação atual.

## O que já resolve

| Necessidade | Implementação observada | Limite percebido pelo usuário |
|---|---|---|
| Baixar e traduzir | Leitura, perfis, exportação e validação em `project`, `mapping`, `converter`, `slicer` | Requer Slicer instalado; não é compatibilidade universal |
| Saber se configurações fazem sentido | `materials.py`, `advise_offline`, classes de evidência | Regras heurísticas não conhecem toda a aplicação física |
| Peça decorativa, esforço, móvel | `PrintGoal` e regras do Professor | Objetivo é global; projeto com peças de usos diferentes exige evolução por objeto |
| PLA → ABS | Análise térmica, AUX, câmara passiva, pré-aquecimento, folgas e alertas | Não comprova união das camadas nem capacidade de carga |
| Qualidade, velocidade ou meio-termo | Prioridades e cinco alternativas fatiadas | Comparador precisa obedecer às mesmas restrições e explicar diferenças reais |
| Aprender | Conselhos com motivo, efeito esperado, o que conferir e histórico | Muitos controles e linguagem técnica ainda exigem conhecimento prévio |

## Achados priorizados

### P0 — Material físico pode divergir do perfil aplicado

`ui.py:806–833`: correspondência usa substring no nome. Reproduzido: selecionar ABS com apenas `Generic ABS-CF @ECC2` escolhe esse composto. Sem correspondência, um perfil `Generic PLA @ECC2` permanece selecionado e a confirmação física continua verdadeira. O handler também atribui o mesmo perfil a todos os slots usados. Isso não preserva necessariamente intenção de projetos com corpo e material de suporte distintos.

Requisito: comparar metadados resolvidos, distinguir polímero e variante, preservar escolhas por slot e bloquear tradução até resolver divergência. Confirmar um carretel global não pode confirmar vários materiais independentes. Quando usuário só prepara o arquivo para depois, permitir declarar o material planejado sem afirmar que já está carregado.

### P0 — IA pode sobrepor restrições locais

`professor.py:2336`: para a mesma chave/escopo/slot, a sugestão IA ganha do conselho local. Reproduzido: paredes locais 4 + IA 1 resulta apenas em 1. `validate_change` aceita 1 parede como valor geral; validar faixa não garante adequação ao uso.

Requisito: formalizar restrições de material/uso separadas de sugestões. IA e prioridades devem obedecê-las; conflitos precisam ser explicados. Pisos heurísticos devem ser identificados como regras conservadoras, nunca como resistência garantida.

### P0 — Comparador pode recomendar resultado inválido

`optimization.py:121`: elegibilidade considera `validation.success`, não `result.success`; em `converter.py:181` o sucesso também depende de geometria inalterada. Reproduzido com resultado sintético: fatiamento aprovado, conversão reprovada e ainda assim recomendação `velocidade`. Sem alternativa válida, há fallback para a primeira.

Requisito: só destacar conversões integralmente válidas e com métricas disponíveis; nenhuma válida significa nenhuma recomendação.

### P1 — Comparador altera camada fora das decisões do Professor

`optimization.py:77–88`: se o Professor mantém altura, o comparador aplica fator 1,2 em velocidade. Reprodução isolada com conselhos vazios e uso móvel: 0,20 → 0,24 mm. Isso evidencia a rota de fallback; validar também com conselhos reais no teste de regressão, sem assumir que todos os projetos móveis produzem esse resultado.

Requisito: uma única política de geração e validação das alternativas. Exibir alterações de processo, filamento e máquina; hoje `Variant.changed` contabiliza apenas processo. Equilíbrio deve explicar o compromisso obtido, sem prometer que seu nome garante um melhor resultado.

### P1 — Confiança alta significa respostas preenchidas

`professor.py:225`: peça decorativa + material PLA resulta `alta` sem dados físicos. A UI chama isso de “Confiança da recomendação”. O índice mede completude do contexto, não calibração, adesão ou precisão do modelo.

Requisito: separar “Informações fornecidas” de evidência de cada conselho. Perfil identificado, geometria estimada, fatiamento validado e impressão testada são estados diferentes.

### P1 — Jornada ainda exige trabalho de operador

`ui.py:457`: seis perguntas do Professor ficam visíveis simultaneamente, além de seleção/confirmacão de material e cartão extenso. Comparar alternativas fica em ferramentas/detalhes; o usuário que escolhe equilíbrio pode nem descobrir o recurso. Confirmações individuais de parâmetros obrigam o iniciante a interpretar chaves do fatiador.

Requisito proposto: arquivo → impressora/material → uso/prioridade → resumo de decisões → resultado. Mostrar carga/criticidade apenas quando relevantes; manter “Não sei”. Oferecer um conjunto explicado de ajustes para aprovação, mantendo detalhes acessíveis e decisões de risco explícitas. Comparar qualidade/equilíbrio/velocidade deve ser acessível no resultado; economia continua disponível em avançado.

### P2 — Professor deve ensinar a decidir e verificar

Cada conselho deve responder: “o que observei”, “por que isso importa para sua peça”, “o que proponho”, “qual o custo” e “como conferir”. Para força, perguntar direção e consequência da falha, reconhecer falta de magnitude/condição de carga e orientar teste representativo. Para partes móveis, explicar folgas, suporte, brim e efeito da troca de material. Não recomendar aumentar preenchimento como solução universal.

Para ABS, a pergunta correta não é apenas se há ventilação suficiente: resfriamento excessivo pode prejudicar adesão, enquanto detalhes pequenos e balanços podem precisar de resfriamento controlado. Diferenciar ventoinha da peça, auxiliar, condições da câmara e ventilação do ambiente. Não fornecer percentual universal nem afirmar “solda correta” por aprovação no fatiador. Referências técnicas consultadas em 15/11/2026: [Prusa: separação de camadas](https://help.prusa3d.com/article/layer-separation-and-splitting-fdm_1806), [Prusa: empenamento](https://help.prusa3d.com/article/warping_2011), [Fillamentum: ABS Extrafill](https://fillamentum.com/wp-content/uploads/2023/01/3D-printing-guide_Fillamentum-ABS-Extrafill_EN_13052020.pdf). As referências sustentam os mecanismos; valores devem vir do filamento/máquina específicos.

## Abordagens e recomendação

1. Apenas corrigir bugs: menor escopo, mantém esforço cognitivo atual.
2. **Recomendação: corrigir consistência e simplificar a jornada existente**, preservando motor offline e acesso avançado. Aproveita o que já está implementado.
3. Centralizar tudo em conversa com IA: maior variabilidade e dependência de rede/consentimento, sem resolver validação física. Não recomendado como próximo marco.

A opção 2 é uma proposta desta auditoria, não uma escolha previamente aprovada pelo usuário. O pedido atual termina no diagnóstico e plano.

## Critério de sucesso do produto

Um iniciante consegue preparar uma peça simples sem conhecer nomes de presets; vê claramente material e impressora de destino; entende as três principais mudanças e o que ainda deve conferir. Em projeto funcional ou articulado, o aplicativo solicita contexto pertinente e não mascara desconhecimento com confiança alta. Nenhuma sugestão de IA, alternativa ou perfil automático contorna as mesmas restrições. Aceitação final inclui teste com iniciantes, fatiamento real de todas as placas e ensaios físicos separados quando se avaliar resistência ou folgas.
