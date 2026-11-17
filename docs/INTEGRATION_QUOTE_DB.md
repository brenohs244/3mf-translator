# Integração Externa — Banco SQLite de Simulações para Orçamento (`Schema v1`)

Este documento orienta o desenvolvimento de um sistema externo de **precificação / orçamento rápido** que leia as medições reais geradas pelo botão **`Simular fatiamento`** do **Maker → ELEGOO**.

---

## 1. Recomendação de arquitetura: sistema separado x dentro deste projeto

**Recomendação:** crie o sistema de orçamentos e precificação **em um repositório / projeto separado**, conectando-se a este banco SQLite como **contrato de dados**.

| Critério | Sistema separado (Recomendado) | Dentro do mesmo código (`maker_elegoo`) |
|---|---|---|
| **Responsabilidade** | O Maker → ELEGOO foca em fatiamento/engenharia/ELEGOO Slicer; o orçamentador foca em custo, lucro, cliente, frete e PDF. | Mistura lógica técnica de 3MF com regras comerciais, impostos e preços de rolo. |
| **Stack tecnológica** | Liberdade total: Web (FastAPI/React/Next), Desktop, Node.js, C#, Power BI ou Excel — basta ler SQLite. | Preso ao ciclo de Tkinter e empacotamento Windows do tradutor. |
| **Atualizações** | Você atualiza preços, taxas de marketplace (Shopee/ML) ou margem sem recompilar nem arriscar o tradutor. | Cada atualização do tradutor exigiria cuidado redobrado para não afetar telas comerciais. |
| **Confiabilidade dos dados** | O Maker → ELEGOO atua apenas como **produtor** das simulações físicas; seu sistema atua como **consumidor** em modo somente-leitura (`mode=ro`). | Risco de acoplamento entre preferências do fatiador e banco comercial. |

> **Boa prática ao começar seu novo projeto:** crie nele uma pequena tabela própria (ou banco próprio `pricing.db` + `ATTACH DATABASE ... AS maker`) guardando custos unitários de filamento (`R$/kg` por material/marca), tarifa de energia (`R$/kWh`), taxa de depreciação/hora-máquina e histórico de cotações enviadas aos clientes referenciando `simulations.id` (e `project_sha256`). Assim você **nunca modifica nem escreve** no arquivo gerenciado pelo Maker → ELEGOO.

---

## 2. Onde fica o banco SQLite e quando ele é gravado

- **Caminho padrão no Windows:**
  ```text
  %APPDATA%\MakerElegoo\maker_elegoo_quotes.db
  ```
- **Sobrescritas aceitas (em ordem de prioridade):**
  1. Configuração na interface: menu **`Ferramentas → Configurar banco de orçamentos (SQLite)...`** (salvo em `quote_db_path` no `settings.json`);
  2. Variável de ambiente: `MAKER_ELEGOO_QUOTE_DB`;
  3. Padrão na mesma pasta de preferências (`%APPDATA%\MakerElegoo\maker_elegoo_quotes.db`, ou `<MAKER_ELEGOO_CONFIG_DIR>\maker_elegoo_quotes.db` no modo portátil).
- **Quando há gravação:**
  - **Exclusivamente** ao clicar em **`Simular fatiamento`** (ou **`Ferramentas → Simular fatiamento (registrar para orçamento)`**) e somente quando o fatiamento no ELEGOO Slicer **passar com sucesso**.
  - Conversões normais (**`Traduzir para minha ELEGOO`**) e simulações que falhem no fatiador **não** gravam registros neste banco.
- **Concorrência (`WAL`):** o Maker → ELEGOO abre o banco com `PRAGMA journal_mode=WAL` e `PRAGMA busy_timeout=5000`. O sistema externo consegue ler em tempo real enquanto o aplicativo está aberto.

---

## 3. Contrato do Schema (`user_version = 1`)

Antes de consultar, seu sistema pode conferir a versão do schema:

```sql
PRAGMA user_version; -- Esperado: 1
SELECT value FROM schema_metadata WHERE key = 'schema_version'; -- Esperado: '1'
```

### Tabela `simulations` (1 registro por simulação concluída)

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER` PK | ID sequencial da simulação (`lastrowid`). |
| `created_at` | `TEXT` | Data/hora ISO-8601 com fuso horário (ex.: `2026-11-17T12:15:00-03:00`). |
| `app_version` | `TEXT` | Versão do Maker → ELEGOO que gerou o registro (ex.: `0.3.0`). |
| `project_name` | `TEXT` | Nome do arquivo `.3mf` de origem (ex.: `suporte_camera.3mf`), sem expor caminhos sensíveis nem embutir binários. |
| `project_sha256` | `TEXT` | Hash SHA-256 do `.3mf` de origem (útil para reconhecer re-simulações da mesma peça). |
| `machine_name` | `TEXT` | Perfil de máquina ELEGOO usado. |
| `nozzle_mm` | `TEXT` | Diâmetro do bico (ex.: `0.4`). |
| `process_name` | `TEXT` | Perfil de processo ELEGOO (ex.: `0.20mm Standard @Elegoo CC2 0.4 nozzle`). |
| `layer_height_mm` | `REAL` \| `NULL` | Altura de camada do processo em mm. |
| `purpose` | `TEXT` | Objetivo de uso selecionado (`decorativa`, `funcional`, `esforco`, etc.). |
| `priority` | `TEXT` | Prioridade selecionada (`qualidade`, `equilibrio`, `velocidade`, `economia`). |
| `scale_percent` | `REAL` | Escala efetiva aplicada (`100.0` se tamanho original; ex. `125.0` se redimensionada). |
| `plate_count` | `INTEGER` | Total de placas fatiadas nesta simulação. |
| `part_count` | `INTEGER` | Quantidade de objetos/instâncias no projeto. |
| `estimated_seconds` | `INTEGER` | **Tempo total estimado de impressão em segundos** (soma real do G-code de todas as placas). |
| `filament_grams` | `REAL` | **Massa total estimada de filamento em gramas** (soma real do G-code de todas as placas). |
| `size_x_mm`, `size_y_mm`, `size_z_mm` | `REAL` \| `NULL` | Dimensões finais do conjunto em milímetros já ajustadas pela escala (úteis para caixa/embalagem/frete). |
| `has_supports` | `INTEGER` | `1` se suportes estavam ativados na simulação; `0` caso contrário. |
| `short_layers_under_6s` | `INTEGER` | Quantidade de camadas rápidas (< 6 s) detectadas na auditoria do G-code (indicador de risco de acabamento). |
| `max_volumetric_flow_mm3_s` | `REAL` \| `NULL` | Vazão volumétrica máxima estimada em `mm³/s`. |
| `gcode_summary_json` | `TEXT` | JSON extra com avisos do fatiador, achados da auditoria de G-code e lista bruta de gramas por slot. |

### Tabela `simulation_plates` (`simulation_id` → `simulations.id`)

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER` PK | Identificador da linha da placa. |
| `simulation_id` | `INTEGER` FK | Referência para `simulations(id)`. |
| `plate_index` | `INTEGER` | Índice da placa (`1`, `2`, ...). |
| `estimated_seconds` | `INTEGER` \| `NULL` | Tempo estimado somente desta placa em segundos. |
| `filament_grams` | `REAL` \| `NULL` | Filamento estimado somente desta placa em gramas. |
| `layer_count` | `INTEGER` \| `NULL` | Total de camadas da placa (da auditoria real do G-code). |
| `max_nozzle_temp_c` | `REAL` \| `NULL` | Maior temperatura de bico observada no G-code (°C). |
| `max_bed_temp_c` | `REAL` \| `NULL` | Maior temperatura de mesa observada no G-code (°C). |

### Tabela `simulation_slots` (`simulation_id` → `simulations.id`)

Contém **apenas os slots ativos** usados pelas placas do projeto:

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER` PK | Identificador do slot. |
| `simulation_id` | `INTEGER` FK | Referência para `simulations(id)`. |
| `slot_index` | `INTEGER` | Número do slot (`1`, `2`, ...). |
| `material_type` | `TEXT` | Identidade do material confirmado (ex.: `PLA`, `PETG`, `ABS`, `ASA`, `TPU 95A`). |
| `profile_name` | `TEXT` | Nome exato do perfil escolhido na Seção 2/avançado (ex.: `ENDER PLA`). |
| `color_hex` | `TEXT` | Cor original declarada no projeto (`#RRGGBB`). |
| `readiness` | `TEXT` | Estado selecionado na Seção 2 (`carregado` ou `planejado`). |
| `filament_grams` | `REAL` \| `NULL` | Massa exata deste slot em gramas quando informada pelo G-code (`; filament used [g] = ...`) ou para 1 slot único. Em múltiplos slots cujo G-code não tenha divisão individual, permanece **`NULL`** (nunca é chutado). |

### View pronta: `v_simulations_summary`

Inclui todas as colunas de `simulations` acrescidas de:
- `estimated_hours` (`REAL`): `estimated_seconds / 3600.0` (arredondado para 4 casas);
- `slot_count` (`INTEGER`): total de slots ativos gravados;
- `materials_summary` (`TEXT`): ex. `"PLA"` ou `"PLA + ABS"`;
- `profiles_summary` (`TEXT`): ex. `"ENDER PLA"` ou `"ENDER PLA + Elegoo ABS @ECC2"`.

---

## 4. Como ler com segurança no sistema externo

Sempre abra o banco com URI em modo **somente leitura (`?mode=ro`)** e `busy_timeout`:

### SQL direto (DB Browser / DBeaver / ODBC / BI)

```sql
-- Listar as 20 simulações mais recentes já resumidas para orçamento
SELECT
    id,
    created_at,
    project_name,
    machine_name,
    nozzle_mm,
    process_name,
    plate_count,
    estimated_seconds,
    estimated_hours,
    filament_grams,
    materials_summary,
    profiles_summary,
    has_supports,
    size_x_mm,
    size_y_mm,
    size_z_mm
FROM v_simulations_summary
ORDER BY id DESC
LIMIT 20;

-- Buscar consumo por material/perfil de uma simulação específica
SELECT slot_index, material_type, profile_name, color_hex, filament_grams
FROM simulation_slots
WHERE simulation_id = :simulation_id
ORDER BY slot_index;
```

### Exemplo em Python (`sqlite3` nativo)

```python
import sqlite3
from contextlib import closing
from pathlib import Path
import os

def open_quotes_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        env_path = os.getenv("MAKER_ELEGOO_QUOTE_DB")
        db_path = Path(env_path) if env_path else Path(os.environ["APPDATA"]) / "MakerElegoo" / "maker_elegoo_quotes.db"
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

with closing(open_quotes_readonly()) as conn:
    latest = dict(conn.execute("SELECT * FROM v_simulations_summary ORDER BY id DESC LIMIT 1").fetchone())
    slots = [dict(r) for r in conn.execute(
        "SELECT * FROM simulation_slots WHERE simulation_id = ? ORDER BY slot_index",
        (latest["id"],),
    ).fetchall()]
```

### Exemplo em Node.js (`better-sqlite3`)

```js
const path = require("node:path");
const Database = require("better-sqlite3");

const dbPath =
  process.env.MAKER_ELEGOO_QUOTE_DB ||
  path.join(process.env.APPDATA, "MakerElegoo", "maker_elegoo_quotes.db");

const db = new Database(dbPath, { readonly: true, timeout: 5000 });
const latest = db.prepare("SELECT * FROM v_simulations_summary ORDER BY id DESC LIMIT 1").get();
const slots = latest
  ? db.prepare("SELECT * FROM simulation_slots WHERE simulation_id = ? ORDER BY slot_index").all(latest.id)
  : [];
```

---

## 5. Modelo sugerido de cálculo de custo no seu orçamentador

Com os dados gravados pelo Maker → ELEGOO, a fórmula base de custo industrial fica limpa e transparente:

1. **Custo de filamento (`C_mat`):**
   - Para cada slot com `filament_grams != NULL`: `(filament_grams / 1000.0) * preco_kg[material_type / profile_name]`.
   - Se algum registro antigo/multisslot tiver `filament_grams IS NULL`, use `simulations.filament_grams / 1000.0 * preco_kg_fallback` (ou média ponderada cadastrada no seu sistema).
   - Aplique multiplicador de perda/purga/refugo (ex.: `1.08` a `1.15`).
2. **Energia elétrica (`C_energia`):**
   - `estimated_hours * potencia_media_kw * tarifa_kwh` (ex.: `0.12 kW` a `0.18 kW` médios conforme material/mesa).
3. **Hora-máquina + manutenção + depreciação (`C_maq`):**
   - `estimated_hours * custo_hora_maquina`.
4. **Setup operacional por placa e acabamentos (`C_setup`):**
   - `plate_count * custo_troca_e_preparo_placa + (custo_remocao_suporte if has_supports else 0)`.
5. **Margem comercial e taxas:**
   - Preço final = `(C_mat + C_energia + C_maq + C_setup + C_embalagem) * (1 + risco) / (1 - taxa_marketplace - imposto - margem_liquida)`.
   - Use `size_x_mm`, `size_y_mm` e `size_z_mm` para escolher a caixa/frete corretos antes de fechar o orçamento.
