# Perfis locais do ELEGOO Slicer

## Intenção

Ao abrir o MakerElegoo em qualquer computador Windows, ler os perfis presentes na instalação local do ELEGOO Slicer e permitir escolher impressora, bico, processo e filamento compatíveis. O executável não leva nem instala perfis de outro computador.

## Decisões

- Descobrir perfis de sistema e perfis de usuário no AppData local, inclusive contas além de `default`.
- Resolver herança antes de filtrar por modelo, diâmetro e compatibilidade. O nome do perfil não determina o bico.
- Exibir impressoras Centauri Carbon 2 personalizadas e filtrar processo e filamento pelo perfil de máquina escolhido e seus ancestrais.
- Usar exatamente a impressora selecionada no plano de conversão. Preservar a exigência de fatiamento real antes de declarar sucesso.
- Não ler ou empacotar dados de conta, telemetria, 3MF ou o arquivo `user.7z` fornecido como referência.

## Verificação

Testar com perfis sintéticos que herdam os dados de impressora, processo e filamento; testar a filtragem por outro bico e por outra impressora; executar a suíte, o build e a abertura do executável. A compatibilidade de 3MF continua dependente de fatiamento real no ELEGOO Slicer.
