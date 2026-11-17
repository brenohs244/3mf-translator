# Simulação de Fatiamento e Banco de Dados SQLite para Orçamento (`v0.3.0`)

## Contexto e objetivo

Permitir que o usuário execute uma **simulação de fatiamento** diretamente no **Maker → ELEGOO** sem precisar escolher nem gravar um arquivo `.3mf` permanente no disco, e registrar os dados físicos reais retornados pelo ELEGOO Slicer em um **banco SQLite local** (`maker_elegoo_quotes.db`) no mesmo computador para consumo por um futuro sistema externo de precificação/orçamento.

## Regras acordadas com o usuário

1. **Gravação estrita no botão de simular:** o registro no banco SQLite ocorre **exclusivamente** quando o usuário clica no botão **Simular fatiamento** (ou no item equivalente em `Ferramentas`) e o fatiamento é concluído com sucesso (`validation.success == True`). Conversões normais (`Traduzir para minha ELEGOO`), inspeções de projeto, prévias rápidas e comparações de objetivos **não** gravam automaticamente na tabela de simulações.
2. **Banco local no mesmo PC:** banco SQLite único (`maker_elegoo_quotes.db`), por padrão em `%APPDATA%\MakerElegoo\maker_elegoo_quotes.db` (respeitando `MAKER_ELEGOO_CONFIG_DIR` e sobrescrevível por `quote_db_path` em `settings.json` ou variável `MAKER_ELEGOO_QUOTE_DB`).
3. **Concorrência segura:** usar `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON` e `PRAGMA busy_timeout=5000`, permitindo leitura simultânea em modo `ro` por ferramentas externas sem travar durante novas simulações.
4. **Arquitetura recomendada ao sistema de orçamento:** o sistema de precificação/ERP deve ser desenvolvido **em projeto/repositório separado**, consumindo este SQLite como contrato de dados estável e versionado (`SCHEMA_VERSION = 1`).
5. **Documentação de integração no repositório:** incluir `docs/INTEGRATION_QUOTE_DB.md` explicando schema completo, exemplos SQL/Python/Node.js e recomendações de leitura segura e separação arquitetural.
6. **Privacidade e integridade (`AGENTS.md`):**
   - Manter `.3mf` e `.gcode` fora do Git, fora do banco SQLite e fora de serviços de IA.
   - Registrar apenas metadados técnicos e medições reais do fatiamento (`project_name`, `project_sha256`, placas, slots, tempo estimado e gramas).
   - Nunca relaxar confirmações obrigatórias de material da Seção 2.

---

## Componentes técnicos

### 1. Extração por slot no G-code (`src/maker_elegoo/slicer.py`)

- Manter `_gcode_metrics(path)` preservando compatibilidade atual (`tuple[int | None, float | None]`) e adicionar extração detalhada de massa por slot (`; filament used [g] = 12.34, 5.67`).
- Estender `PlateValidationMetric` e `ValidationResult` com `slot_filament_grams: tuple[float, ...] = ()` contendo os gramas usados por índice de slot quando informados no cabeçalho do G-code.

### 2. Repositório SQLite de simulações (`src/maker_elegoo/quote_db.py`)

- **Descoberta de caminho:** `quote_db_path(custom_path=None)` usa, nesta ordem: `custom_path`, `os.getenv("MAKER_ELEGOO_QUOTE_DB")`, `settings.get("quote_db_path")` e fallback `settings_path().parent / "maker_elegoo_quotes.db"`.
- **Schema (`SCHEMA_VERSION = 1` em `PRAGMA user_version` e `schema_metadata`):**
  - `simulations`: `id`, `created_at`, `app_version`, `project_name`, `project_sha256`, `machine_name`, `nozzle_mm`, `process_name`, `layer_height_mm`, `purpose`, `priority`, `scale_percent`, `plate_count`, `part_count`, `estimated_seconds`, `filament_grams`, `size_x_mm`, `size_y_mm`, `size_z_mm`, `has_supports`, `short_layers_under_6s`, `max_volumetric_flow_mm3_s`, `gcode_summary_json`.
  - `simulation_plates`: `id`, `simulation_id`, `plate_index`, `estimated_seconds`, `filament_grams`, `layer_count`, `max_nozzle_temp_c`, `max_bed_temp_c`.
  - `simulation_slots`: `id`, `simulation_id`, `slot_index`, `material_type`, `profile_name`, `color_hex`, `readiness`, `filament_grams`.
  - `v_simulations_summary` (`VIEW`): consolida cada simulação com horas decimais e resumo concatenado de materiais/perfis para leitura direta por sistemas de orçamento ou Excel/Power BI.
- **`record_simulation(...)`:** grava em transação única (`simulations` + `simulation_plates` + `simulation_slots`) e retorna `SimulationRecordResult(simulation_id, db_path, ...)`.
- **Cálculo honesto de `filament_grams` por slot:** usa exatamente `slot_filament_grams` do G-code por índice do slot quando disponível; se houver exatamente 1 slot ativo e o G-code só informar o total geral, atribui o total a esse slot; em múltiplos slots sem quebra no G-code, grava `NULL` em vez de estimar divisão igual.

### 3. Configuração em `src/maker_elegoo/settings.py`

- Adicionar `"quote_db_path": ""` em `DEFAULTS`.

### 4. Fluxo de UI em `src/maker_elegoo/ui.py`

- Novo botão **`Simular fatiamento`** (`self.simulate_button`) na barra `actions`, além de itens no menu `Ferramentas`:
  - `Simular fatiamento (registrar para orçamento)`
  - `Configurar banco de orçamentos (SQLite)...` (abre diálogo simples para escolher arquivo `.db`, abrir pasta do banco ou restaurar padrão).
- **Fluxo `_simulate()`:**
  - Valida projeto, ELEGOO Slicer, `validate_slot_material_plan(...)`, confirmações da Seção 2 (seguindo as mesmas salvaguardas de `_convert()` — nunca presume material nem auto-confirma silenciosamente) e escala (`_parse_scale_request()` / `analyze_scale_risk()`).
  - Calcula conselhos locais (`advise_offline`) sem precisar pedir diálogo de arquivo nem chamada externa de IA (mantendo simulação rápida, determinística e offline).
  - Exporta e fatia em `tempfile.TemporaryDirectory(prefix="maker-elegoo-sim-")` em thread separada via `self.simulate_queue` + `_poll_simulate` (registrado em `_POLL_HANDLE_ATTRS` para teardown limpo).
  - Ao concluir com `result.success`: grava no SQLite via `record_simulation(...)`, mostra relatório completo com tempo, peso por placa/slot, dimensões estimadas e ID/caminho do registro salvo no SQLite, limpando toda pasta temporária ao sair.
  - Em `_convert()` (`Traduzir para minha ELEGOO`): **não** chama `record_simulation(...)`.

### 5. Documentação de integração (`docs/INTEGRATION_QUOTE_DB.md`)

- Guia técnico passo a passo dentro do projeto explicando:
  - Por que desenvolver o sistema de orçamento em projeto separado usando SQLite como fronteira limpa;
  - Caminho do banco, configuração `WAL` e exemplos prontos em SQL, Python e Node.js com leitura segura em modo somente leitura;
  - Dicionário de dados de todas as tabelas, colunas, `v_simulations_summary` e modelo de fórmula para precificação.
