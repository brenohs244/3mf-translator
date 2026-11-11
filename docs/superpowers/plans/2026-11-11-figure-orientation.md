# Figure Orientation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Oferecer análise local de orientação de figura, priorizando rosto/frente e aplicando uma mudança apenas após confirmação.

**Architecture:** Um núcleo separado lê uma malha e a transformação de uma instância do 3MF, gera quatro vistas e mede candidatas. Um adaptador cria cópias com outra transformação e usa o ELEGOO Slicer existente para exportar/fatiar. A UI mostra a comparação e só salva a candidata aprovada.

**Tech Stack:** Python 3.15, biblioteca padrão, Tkinter, unittest, ELEGOO Slicer CLI, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-11-figure-orientation-design.md`

## Global Constraints

- O 3MF do usuário permanece fora do Git e de serviços de IA.
- Nunca alterar origem, perfis instalados ou enviar G-code à impressora.
- Só declarar validação após exportação estrutural e fatiamento real da placa.
- Primeira versão: uma placa, uma instância de figura; casos fora do escopo recebem motivo legível.

## Review Focus

- Transformação com rotação prévia: composição deve preservar escala, posicionar na mesa e manter identidade da malha.
- 3MF com múltiplos objetos/placas, matrizes inválidas ou limites excedidos: recusar sem criar saída parcial.
- Candidata que parece melhor geometricamente mas falha no fatiamento: não recomendar nem aplicar.
- Figura já bem apoiada: manter posição atual se nenhuma alternativa tiver ganho frontal comprovável.
- UI: alteração só após confirmação; cancelamento não deixa 3MF temporário na pasta do usuário.

---

### Task 1: Ler a cena e mostrar o lado frontal

**Files:** Create `src/maker_elegoo/orientation.py`, `tests/test_orientation.py`.

**Interfaces:** `load_scene(path: Path) -> Scene`; `render_front_views(scene: Scene, size: int = 220) -> dict[str, bytes]` gera PPM para `+X`, `-X`, `+Y`, `-Y`.

- [ ] Escrever testes com 3MF sintético de uma instância, transformação existente, figura vazia e arquivo com duas instâncias; confirmar falha inicial.
- [ ] Implementar leitura por streaming, limites de vértices/triângulos e extração de transformação. Recusar casos fora do escopo com `OrientationError`.
- [ ] Implementar quatro vistas locais de profundidade sem dependência externa; testar dimensões e diferença entre frente e costas de uma malha assimétrica.
- [ ] Rodar `python -m unittest tests.test_orientation -v` até passar.

### Task 2: Pontuar e criar candidatas

**Files:** Modify `src/maker_elegoo/orientation.py`; extend `tests/test_orientation.py`.

**Interfaces:** `rank_orientations(scene: Scene, front: str, printable_area: list[str], printable_height: float) -> list[Candidate]`; `write_oriented_copy(source: Path, candidate: Candidate, destination: Path) -> Path`.

- [ ] Testar seis eixos principais, inclinações pequenas, área de apoio, altura/encaixe, risco frontal e regra de manter a posição atual quando não há ganho suficiente; confirmar falha.
- [ ] Implementar pontuação geométrica determinística, rejeição de candidatos sem apoio/fora da mesa, e relatório de medidas com rótulo de estimativa.
- [ ] Testar transformação 3MF em cópia, arquivo original intacto e malha igual, incluindo rotação prévia e XML com ordem de atributos diferente; confirmar falha e implementar escrita segura.
- [ ] Rodar testes de orientação e suíte completa.

### Task 3: Medir com o fatiador e recomendar

**Files:** Create `src/maker_elegoo/orientation_service.py`, `tests/test_orientation_service.py`; modify `src/maker_elegoo/slicer.py` only if required for métricas.

**Interfaces:** `evaluate_orientations(project: ProjectInfo, plan: ConversionPlan, front: str, slicer: SlicerCLI, *, progress: Callable | None = None, cancelled: Callable | None = None) -> OrientationAnalysis`.

- [ ] Testar que posição atual e melhores candidatas são exportadas/fatiadas, falhas não são recomendadas, nenhuma candidata boa preserva a atual, cancelamento apaga temporários; confirmar falha.
- [ ] Implementar avaliação em diretórios temporários, comparação estrutural e coleta de tempo/material só quando o G-code tiver campos identificáveis; registrar métricas ausentes.
- [ ] Rodar testes do serviço e suíte completa.

### Task 4: Fluxo Tkinter e confirmação

**Files:** Modify `src/maker_elegoo/ui.py`; create `tests/test_ui_orientation.py`.

**Interfaces:** diálogo **Analisar orientação de figura** abre quatro vistas, escolhe a frente e mostra recomendação; **Aplicar em cópia** pede novo caminho, executa a conversão/validação e permite abrir resultado no ELEGOO Slicer.

- [ ] Testar com cena e fatiador falsos que nenhuma escrita de destino ocorre antes da confirmação e que cancelamento mantém o projeto intacto; confirmar falha.
- [ ] Implementar trabalho pesado fora da thread Tkinter, progresso, cancelamento e erros legíveis.
- [ ] Rodar suíte, smoke da UI e revisar layout em 980x760.

### Task 5: Exemplo real e distribuição

**Files:** Modify `docs/DEVELOPMENT.md`, `scripts/README-DISTRIBUTION.txt`; update generated graphs.

- [ ] Executar a análise no `Our+Lady+of+Guadalupe+Chibi.3mf` local com PLA, bico 0,4 e processo 0,16 mm; fatiar atual e ao menos uma candidata e registrar o resultado sem divulgar o 3MF.
- [ ] Abrir visualmente a cópia no ELEGOO Slicer e verificar face, suportes e placa; não afirmar ganho estético sem esta revisão.
- [ ] Rodar suíte completa, `graphify update .`, Understand Anything, `scripts/build.ps1`, `scripts/smoke_exe.py` e integridade do ZIP.
- [ ] Revisar diff e entregar executável/pacote Windows, documentando limites observados.
