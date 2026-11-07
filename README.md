# Maker → ELEGOO

Aplicativo Windows local para analisar projetos 3MF do MakerWorld e prepará-los para a ELEGOO Centauri Carbon 2 usando os perfis do ELEGOO Slicer instalado.

## Estado

Em desenvolvimento. Consulte o [desenho](docs/superpowers/specs/2026-11-07-makerworld-elegoo-design.md) e o [plano](docs/superpowers/plans/2026-11-07-makerworld-elegoo.md).

## Desenvolvimento

Requer Python 3.11 ou superior e ELEGOO Slicer 1.5.3.5 ou versão compatível. Execute `python -m unittest discover -s tests -v`. Para abrir a interface durante o desenvolvimento, defina `PYTHONPATH=src` e execute `python -m maker_elegoo`.

Os arquivos 3MF do usuário ficam locais e não entram no Git. O aplicativo nunca envia G-code para a impressora.

