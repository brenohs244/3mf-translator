# Assistente de orientação para figuras

## Intenção

Adicionar ao MakerElegoo uma análise opcional de orientação para figuras, santos e personagens. A prioridade inicial é preservar o acabamento do rosto e da frente. O aplicativo recomenda uma posição e explica as trocas; só altera uma **cópia** do 3MF depois da confirmação do usuário. O arquivo original e os perfis do ELEGOO Slicer permanecem intactos.

## Exemplo observado

`Our+Lady+of+Guadalupe+Chibi.3mf` é um projeto Bambu com uma placa, uma instância e uma malha de cerca de 1,94 milhão de triângulos. A figura tem aproximadamente 98 mm de altura, usa PLA/bico 0,4 mm e já está em pé. A base atual apresenta cerca de 1.240 mm² de triângulos próximos à mesa; posições de lado oferecem apenas cerca de 6 a 37 mm². O projeto atual exportou e fatiou uma placa no ELEGOO Slicer local com o processo 0,16 mm Optimal e Elegoo PLA; a comparação da malha passou. A captura do usuário mostra o rosto e a frente como região prioritária e relata 33 arestas não manifold. Esses dados não demonstram que outra orientação melhoraria a impressão.

## Experiência proposta

1. Após analisar o 3MF, o usuário abre **Analisar orientação de figura**. A análise é local e desligada por padrão.
2. O aplicativo mostra vistas simplificadas da malha nos quatro sentidos horizontais; o usuário escolhe a vista em que aparece o rosto. O aplicativo indica a região frontal que receberá maior peso e permite corrigir a escolha antes de prosseguir. Não tentar reconhecer rostos semanticamente nem enviar malha ou imagem para IA.
3. O aplicativo compara a posição original com posições candidatas: eixos principais para cima e pequenas inclinações para trás. Uma triagem geométrica calcula altura, área próxima à mesa, área de superfícies voltadas para baixo e uma estimativa separada dessa área na região frontal. Posições com contato muito pequeno ou fora do volume útil são descartadas.
4. As melhores candidatas passam pela exportação e pelo fatiamento reais do ELEGOO Slicer instalado, usando máquina, processo e filamento escolhidos no aplicativo. Registrar sucesso ou falha, tempo e material somente quando o fatiador disponibilizar esses números de maneira verificável. Informar quando uma métrica não estiver disponível.
5. Mostrar posição atual e recomendada com justificativa, risco estimado para a frente, contato com a mesa, resultado do fatiamento e perdas de compatibilidade. Se nenhuma candidata tiver ganho frontal claro e validação completa, recomendar manter a posição original.
6. O usuário confirma ou cancela. Ao confirmar, o aplicativo cria um novo 3MF com a transformação da instância, exporta e fatia de novo. Nunca sobrescrever origem, projeto já convertido ou perfis instalados; nunca enviar G-code à impressora. Exigir revisão visual da prévia, suportes e rosto no ELEGOO Slicer antes de imprimir.

## Escopo inicial

- Primeira versão: uma placa e uma instância de figura. Projetos com várias placas, objetos, modificadores ou pintura complexa recebem explicação de que a análise de orientação não está disponível.
- A malha pode ser grande; leitura por streaming e limite de tempo/memória evitam travar a interface. Trabalho pesado roda fora da thread Tkinter, com progresso e cancelamento.
- A posição atual é sempre candidata. O nome ou gênero do modelo não determina a orientação. Uma imagem frontal fornecida pelo usuário orienta a análise do exemplo, mas não entra no instalador.
- As medidas de geometria e G-code estimam risco de suportes e acabamento. Não constituem prova de qualidade estética, resistência nem segurança de impressão.

## Alternativas consideradas

1. **Assistente com confirmação — escolhido.** Compara posições e fatiamento, preserva a opção atual e exige revisão humana. É o caminho que atende à prioridade no rosto sem aplicar mudanças silenciosas.
2. Perfil fixo para figuras. Apenas troca processo/suportes e mantém uma rotação predefinida; não resolve modelos que chegam deitados ou com bases diferentes.
3. Orientação totalmente automática com reconhecimento semântico. Exigiria visão 3D mais complexa, dados de treinamento ou envio da malha, e ainda não garantiria a posição preferida pelo usuário.

## Verificação necessária

- Testes de transformação 3MF: cópia válida, transformação correta, limites de mesa, origem intacta, geometria preservada e recusa de casos fora do escopo.
- Testes de pontuação: figura já bem apoiada não gira sem ganho; alternativa com menor área frontal voltada para baixo vence apenas quando mantém apoio e fatiamento válidos.
- Testar o exemplo real localmente em ao menos duas candidatas e confirmar no ELEGOO Slicer as posições, suportes e prévia. Registrar também a resposta do fatiador ao aviso de arestas não manifold da captura.
- Rodar suíte, Graphify, Understand Anything, empacotamento e smoke test do executável antes da entrega.
