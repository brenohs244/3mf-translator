# Professor de impressão: modos Offline e IA (Gemini)

## Intenção

Depois de traduzir um 3MF do MakerWorld para a ELEGOO Centauri Carbon 2, o aplicativo deve dizer se as configurações fazem sentido para **como a peça será usada**, para o **material escolhido** e para a **prioridade** do usuário. Ele explica cada mudança em linguagem simples e nunca aplica nada sem revisão.

## Problemas que motivam a mudança

- A IA e o Codex recebiam o material de **origem**, e não o escolhido. Um projeto PLA impresso em ABS era analisado como PLA.
- A altura de camada do autor era descartada em silêncio, porque o processo padrão era sempre o "Standard".
- O relatório usava nomes internos (`fan_max_speed`) e mostrava o tempo em segundos.
- O ajuste por IA exigia copiar e colar o resumo, e a chave Gemini era pedida a cada uso.
- A comparação de objetivos limitava a camada a 0,08–0,32 mm. Isso invalida o bico 0,8, cujo Standard usa 0,40 mm.

## Decisões

1. **Dois modos exclusivos, escolhidos na tela principal:**
   - **Offline (Professor local):** regras determinísticas, sem rede. É o padrão.
   - **IA (Gemini):** o modelo decide os ajustes e escreve a explicação. Não há mistura com as regras locais.
   - Os dois modos passam pela **mesma validação de limites** e pelo **mesmo diálogo de revisão**. Em ambos, o resultado é exportado e fatiado pelo ELEGOO Slicer.
   - Se a IA falhar (rede, cota ou resposta inválida), o aplicativo mostra o erro e oferece "Usar Professor offline desta vez". Nunca troca de modo em silêncio.
2. **Perguntas ao usuário:**
   - **Uso:** Decorativa · Funcional leve · Recebe força · Partes móveis/encaixes · Uso externo/calor.
   - **Prioridade:** Qualidade · Equilíbrio · Velocidade · Economia de material.
   - **Material:** é o perfil de filamento escolhido por slot, que já existe na tela.
3. **Processo sugerido pela camada original:** escolher o processo ELEGOO compatível cuja altura de camada resolvida é a mais próxima da do projeto. No empate, preferir Standard, depois Fine. Avisar quando a camada mudar mais de 0,02 mm.
4. **Limites invioláveis (os dois modos):**
   - **Processo:** paredes 1–8; topo/base 0–12; preenchimento 0–100%; padrão do preenchimento em {gyroid, rectilinear, grid, cubic}; costura em {aligned, back, nearest, random}; passar a ferro em {no ironing, top}; brim em {auto_brim, outer_only, no_brim} e 0–15 mm; velocidade da parede externa entre 30 mm/s e o valor do perfil (só reduz); camada entre `min_layer_height` e `max_layer_height` da máquina e ≤ 0,75 × bico.
   - **Filamento:** ventoinha da peça (máx./mín.), ventoinha de saliências, ventoinha auxiliar e exaustão entre 0 e o valor do perfil ELEGOO (só reduz).
   - **Proibido** alterar temperaturas, G-code, firmware, limites de máquina ou chaves ausentes do perfil resolvido. Temperaturas são apenas explicadas.
5. **Exaustão no ABS/ASA:** é proposta (30%), mas vem **desmarcada**, com aviso de odor e vapores e recomendação de ventilar o ambiente.
6. **Câmara:** a CC2 não controla a temperatura da câmara (`support_chamber_temp_control = 0`). Para ABS/ASA, o aplicativo orienta tampa fechada, pré-aquecimento da mesa e ausência de corrente de ar.
7. **Sem promessa mecânica:** o aplicativo não declara ganho de resistência sem ensaio. Tempo e material vêm do fatiamento.

## Modo IA: dados, chave e modelo

- **Envio:** somente um resumo textual com uso, prioridade, materiais de origem e destino, bico, os valores atuais das chaves permitidas, os limites de cada uma e, quando houver, tempo e gramas de um fatiamento anterior. Nunca o 3MF, a malha, o G-code, nomes de arquivo ou caminhos.
- **Consentimento:** explícito ao ativar o modo IA, com aviso de que, na camada gratuita, o Google pode usar os dados para melhorar seus serviços. O diálogo de revisão permite "Ver dados enviados".
- **Chave:** informada uma vez em **Configurações de IA** e guardada criptografada com DPAPI do Windows (só o usuário atual consegue ler), fora do `settings.json`. A variável de ambiente `GEMINI_API_KEY`, se existir, tem prioridade. Há botões "Testar conexão" e "Esquecer chave". A chave nunca aparece em logs, relatórios ou erros.
- **Modelo:**
  - Padrão `gemini-3.8-flash`, pelo bom raciocínio a baixo custo e por ter camada gratuita. O volume é de cerca de uma chamada por conversão.
  - Alternativa `gemini-3.5-flash-lite`, mais rápida e com cota maior, oferecida quando houver HTTP 429.
  - O modelo é configurável. "Testar conexão" consulta a lista de modelos da conta para confirmar a disponibilidade.
  - A resposta é exigida em JSON com schema (`responseMimeType` + `responseJsonSchema`).
  - A disponibilidade e as cotas devem ser reconfirmadas no Google AI Studio na implementação.

## Fora do escopo desta fase

Outras impressoras ELEGOO, alteração de temperaturas, análise de malha para detectar partes móveis automaticamente, e mudanças nos recursos de orientação. O ajuste manual por copiar/colar e o Codex saem do fluxo principal e ficam em **Ferramentas → Avançado**, sem novas funções.

## Verificação

Testes unitários para regras, limites, seleção de processo, rótulos, armazenamento da chave e cliente Gemini (com transporte simulado). Fatiamento real local de três projetos do usuário nos dois modos, conferindo no 3MF de saída que os valores aplicados são os aprovados. Os arquivos 3MF permanecem locais e fora do Git.
