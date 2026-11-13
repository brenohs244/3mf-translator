# Maker → ELEGOO

Aplicativo Windows local para analisar projetos 3MF do MakerWorld e prepará-los para a ELEGOO Centauri Carbon 2 usando os perfis do ELEGOO Slicer instalado.

## Estado

Em desenvolvimento. Consulte o [desenho](docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md) e o [plano](docs/superpowers/plans/2026-11-07-makerworld-elegoo.md).

## Desenvolvimento

Requer Python 3.11 ou superior e ELEGOO Slicer 1.5.3.5 ou versão compatível. Execute `python -m unittest discover -s tests -v`. Para abrir a interface durante o desenvolvimento, defina `PYTHONPATH=src` e execute `python -m maker_elegoo`.

Os arquivos 3MF do usuário ficam locais e não entram no Git. O aplicativo nunca envia G-code para a impressora.

## Ajuste guiado por IA, sem API

Após a primeira conversão, abra **Ferramentas → Ajuste guiado por IA (sem API)**. Escolha a prioridade e o uso da peça, copie o resumo textual e cole em uma IA de sua preferência. Cole a resposta JSON no aplicativo; ele aceita somente parâmetros de processo presentes no perfil ELEGOO e dentro dos limites permitidos. Revise as sugestões e converta novamente para aplicar e fatiar o resultado. O 3MF, a malha e o G-code não são incluídos no resumo.

## Fidelidade e comparação local

Em **Ferramentas**, use **Prévia de compatibilidade** antes da conversão para ver parâmetros transferidos, substituídos e sem equivalência. Depois de converter, **Comparar placas antes/depois** mostra miniaturas 3MF quando disponíveis, além das contagens de instâncias e IDs por placa; pintura, suportes manuais, posição e cores continuam sujeitos à revisão visual no ELEGOO Slicer. **Salvar relatório** grava o texto mostrado localmente.

**Comparar objetivos de impressão** cria cinco cópias independentes (original, qualidade, velocidade, economia e resistência), fatia cada uma e mostra tempo e material estimados quando o Slicer os fornece. Nenhuma variante é aplicada automaticamente. Para repetir conversões após atualizar o Slicer, use `scripts/regression_local.py` conforme `docs/DEVELOPMENT.md`; mantenha a pasta de saída fora do Git.
