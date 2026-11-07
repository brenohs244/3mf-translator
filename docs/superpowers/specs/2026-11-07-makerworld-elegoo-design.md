# Conversor MakerWorld → ELEGOO Centauri Carbon 2

## Intenção

Criar um aplicativo Windows instalável que ajude o usuário a aproveitar projetos 3MF baixados do MakerWorld na ELEGOO Centauri Carbon 2. A primeira entrega deve gerar um projeto editável no ELEGOO Slicer, explicar as adaptações e exigir conferência do fatiamento antes da impressão.

## Situação encontrada

- O diretório do projeto começou sem código nem repositório Git; inicializar Git e organizar o projeto faz parte da primeira entrega.
- Neste computador, ELEGOO Slicer 1.5.3.5 e OrcaSlicer estão instalados. O ELEGOO Slicer contém perfis oficiais da Centauri Carbon 2 para bicos de 0,2, 0,4 e 0,8 mm; o perfil selecionado atualmente é o de 0,4 mm.
- O Bambu Studio armazena configurações de projeto em `Metadata/project_settings.config` e outras partes do 3MF. O 3MF é um pacote ZIP com modelo e metadados.
- Há três exemplos reais no diretório: dois projetos Bambu (um PLA e outro PETG/TPU) e um projeto ELEGOO Centauri Carbon 2 com três placas e quatro filamentos, útil como referência de formato.

## Objetivos da primeira entrega

1. Selecionar um 3MF local, escolher bico (0,2, 0,4 ou 0,8 mm), um perfil de filamento ELEGOO para cada filamento do projeto e um perfil de processo ELEGOO compatível. Descobrir os perfis diretamente na instalação do fatiador e oferecer a seleção na interface, incluindo perfis criados pelo usuário.
2. Ler e resumir placas, objetos, filamentos, cores e parâmetros de processo presentes no arquivo, quando disponíveis.
3. Criar uma **cópia** do projeto com perfis ELEGOO e parâmetros compatíveis, preservando geometria e organização sempre que o formato permitir. Não alterar o arquivo de origem nem os perfis instalados.
4. Produzir relatório de fidelidade: itens preservados, convertidos, substituídos pelo perfil ELEGOO ou não representáveis.
5. **Fatiar automaticamente o projeto convertido com o ELEGOO Slicer instalado** e analisar código de saída, erros, alertas e existência dos artefatos esperados. Só indicar conversão concluída quando a validação estrutural e o fatiamento automático de todas as placas passarem. Em caso de falha, manter o projeto exportado, mas marcar claramente a falha e seu diagnóstico. Os artefatos de validação ficam em diretório temporário; não são enviados à impressora.
6. Permitir abrir o resultado no ELEGOO Slicer para o usuário revisar placas, cores, suportes, temperatura, limites e prévia do fatiamento mesmo após o teste automático.
7. Distribuir um executável/instalador Windows com configuração local por usuário e detecção do ELEGOO Slicer.
8. Analisar a troca de material para PLA, PETG ou ABS usando perfil ELEGOO selecionado para cada filamento. Mostrar diferenças de temperatura, mesa, ventilação e vazão/velocidade e incompatibilidades para revisão; não assumir que a peça suporta a troca sem conhecer seu uso.
9. Oferecer análise opcional por IA para campos Bambu sem mapeamento direto. A IA pode sugerir uma configuração ELEGOO equivalente somente se a chave de destino existir no perfil/esquema do ELEGOO Slicer. Mostrar origem, destino, valor, justificativa e grau de confiança; exigir confirmação do usuário para aplicar. Listar também recursos próprios do ELEGOO Slicer que possam melhorar o projeto, diferenciando sugestões de mudanças verificadas pelo fatiamento.

## Limites e decisões

- Linguagem: Python; interface desktop simples com Tkinter. Núcleo de leitura e transformação separado da interface. Priorizar biblioteca padrão para manter baixo o tamanho do programa.
- O ELEGOO Slicer é necessário para fatiar e imprimir, mas o Bambu Studio não é necessário para analisar o 3MF. A aplicação não deve depender de uma conta MakerWorld.
- A fonte para limites de máquina e material são os perfis instalados do ELEGOO Slicer. O aplicativo resolve a herança dos JSONs antes de usar os valores. Parâmetros de máquina e filamento Bambu não prevalecem sobre os perfis ELEGOO.
- O programa mostra os perfis de processo disponíveis como opções para objetivo de impressão; o usuário pode escolher entre perfis como Standard, Fine, Draft e Strength conforme existirem para seu bico. O nome do perfil não é tratado como prova de desempenho; tempo e material devem vir do fatiamento.
- A conversão é por lista explícita de campos compartilhados e transformações documentadas. Campos desconhecidos entram no relatório; não são silenciosamente copiados para o projeto de destino.
- A IA é opcional e desligada por padrão. O usuário informa chave de API e autoriza o envio de um resumo textual de configurações; o arquivo 3MF e a malha não são enviados. Nenhuma sugestão é aplicada sem revisão. Validar tipos, faixas e compatibilidade da sugestão antes de usá-la; nunca permitir que IA altere comandos de segurança, firmware ou G-code livre nesta fase.
- O fatiamento automático pode gerar G-code temporário para validação, mas nunca envia arquivos à impressora. O usuário confere o projeto no ELEGOO Slicer antes de imprimir.
- Confirmar que a versão instalada do ELEGOO Slicer aceita fatiamento por linha de comando antes de implementar o conversor. Se houver limitação nessa versão, documentar o impedimento e apresentar uma alternativa técnica para aprovação, em vez de declarar sucesso sem validação.
- Compatibilidade avançada (suportes pintados, pintura multicolorida, modificadores, G-code por camada e placas múltiplas) deve ser medida com exemplos reais e reportada individualmente. Não prometer preservação até passar em validação.
- O primeiro marco funcional usa um 3MF simples e depois um 3MF real do usuário. Sem amostras, só a leitura de perfis e o analisador podem ser considerados demonstrados.

## Melhorias e evolução

- **Etapa seguinte — otimização parametrizada:** oferecer quatro objetivos (qualidade, velocidade, economia, resistência), com mudanças pequenas e justificadas em altura de camada, paredes, preenchimento, velocidades e suportes, limitadas pelos perfis de bico/material. Comparar tempo e material estimados pelo fatiador antes de recomendar um ajuste. A resistência real depende de orientação, material e carga; o programa não deve declarar ganho mecânico sem ensaio.
- **Análise geométrica:** extrair dimensões, área/volume estimados, orientação, espessuras mínimas quando mensuráveis e risco de falta de apoio. Usar biblioteca de malha apenas quando a regra exigir; não enviar geometria à nuvem por padrão.
- **IA opcional no primeiro marco:** adaptador Gemini (plano gratuito sujeito a cotas), usando resumo de parâmetros e medições para sugerir equivalências de campos desconhecidos e recursos do ELEGOO. Chave guardada localmente; o usuário escolhe explicitamente se compartilha dados. A IA não substitui validações determinísticas nem a revisão humana.
- **Futuro:** perfis de outras impressoras por adaptadores, monitoramento de impressora por conector específico, histórico local e, se houver necessidade real, cadastro/sincronização de usuários. Essas partes não entram no primeiro marco.

## Ferramentas para desenvolver e manter o projeto

- Usar e documentar o fluxo Superpowers para desenho, plano, testes, verificação e revisão.
- Instalar Graphify Local no escopo do projeto e gerar um grafo do código após a primeira implementação. O grafo serve à manutenção do repositório; não é parte do programa distribuído aos usuários.
- Executar Understand Anything no código implementado e manter seu grafo de arquitetura no repositório ou documentar sua regeneração. Também é ferramenta de desenvolvimento, separada do executável.
- Usar Find Skills para avaliar habilidades adicionais antes de adotá-las. A busca inicial encontrou Graphify oficial; habilidades genéricas de modelagem 3D não resolvem a compatibilidade Bambu → ELEGOO e não são dependências do aplicativo.

## Abordagens consideradas

1. **Aplicativo Python Windows — escolhido.** Desenvolvimento rápido, leitura local de perfis e projeto, distribuição como executável. Exige um empacotamento próprio e interface menos flexível que uma web.
2. Extensão em C++ do ELEGOO Slicer. Integração mais profunda, com custo alto de desenvolvimento e manutenção a cada versão do fatiador.
3. Aplicativo web local. Interface flexível e caminho fácil para contas, com mais componentes e distribuição mais trabalhosa para o primeiro uso individual.

## Verificação necessária

- Comparar o 3MF de entrada e saída: integridade do pacote, contagem e hashes dos recursos de geometria, placas, cores e parâmetros suportados.
- Executar o fatiamento por linha de comando no ELEGOO Slicer instalado para todas as placas e conferir erros, avisos e artefatos gerados. Depois abrir o resultado na interface para verificar a Centauri Carbon 2, bico, cores e prévia sem substituição silenciosa de configurações.
- Repetir com o arquivo real do usuário e documentar perdas específicas antes de afirmar compatibilidade completa.

## Escolhas deixadas para a implementação

- Layout detalhado da interface, formato exato do relatório e mecanismo de empacotamento Windows, desde que mantenham a aplicação local e simples de instalar.
- Mapeamentos de campos específicos serão definidos a partir de exemplos reais e do código/arquivos de perfil dos fatiadores.

## Fontes

- [Bambu Studio: implementação 3MF](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Format/bbs_3mf.cpp)
- [ELEGOO Slicer: repositório oficial](https://github.com/elegooofficial/ElegooSlicer)
- [ELEGOO: perfil oficial da Centauri Carbon 2](https://github.com/elegooofficial/ElegooSlicer/blob/main/resources/profiles/Elegoo/machine/ECC2/Elegoo%20Centauri%20Carbon%202.json)
- [Google: cobrança e cotas do Gemini](https://ai.google.dev/gemini-api/docs/billing)
