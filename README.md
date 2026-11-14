# Maker → ELEGOO

Aplicativo Windows local para analisar projetos 3MF do MakerWorld e prepará-los para a ELEGOO Centauri Carbon 2 usando os perfis do ELEGOO Slicer instalado.

## Estado

Em desenvolvimento. Consulte o [desenho](docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md) e o [plano](docs/superpowers/plans/2026-11-07-makerworld-elegoo.md).

## Desenvolvimento

Requer Python 3.11 ou superior e ELEGOO Slicer 1.5.3.5 ou versão compatível. Execute `python -m unittest discover -s tests -v`. Para abrir a interface durante o desenvolvimento, defina `PYTHONPATH=src` e execute `python -m maker_elegoo`.

Os arquivos 3MF do usuário ficam locais e não entram no Git. O aplicativo nunca envia G-code para a impressora.

## Fluxo principal para iniciantes

1. Escolha o projeto `.3mf` do MakerWorld.
2. Confirme o bico instalado e o **filamento físico carregado na impressora** (o aplicativo nunca presume que o carretel físico é igual ao declarado no `.3mf`).
3. Responda ao contexto da peça no Professor de Impressão (**uso, prioridade, direção da carga, criticidade, encaixes/folgas e calor/sol** — com opção *Não sei informar*, que reduz a confiança da recomendação).
4. Revise o **Cartão Pré-Conversão** e clique em **Traduzir para minha ELEGOO**. Máquinas, processos, filamentos por slot, escala e ferramentas avançadas ficam recolhidos em **Mostrar detalhes avançados ▾**.

Cada conclusão separa explicitamente as 4 classes de evidência (**Verificado no 3MF**, **Verificado pelo fatiamento**, **Estimado por regra/IA** e **Depende de teste físico**). *Fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica.*

## Modos de análise, histórico e IA (opcionais)

1. **Professor de Impressão (`100% Offline` ou `Professor IA (Google Gemini)`)**: avalia uso real da peça, prioridade, origem real (`PLA`, `PETG` ou mista), checklist completo para troca `PLA/PETG → ABS/ASA` (câmara passiva, ventilação da peça × exaustão do cômodo, contração e conflitos), chaveiros e escala.
2. **Histórico local opcional (`Registrar resultado da impressão`)**: grava observações após o teste físico somente neste PC para contextualizar futuras conversões (nenhum `.3mf`, malha ou `.gcode` sai da máquina).
3. **Analisar orientação/suportes (`Codex / IA`)** e **Ajuste guiado sem API (copiar/colar JSON)**: ficam dentro de **Detalhes avançados** / **Ferramentas**. O `.3mf`, a malha e o `.gcode` nunca são enviados.

## Fidelidade e comparação por placa

Em **Detalhes avançados** ou **Ferramentas**, **Comparar objetivos de impressão / 5 alternativas** cria cinco cópias independentes (**original**, **qualidade**, **velocidade**, **equilibrio** e **economia**), exibe tempo e gramas **por placa** e parâmetros alterados antes de sugerir um ponto de partida alinhado ao objetivo (marcando resistência mecânica como não comprovada sem ensaio físico). Para repetir conversões após atualizar o Slicer, use `scripts/regression_local.py` conforme `docs/DEVELOPMENT.md`; mantenha a pasta de saída fora do Git.
