# Maker → ELEGOO

Aplicativo Windows local para analisar projetos 3MF do MakerWorld e prepará-los para a ELEGOO Centauri Carbon 2 usando os perfis do ELEGOO Slicer instalado.

## Estado

Em desenvolvimento. Consulte o [desenho](docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md) e o [plano](docs/superpowers/plans/2026-11-07-makerworld-elegoo.md).

## Desenvolvimento

Requer Python 3.11 ou superior e ELEGOO Slicer 1.5.3.5 ou versão compatível. Execute `python -m unittest discover -s tests -v`. Para abrir a interface durante o desenvolvimento, defina `PYTHONPATH=src` e execute `python -m maker_elegoo`.

Os arquivos 3MF do usuário ficam locais e não entram no Git. O aplicativo nunca envia G-code para a impressora.

## Modos de análise e IA (opcionais)

O aplicativo distingue três entradas independentes para não misturar funções:

1. **Professor de Impressão (`100% Offline` ou `Professor IA (Google Gemini)`)**: fica no painel principal antes da conversão e avalia uso da peça, prioridade, troca de material (ex.: `PLA → ABS`), ventilação/solda entre camadas, chaveiros e escala.
2. **Analisar orientação/suportes (`Codex / IA`)**: botão habilitado após uma conversão para avaliar candidatos de orientação de figura fatiados localmente (Codex) ou sugerir equivalências de campos não mapeados (Gemini).
3. **Ajuste guiado sem API (copiar/colar JSON)**: disponível em **Ferramentas → Ajuste guiado sem API (copiar/colar JSON)** após a primeira conversão. Escolha a prioridade e o uso da peça, copie o resumo textual para qualquer IA externa e cole a resposta JSON de volta; o aplicativo valida chaves e faixas antes de aplicar. O 3MF, a malha e o G-code nunca são enviados.

## Fidelidade e comparação local

Em **Ferramentas**, use **Prévia de compatibilidade** antes da conversão para ver parâmetros transferidos, substituídos e sem equivalência. Depois de converter, **Comparar placas antes/depois** mostra miniaturas 3MF quando disponíveis, além das contagens de instâncias e IDs por placa; pintura, suportes manuais, posição e cores continuam sujeitos à revisão visual no ELEGOO Slicer. **Salvar relatório** grava o texto mostrado localmente.

**Comparar objetivos de impressão** cria cinco cópias independentes (original, qualidade, velocidade, economia e resistência), fatia cada uma e mostra tempo e material estimados quando o Slicer os fornece. Nenhuma variante é aplicada automaticamente. Para repetir conversões após atualizar o Slicer, use `scripts/regression_local.py` conforme `docs/DEVELOPMENT.md`; mantenha a pasta de saída fora do Git.
