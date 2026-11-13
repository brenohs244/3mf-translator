# Fidelidade e comparação de conversões

O aplicativo deve mostrar, por placa, objetos, instâncias, associações de filamento e diferenças observáveis entre o 3MF original e o exportado. Falta ou alteração de instância/filamento impede o status de conversão concluída; alterações de posição e recursos avançados são relatadas para revisão. O fatiamento deve produzir um G-code não vazio para cada número de placa esperado.

Antes de converter, mostrar os parâmetros transferidos, substituídos e desconhecidos, além de recursos avançados detectados. Após converter, permitir salvar relatório textual local com versão do Slicer e perfis selecionados. Não incluir malhas nem G-code no relatório.

Uma comparação de objetivos cria variantes independentes dos parâmetros de processo, fatia cada uma e compara tempo e material quando disponíveis. Nunca substituir o resultado principal sem escolha explícita. Uma rotina local de regressão pode repetir casos 3MF escolhidos pelo usuário, guardando apenas resumos e resultados fora do Git. Arquivos 3MF permanecem locais e não são enviados à IA.
