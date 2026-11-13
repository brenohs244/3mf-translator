# Plano de Implementação: Professor de Impressão (Offline & IA)

## Objetivo
Implementar a funcionalidade do "Professor de Impressão" com dois modos operacionais exclusivos:
1. **Modo 100% Offline (Local):** Regras determinísticas e lógicas de manufatura aditiva para segurança mecânica, sem tocar na internet.
2. **Modo IA (Google Gemini):** A IA atua como consultora direta sugerindo parâmetros e justificativas com base no contexto, persistindo a chave de forma segura no Windows sem necessidade de colar toda vez.
Ambos os modos passam pelo mesmo motor estrito de validação de limites (processo e filamento) e exibição amigável ao usuário.

---

## Etapas de Implementação (Metodologia TDD & Superpowers)

### Etapa 1: Armazenamento Seguro de Chave de API e Configurações
- Criar módulo para persistência segura no Windows (DPAPI via `ctypes` ou fallback protegido no perfil do usuário local).
- Estender `settings.py` para armazenar:
  - `mode`: `"offline"` ou `"ai"`
  - `purpose`: `"decorativa"`, `"funcional_leve"`, `"esforco"`, `"moveis"`, `"externa"`
  - `priority`: `"qualidade"`, `"equilibrio"`, `"velocidade"`, `"economia"`
  - `ai_model`: `"gemini-3.8-flash"` (com fallback para `"gemini-3.5-flash-lite"`)

### Etapa 2: Motor Compartilhado de Regras e Limites (`professor.py`)
- Definir constantes invioláveis de limites (`SAFE_PROCESS_KEYS`, `SAFE_FILAMENT_KEYS`).
- Implementar `validate_change(scope, key, value, plan, slot=None)`.
- Implementar as regras do modo **Offline**:
  - Peça que recebe força / funcional: paredes reforçadas, infill giroscópico, alertas de camada.
  - Peça decorativa: infill moderado, costura escondida.
  - Partes móveis: alertas de tolerância dimensional e compensação de pé de elefante.
  - Troca para ABS/ASA: controle estrito de ventoinha (máx 40%, sugerindo 25% em esforço mecânico), brim reforçado, aviso de câmara fechada e exaustão desmarcada por padrão.
- Implementar `apply_advice` para gerar cópia atualizada do `ConversionPlan`.

### Etapa 3: Integração Direta com Google Gemini (`ai_client.py` / `ai.py`)
- Implementar chamada direta com JSON Schema estruturado (`responseJsonSchema` / `responseMimeType: "application/json"`).
- Inclusão do contexto real no payload: materiais de **destino reais** (corrigindo bug de troca para ABS), material de origem, bico, parâmetros atuais e limites aceitáveis.
- Enviar prompt pedindo que o modelo assuma o papel de um Professor Especialista em Impressão 3D e justifique didaticamente cada alteração em português claro.
- Sanitização rigorosa das respostas recebidas passando pelo motor `validate_change`.

### Etapa 4: Apresentação e Tradução para o Usuário (`labels.py`)
- Rótulos amigáveis em português (`"wall_loops"` -> `"Paredes perimétricas"`, `"fan_max_speed"` -> `"Ventoinha de resfriamento"`).
- Conversão de durações para formato legível (`1h 45min` em vez de segundos brutos).
- Formatação de comparações (`220 °C → 250 °C`).

### Etapa 5: Seleção de Processo por Altura de Camada Original (`mapping.py`)
- Em `suggest_process`, ler a altura de camada do arquivo original Bambu/Orca.
- Comparar com os perfis de processo ELEGOO instalados para selecionar automaticamente o mais próximo (ex: projeto 0.12mm seleciona perfil `0.12mm Fine`, e não `Standard 0.20mm` arbitrário).
- Criar alerta informativo (`Finding`) caso haja discrepância de camada.

### Etapa 6: Interface Gráfica Unificada (`ui.py`)
- Seção no painel principal para seleção do modo: **Professor Offline** ou **Professor com IA (Gemini)**.
- Seleção direta do Uso da Peça e Prioridade.
- Botão/menu para configurar a Chave de API Google (com teste de conexão rápido e salvar de vez).
- Janela de diálogo pré-conversão apresentando os conselhos do Professor:
  - Checkboxes selecionáveis (com os recomendados pré-marcados).
  - Explicação didática do "Porquê".
  - Alertas em destaque (ex: tampa fechada para ABS, vapores/odor).
- Relatório final reestruturado e compreensível para qualquer usuário.

### Etapa 7: Testes Automatizados e Validação
- Testes unitários para regras offline, serialização, limites do Gemini e seleção de camada.
- Teste de integração do fluxo completo com simulação do fatiador.
- Validação real com os 3MFs locais existentes (`Gardena_quick_connectors.3mf`, `3DBenchy+pruebas+ABS.3mf`).
