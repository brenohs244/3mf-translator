# Análise opcional com Codex de orientação e suportes

## Intenção

Ampliar o botão **Analisar com IA** para oferecer **Codex** como provedor adicional ao Gemini. O Codex recebe somente um resumo textual de configurações e medições locais, explica oportunidades de equivalência de parâmetros, orientação e suportes, e devolve sugestões estruturadas. O usuário revisa cada sugestão. Uma alteração só entra em uma nova cópia depois de passar pelas regras locais e pelo fatiamento real no ELEGOO Slicer.

## Estado atual

- O botão atual aparece após a conversão e chama Gemini com até 30 campos de configuração sem equivalência. A resposta passa por lista de chaves, faixas e confirmação antes de uma nova conversão.
- O assistente de orientação produz quatro vistas locais para a pessoa indicar a frente; estima área de contato, superfície voltada para baixo e risco frontal; fatia a posição atual e alternativas viáveis. Ele pode recomendar manter a posição original.
- A validação do ELEGOO Slicer fornece sucesso/falha, avisos, tempo e massa estimados quando presentes no G-code. Não há medição confiável do acabamento visual, da quantidade de suporte por região nem da resistência da peça.
- `codex.exe` está instalado neste computador e oferece `exec` não interativo, saída por esquema JSON, sessão efêmera, configuração isolada e sandbox de leitura. O executável distribuído não inclui o Codex; cada computador deve instalá-lo e autenticá-lo para usar esse provedor.

## Experiência proposta

1. Em **Analisar com IA**, selecionar **Codex** ou **Gemini**. Codex pode propor orientação e suportes; Gemini conserva o comportamento atual. Se Codex não estiver disponível, mostrar instrução curta de instalação/autenticação e manter o resto do aplicativo utilizável.
2. A análise de figura pede ao usuário a vista frontal entre as quatro vistas locais, ou reutiliza uma análise de orientação ainda válida para o mesmo arquivo, frente e perfis. Quando o projeto estiver fora do escopo de uma placa e uma instância, explicar que orientação não pode ser avaliada e ainda permitir a análise de parâmetros de processo.
3. Preparar localmente um resumo limitado: perfil de impressora, bico, material, opções seguras de processo, campos sem equivalência, dimensões, apoio, risco frontal e geral das candidatas, status de fatiamento, tempo e massa quando disponíveis, e opções atuais de suporte. Não incluir caminho, nomes identificáveis de arquivo, XML 3MF, vértices, faces, imagens, G-code ou credenciais. Mostrar exatamente esse resumo antes de pedir autorização para enviá-lo ao Codex.
4. Executar `codex exec` em diretório temporário vazio, com entrada por `stdin`, `--ephemeral`, `--ignore-user-config`, `--sandbox read-only` e `--output-schema`; impor tempo máximo e limite de tamanho da resposta. A opção usa a autenticação local do Codex, sem pedir chave Gemini. A chamada é remota para o modelo: o resumo textual aprovado sai do computador.
5. A resposta separa **explicação**, **hipótese** e **mudança verificada**. Para orientação, o Codex pode escolher apenas IDs de candidatas produzidas localmente e aprovadas pela triagem; nunca inventar rotação nem se sobrepor a uma alternativa que falhou no fatiamento. Para suporte, pode sugerir somente campos seguros existentes no perfil ELEGOO, inicialmente `enable_support` e `support_on_build_plate_only`; outros ajustes aparecem apenas como observação não aplicável.
6. Antes de apresentar como mudança verificada, refatiar localmente qualquer combinação nova de orientação ou suporte proposta, comparar sucesso, avisos, tempo e massa com a base e preservar a malha. Se o fatiamento falhar ou a evidência for insuficiente, mostrar somente como hipótese sem botão de aplicar. Não inferir acabamento do rosto a partir de tempo ou massa.
7. A tela de revisão mostra os dados que sustentam cada proposta e permite selecionar uma por vez. Após confirmação, gerar uma nova cópia, converter e fatiar novamente. Não alterar origem, perfis locais ou projeto convertido existente. A prévia do ELEGOO Slicer continua sendo a verificação visual final.

## Regras de segurança e privacidade

- Nenhum 3MF do usuário, malha, imagem ou G-code entra no prompt ou em serviço de IA. A montagem do resumo fica em módulo testável, com lista positiva de campos e teste que bloqueia nomes, caminhos e conteúdo de geometria.
- `codex exec` recebe somente o resumo aprovado e trabalha em diretório vazio. O sandbox de leitura reduz permissões de escrita, mas não é apresentado como garantia absoluta de isolamento de todos os arquivos locais; o aplicativo não concede ferramentas próprias nem fornece caminhos do projeto ao agente.
- A saída do modelo nunca é executada como comando. O parser aceita somente JSON no esquema esperado, chaves locais permitidas, valores dentro de faixas e identificadores de candidata conhecidos. A confirmação humana e a validação do fatiador permanecem obrigatórias.
- Falta de Codex, autenticação, rede, saída inválida, cancelamento e timeout geram erro legível sem alterar o projeto. Logs não guardam prompt completo nem segredos. O resumo não é enviado automaticamente ao abrir o projeto.

## Alternativas consideradas

1. **Codex CLI como provedor opcional no app — escolhida.** Reutiliza a autenticação do Codex e o parser/fluxo de aprovação existentes, com processo separado e saída estruturada. Exige Codex instalado em cada computador que use essa opção.
2. API direta da OpenAI no app. Facilita limitar precisamente as ferramentas e a entrada, mas exige chave/API e administração de cobrança separadas da autenticação do Codex CLI.
3. CLI-Anything para gerar um CLI do MakerElegoo. É útil se a meta futura for o Codex operar o conversor pelo terminal, mas não faz o botão do aplicativo chamar o Codex; não é dependência desta mudança.

## Verificação necessária

- Testes de resumo que provam ausência de 3MF, caminhos, imagens, vértices, G-code e credenciais; consentimento negado não inicia processo.
- Testes de adaptador Codex com subprocesso falso: comandos/flags, diretório temporário, esquema, timeout, cancelamento, erros de autenticação e JSON inválido.
- Testes de recomendação: candidata reprovada ou não fatiada jamais aplicada; mudança de frente/perfis invalida análise; suporte só em chaves seguras e após fatiamento comparativo.
- Teste real com Codex usando apenas dados sintéticos ou resumo previamente aprovado, e teste real de fatiamento no ELEGOO Slicer para qualquer saída 3MF que seja declarada validada.
- Suíte completa, revisão de código, Graphify, Understand Anything, build Windows, smoke do EXE e integridade do ZIP.
