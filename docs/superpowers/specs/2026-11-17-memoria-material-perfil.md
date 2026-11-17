# Especificação — Memória Completa da Seção 2 e Botão "Confirmar tudo"

Data: 2026-11-17  
Projeto: Conversor MakerWorld → ELEGOO (`Centauri Carbon 2`)

## 1. Problema e necessidade do usuário

Ao preparar impressões seguidas na interface:
- O usuário precisa selecionar novamente na **Seção 2 (`2  Sua ELEGOO e Filamento Físico`)** o material na impressora (`PLA`, `ABS`, etc.), a situação do carretel (`Já carregado` vs. `Planejado`) e, quando há múltiplos perfis compatíveis (ex.: `Elegoo PLA @ECC2` e `ENDER PLA`), escolher manualmente o perfil favorito toda vez.
- Em projetos com vários slots (ou na revisão diária rápida de Seção 2), não há um atalho único para revisar as escolhas já pré-selecionadas e marcar todas as confirmações da Seção 2 com segurança.

## 2. Comportamento desejado

### A. Memória de todas as opções da Seção 2 (`settings.json`)

Todas as escolhas conscientes feitas pelo usuário na Seção 2 são persistidas em `settings.json` e restauradas automaticamente na abertura do app e após analisar um novo projeto:

1. **`Bico instalado` (`nozzle`):** já persistido em `settings.json`; mantém o último bico selecionado compatível com a máquina.
2. **`Filamento na impressora` (`last_physical_material`):** armazena o último tipo de material escolhido/confirmado pelo usuário (ex.: `"PLA"`). Inicia vazio `""` na primeira execução (exibindo `"Não sei informar"`).
3. **`Situação do carretel` (`last_material_readiness`):** armazena `"carregado"` ou `"planejado"` (padrão `"carregado"` se ausente/inválido), preservando a escolha mesmo ao analisar um novo `.3mf`.
4. **`Último perfil por tipo de material` (`last_profile_by_material`):** mapa normalizado `{material_label: nome_do_perfil}` (ex.: `{"PLA": "ENDER PLA", "ABS": "Elegoo ABS @ECC2"}`).
   - Ao selecionar um tipo de material (na abertura, após `_inspect_file` em projeto de 1 slot, ao trocar `physical_material_combo` ou ao trocar `slot_target_vars[slot]` em multisslot), [`select_material_profile`](../../../src/maker_elegoo/material_selection.py) consulta `preferred_profile_name` para aquele material:
     - **Só pré-seleciona** o perfil memorizado se ele existir na lista compatível com máquina/bico atuais **e** sua identidade real resolvida por metadados (`extract_profile_material_identity`) bater exatamente com `polymer` e `variant` solicitados (nunca aplica `PLA-CF` ou `ABS-CF` quando o usuário pediu `PLA` ou `ABS` puro).
     - Caso o perfil salvo tenha sido apagado, incompatibilizado ou alterado em disco para outro polímero, descarta a preferência com segurança e aplica as regras normais de desempate/alerta.

### B. Pré-seleção sem auto-confirmação e proteção contra metadados do `.3mf`

- **Nunca auto-confirmar:** as caixas `Confirmo que este filamento físico está carregado` e `Confirmar Slot N` continuam iniciando **desmarcadas (`False`)** ao abrir o aplicativo e a cada novo projeto analisado (`_inspect_file`), deixando os valores pré-selecionados apenas para o usuário revisar e confirmar explicitamente.
- **Nunca memorizar chutes do `.3mf`:** a memória só grava escolhas reais feitas pelo usuário (troca manual de material/perfil/situação do carretel, marcação de confirmação ou execução de conversão).
- **Projetos multisslot (`2+` slots ativos):** não sobrescrevem materiais distintos de slots diferentes pelo `last_physical_material` global, mas pré-selecionam em cada slot o último perfil memorizado correspondente ao material daquele slot (ou escolhido manualmente para o slot).

### C. Botão extra **`Confirmar tudo`** na Seção 2

- Adicionar botão **`Confirmar tudo`** (`self.confirm_all_section2_btn`) na Seção 2 ao lado da caixa de confirmação.
- Ao clicar em **`Confirmar tudo`**:
  - **Sem projeto carregado:** valida que `physical_material_var` não está em `"Não sei informar"` e marca `physical_filament_confirmed_var = True` (atualizando memória/status).
  - **Projeto de 1 slot ativo:** valida o material alvo, garante que há um perfil selecionado válido e compatível por metadados (tentando aplicar o último perfil salvo se ainda não aplicado manualmente) e marca `physical_filament_confirmed_var = True` + `slot_confirmed_vars[slot] = True`. Se houver erro/ambiguidade não resolvida (ex.: `"Não sei informar"` ou 2 perfis empatados sem escolha prévia), **não marca confirmação**, exibe o motivo no slot/`status_var` e mantém o bloqueio seguro.
  - **Projeto multisslot (`2+` slots ativos):** valida todos os slots ativos; se todos tiverem material alvo válido e perfil compatível sem divergência/ambiguidade, marca todas as confirmações `slot_confirmed_vars[s] = True` e `physical_filament_confirmed_var = True`, salvando o perfil lembrado por material e atualizando o cartão pré-conversão. Se algum slot estiver inválido/pendente/ambíguo, **não confirma esse(s) slot(s)**, destaca o problema em `section2_slots_frame` e orienta o usuário.

## 3. Critérios de aceitação

- Abertura do app e análise de `.3mf` restauram `nozzle`, `last_physical_material`, `last_material_readiness` e `last_profile_by_material` (quando já existem no `settings.json`), mantendo confirmações em `False`.
- Trocar para `PLA` (ou voltar de `ABS` para `PLA`) pré-seleciona automaticamente `ENDER PLA` quando este foi o último perfil usado para `PLA`, inclusive vencendo empate com outros perfis `PLA`.
- Clicar em `Confirmar tudo` marca todas as confirmações válidas da Seção 2 (1 slot ou multisslot) e libera o botão de conversão; se algum item estiver inválido/ambíguo ou em `"Não sei informar"`, bloqueia com segurança sem confirmar o item inválido.
- Toda a suíte existente (`unittest`) passa sem quebrar as garantias de não presumir o `.3mf` na primeira execução.
