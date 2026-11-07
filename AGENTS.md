# Instruções do projeto

- Leia `docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md` antes de alterar comportamento.
- Use o plano em `docs/superpowers/plans/2026-11-07-makerworld-elegoo.md` para a primeira implementação.
- Adote o fluxo Superpowers: desenho, plano, TDD, verificação e revisão. Não afirme compatibilidade de 3MF sem fatiamento real no ELEGOO Slicer.
- Use Graphify e Understand Anything para entender relações do código depois que houver módulos. As instruções de atualização ficam em `docs/DEVELOPMENT.md`.
- Mantenha os arquivos 3MF do usuário fora do Git e fora de serviços de IA. Envie à IA apenas um resumo textual após autorização explícita.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
