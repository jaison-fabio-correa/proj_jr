# proj-jr

Pipeline de dados históricos da Fórmula 1, com arquitetura em camadas
`raw`, `refined` e `mart`, banco DuckDB e dashboard em Streamlit.

## Visão geral

O projeto transforma arquivos CSV históricos em uma base analítica reproduzível:

```text
raw/*.csv
    │
    ▼
pipeline.ingestao ──► schema raw
    │
    ▼
pipeline.transformacao ──► schema refined
    │
    ▼
pipeline.mart ──► schema mart
    │
    ▼
painel.py ──► app.py ──► Streamlit
```

O banco local é `olist.duckdb`. Ele é gerado durante a execução e não deve ser
versionado.

## Requisitos

- Python 3.13 ou superior.
- [uv](https://docs.astral.sh/uv/) para ambiente e dependências.
- Windows, Linux ou macOS.

Dependências de produção:

- DuckDB: armazenamento e SQL analítico.
- pandas: leitura dos CSVs e DataFrames.
- Plotly: gráficos do dashboard.
- Streamlit: interface web.

Dependências de desenvolvimento:

- pytest e pytest-cov: testes e cobertura.
- Ruff: formatação e lint PEP 8.

## Instalação

Na raiz do projeto:

```bash
uv sync
```

O comando cria ou atualiza o ambiente virtual e instala as dependências
registradas em [pyproject.toml](./pyproject.toml) e [uv.lock](./uv.lock).

## Execução do pipeline

Execute as camadas nesta ordem:

```bash
uv run python -m pipeline.ingestao
uv run python -m pipeline.transformacao
uv run python -m pipeline.mart
```

Cada etapa é idempotente: as tabelas são recriadas com `CREATE OR REPLACE`.

### Camada RAW

Implementada em [pipeline/ingestao.py](./pipeline/ingestao.py).

- Lê os 14 CSVs da pasta `raw/`.
- Usa `encoding="utf-8"` e `dtype=str`.
- Mantém nomes de colunas, ordem, linhas e valores de origem.
- Campos vazios chegam como nulos no DuckDB.
- Não deduplica, corrige, preenche ou normaliza dados.
- Valida todos os arquivos antes de abrir o banco.
- Cria uma tabela `raw.<nome_do_arquivo>` para cada CSV.

Arquivos esperados:

`circuits`, `constructor_results`, `constructor_standings`, `constructors`,
`driver_standings`, `drivers`, `lap_times`, `pit_stops`, `qualifying`, `races`,
`results`, `seasons`, `sprint_results` e `status`.

Se faltar um arquivo, a execução termina com `SystemExit(1)` e nenhuma tabela é
gravada.

### Camada REFINED

Implementada em [pipeline/transformacao.py](./pipeline/transformacao.py).

- Lê exclusivamente `raw` e grava exclusivamente `refined`.
- Preserva as 14 tabelas e todas as colunas.
- Converte IDs, posições e contagens para `INTEGER`.
- Converte pontos para `DECIMAL(18, 6)`.
- Converte coordenadas para `DOUBLE`.
- Converte datas sem horário para `DATE`.
- Mantém horários de relógio como `TIME`.
- Converte voltas e durações para `INTERVAL`.
- Mantém textos como `VARCHAR`.
- Usa `CAST` e `strptime`, nunca `TRY_CAST`, `try_strptime` ou coerção para
  nulo.
- Em caso de conversão inválida, informa tabela, coluna e valor de exemplo e
  encerra com `SystemExit(1)`.

O marcador textual `\N`, usado pelos arquivos de origem para representar valor
ausente, é tratado como nulo nesta camada antes da conversão de tipo.

### Camada MART

Implementada em [pipeline/mart.py](./pipeline/mart.py).

As 11 tabelas analíticas materializadas são:

- `overview_kpis`: indicadores globais.
- `nationality_stats`: títulos, vitórias e pódios por nacionalidade.
- `constructor_titles_by_decade`: títulos de construtores por década.
- `constructor_wins_by_year`: vitórias de construtores por ano.
- `hall_of_fame`: ranking histórico de pilotos.
- `season_kpis`: indicadores de cada temporada.
- `championship_progression`: evolução acumulada de pontos por piloto.
- `championship_gap`: distância do líder para o segundo e terceiro colocados.
- `grid_performance`: ganho médio de posições na corrida.
- `pit_stop_performance`: média e menor duração de pit stop.
- `dnf_reliability`: abandonos por construtor e categoria de incidente.

Todos os cálculos e agregações ficam nessa camada. O dashboard não recalcula
métricas sobre os dados.

## Dashboard

O ponto de entrada é [app.py](./app.py). A camada de leitura e os construtores
de gráficos ficam em [painel.py](./painel.py).

Execute com:

```bash
uv run streamlit run app.py
```

### Aba panorâmica histórica

Apresenta:

- Total de temporadas, pilotos campeões, equipes campeãs e GPs.
- Nacionalidade com mais títulos.
- Vitórias por nacionalidade.
- Títulos de construtores por década.
- Evolução de vitórias por construtor.
- Hall da fama com títulos, vitórias, pódios, poles e eficiência.

### Aba de análise por temporada

Permite selecionar o ano e apresenta:

- Campeão de pilotos e construtores.
- Pontos dos campeões.
- Corridas e abandonos.
- Progressão do campeonato rodada a rodada.
- Diferença para o líder.
- Ganho ou perda de posições no grid.
- Performance de pit stops.
- Abandonos por categoria de incidente.

O dashboard usa carregamento cacheado dos marts, filtros simples e componentes
nativos do Streamlit, sem CSS customizado.

## Testes e qualidade

Execute a suíte completa com cobertura:

```bash
uv run pytest --cov
```

Resultado de referência atual:

```text
9 passed
TOTAL: 98%
```

Os testes em [test/test_pipeline.py](./test/test_pipeline.py):

- usam DuckDB real criado em `tmp_path`;
- inventam os CSVs e registros necessários;
- não abrem `olist.duckdb` nem leem `raw/` do projeto;
- verificam ingestão, conversões, falhas, idempotência, marts, formatação e
  gráficos.

Verifique formatação e lint:

```bash
uv run ruff format --check .
uv run ruff check .
```

O padrão Ruff está configurado no [pyproject.toml](./pyproject.toml) com limite
de 79 caracteres e regras de erros de sintaxe, imports e qualidade básica.

## Estrutura do projeto

```text
proj_jr/
├── app.py                    # Página Streamlit
├── painel.py                 # Leitura, formatação e gráficos
├── pipeline/
│   ├── db.py                 # Conexão DuckDB e schemas
│   ├── ingestao.py           # CSVs → raw
│   ├── transformacao.py      # raw → refined
│   └── mart.py               # refined → mart
├── raw/                      # CSVs locais de origem
├── test/
│   ├── conftest.py           # Descoberta do pacote nos testes
│   └── test_pipeline.py      # Suíte pytest
├── pyproject.toml            # Metadados e dependências
├── uv.lock                   # Dependências fixadas
├── .gitignore                # Arquivos locais ignorados
└── olist.duckdb              # Banco gerado localmente
```

## Convenções e decisões

- Os comandos são executados a partir da raiz do projeto.
- O banco padrão é `olist.duckdb` na raiz.
- A ausência de dependências deve ser resolvida com `uv sync`.
- As camadas usam schemas separados para evitar escrita acidental em camadas
  anteriores.
- Durações de voltas e paradas são `INTERVAL`; horários de relógio são `TIME`.
- O projeto não possui, neste momento, um módulo `relatorio`; a especificação
  de testes referente a esse artefato permanece não aplicável até sua criação.

## Histórico de entregas

- `Geração da camada RAW`
- `Geração da camada REFINED`
- `Inclusão geração camada mart e dashboard`
- `Inclusão pytest`
- `Inclusão gitignore`
- `Aplicação das regras PEP 8`
