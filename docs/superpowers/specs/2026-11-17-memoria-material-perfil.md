# Especificação — Memória do Último Tipo de Material e Último Perfil Usado

Data: 2026-11-17  
Projeto: Conversor MakerWorld → ELEGOO (`Centauri Carbon 2`)

## 1. Problema e necessidade do usuário

Hoje, ao abrir o aplicativo ou trocar o tipo de material desejado (ex.: `PLA`, `ABS`, `PETG`):
- O seletor de filamento físico sempre começa em **`"Não sei informar"`**, mesmo quando o usuário imprime repetidamente com o mesmo material.
- Quando há mais de um perfil compatível para o mesmo material (ex.: `Elegoo PLA @ECC2` e `ENDER PLA`, ou múltiplos perfis customizados do usuário), [`select_material_profile`](../../../src/maker_elegoo/material_selection.py#L215) exige escolha manual todas as vezes (ou mantém o fallback padrão), sem lembrar que na última vez com **`PLA`** o usuário escolheu **`ENDER PLA`**.

## 2. Comportamento desejado

1. **Memória do último perfil por tipo de material (`last_profile_by_material`):**
   - Armazenar em `settings.json` um mapa normalizado `{tipo_material: nome_do_perfil}` (ex.: `{"PLA": "ENDER PLA", "ABS": "Elegoo ABS @ECC2"}`).
   - Quando um tipo de material é selecionado (no seletor global ou em um slot específico), verificar se existe um último perfil salvo para aquele tipo (`MaterialIdentity.label`, ex.: `"PLA"`):
     - Se esse perfil ainda existir na lista compatível com a máquina e bico atuais **e** sua identidade real resolvida por metadados (`extract_profile_material_identity`) corresponder exatamente ao material selecionado (`polymer` e `variant`), ele deve ser **pré-selecionado automaticamente** (sobrepondo empates de usuário/fabricante e substituindo o chute inicial vindo do `.3mf`).
     - Se o perfil salvo tiver sido apagado, for de outro bico/máquina ou tiver material divergente nos metadados resolvidos (ex.: `ABS-CF` salvo quando o usuário escolheu `ABS` puro), **recusar silenciosamente a memória** e aplicar a seleção padrão segura.

2. **Pré-seleção do último tipo de material utilizado (`last_physical_material`):**
   - Persistir em `settings.json` o último tipo de material realmente usado/confirmado pelo usuário (`last_physical_material`, vazio `""` enquanto o usuário nunca tiver usado).
   - Ao abrir o aplicativo (se houver valor salvo válido no combo) e ao analisar um projeto de **1 slot ativo** via `_inspect_file`, pré-selecionar automaticamente:
     - `physical_material_var` com o último tipo de material utilizado (`"PLA"` no exemplo);
     - o perfil correspondente pelo histórico (`"ENDER PLA"`, se válido), ou a seleção padrão por metadados caso não haja histórico para aquele tipo.
   - Em projetos **multisslot (2+ slots ativos)**: não sobrescrever materiais distintos entre slots com o material global único; aplicar a memória de perfil (`last_profile_by_material`) individualmente para o material alvo de cada slot.

3. **Preservação obrigatória das regras de segurança:**
   - **Nunca auto-confirmar:** `physical_filament_confirmed_var` e `slot_confirmed_vars` devem continuar iniciando **desmarcados (`False`)** ao abrir o app ou analisar um novo `.3mf`, exigindo o clique consciente do usuário na confirmação ("Confirmo que este filamento físico está carregado / planejado") antes de liberar a conversão.
   - **Nunca gravar sugestão vinda do `.3mf`:** a memória (`last_physical_material` e `last_profile_by_material`) só é atualizada a partir de escolhas/confirmações explícitas do usuário (seleção manual de perfil compatível, confirmação de filamento/slot ou execução de conversão validada pelo usuário), nunca pela leitura passiva de metadados do `.3mf` de origem.
   - Se o usuário editar manualmente o combo de perfil de um slot na sessão atual e em seguida confirmar, o novo perfil escolhido passa a ser o lembrado para aquele tipo de material; enquanto estiver na mesma sessão sem trocar o tipo de material, a escolha manual recém-feita para aquele slot é preservada.

## 3. Critérios de aceitação

- Selecionar `"PLA"` após ter usado/confirmado `"ENDER PLA"` pré-seleciona automaticamente `"ENDER PLA"`, mesmo com múltiplos perfis `PLA` competindo.
- Reabrir o aplicativo (nova instância com o mesmo `settings.json`) pré-seleciona o último tipo de material utilizado e seu respectivo último perfil, mantendo a confirmação física desmarcada (`False`) até o clique do usuário.
- Se nenhum material tiver sido salvo ainda (`settings.json` vazio), continua iniciando em `"Não sei informar"`.
- Se o perfil salvo for incompatível com o material (ex.: `ABS-CF` para `ABS`), ou não existir para o bico atual, não é selecionado.
- Toda a suíte existente (`test_ui_beginner_flow.py`, `test_material_selection.py`, `test_settings.py`) continua passando sem relaxar regras de segurança.
