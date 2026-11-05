"""Transformação da camada RAW para a camada REFINED.

Especificação:

* A entrada é exclusivamente o schema ``raw`` e a saída é exclusivamente o
  schema ``refined``; isso mantém a camada bruta imutável.
* As 14 tabelas e todas as suas colunas são preservadas com os mesmos nomes,
  evitando perda de informação e mantendo o contrato entre camadas.
* Datas, horários, durações, inteiros, decimais e textos recebem tipos explícitos para
  que a camada refined seja utilizável sem inferência posterior.
* Conversões usam ``CAST`` e ``strptime`` em SQL. Uma conversão inválida deve
  interromper o processo, em vez de virar nulo silenciosamente.
* Nulos são mantidos como nulos; nenhuma linha é filtrada ou preenchida.
* ``CREATE OR REPLACE TABLE`` torna a execução idempotente e impede que uma
  nova execução acrescente linhas às tabelas existentes.
* A existência das 14 tabelas RAW é verificada antes de qualquer transformação
  para produzir uma mensagem acionável quando a ingestão não foi executada.

Assumptions not specified:

* Datas sem horário são convertidas para ``DATE``; durações de voltas, tempos
  de classificação e durações de parada são convertidos para ``INTERVAL``.
  Horários de relógio permanecem como ``TIME``.
* Pontos, coordenadas, velocidades e durações numéricas usam ``DOUBLE`` ou
  ``DECIMAL`` quando a fonte pode conter casas decimais; identificadores,
  posições e contagens usam ``INTEGER``.
* O comando é executado a partir da raiz do projeto, onde está
  ``olist.duckdb``.
"""

from __future__ import annotations

import re
import sys

import duckdb

from pipeline.db import conectar, criar_schema


TABLES = (
    "circuits",
    "constructor_results",
    "constructor_standings",
    "constructors",
    "driver_standings",
    "drivers",
    "lap_times",
    "pit_stops",
    "qualifying",
    "races",
    "results",
    "seasons",
    "sprint_results",
    "status",
)

INTEGER_COLUMNS: dict[str, set[str]] = {
    "circuits": {"circuitId", "alt"},
    "constructor_results": {"constructorResultsId", "raceId", "constructorId"},
    "constructor_standings": {
        "constructorStandingsId",
        "raceId",
        "constructorId",
        "position",
        "wins",
    },
    "constructors": {"constructorId"},
    "driver_standings": {
        "driverStandingsId",
        "raceId",
        "driverId",
        "position",
        "wins",
    },
    "drivers": {"driverId", "number"},
    "lap_times": {"raceId", "driverId", "lap", "position", "milliseconds"},
    "pit_stops": {"raceId", "driverId", "stop", "lap", "milliseconds"},
    "qualifying": {
        "qualifyId",
        "raceId",
        "driverId",
        "constructorId",
        "number",
        "position",
    },
    "races": {"raceId", "year", "round", "circuitId"},
    "results": {
        "resultId",
        "raceId",
        "driverId",
        "constructorId",
        "number",
        "grid",
        "position",
        "positionOrder",
        "laps",
        "fastestLap",
        "rank",
        "statusId",
    },
    "seasons": {"year"},
    "sprint_results": {
        "resultId",
        "raceId",
        "driverId",
        "constructorId",
        "number",
        "grid",
        "position",
        "positionOrder",
        "laps",
        "fastestLap",
        "statusId",
        "rank",
    },
    "status": {"statusId"},
}

DECIMAL_COLUMNS: dict[str, set[str]] = {
    "constructor_results": {"points"},
    "constructor_standings": {"points"},
    "driver_standings": {"points"},
    "results": {"points", "fastestLapSpeed"},
    "sprint_results": {"points"},
}

DOUBLE_COLUMNS = {"lat", "lng"}
DATE_COLUMNS = {"date", "fp1_date", "fp2_date", "fp3_date", "quali_date", "sprint_date"}
TIME_COLUMNS = {
    "time",
    "fp1_time",
    "fp2_time",
    "fp3_time",
    "quali_time",
    "sprint_time",
    "q1",
    "q2",
    "q3",
    "fastestLapTime",
}

INTERVAL_COLUMNS: dict[str, set[str]] = {
    "lap_times": {"time"},
    "pit_stops": {"duration"},
    "qualifying": {"q1", "q2", "q3"},
    "results": {"time", "fastestLapTime"},
    "sprint_results": {"time", "fastestLapTime"},
}

TIME_FORMATS = {
    ("pit_stops", "time"): "%H:%M:%S",
    ("races", "time"): "%H:%M:%S",
    ("races", "fp1_time"): "%H:%M:%S",
    ("races", "fp2_time"): "%H:%M:%S",
    ("races", "fp3_time"): "%H:%M:%S",
    ("races", "quali_time"): "%H:%M:%S",
    ("races", "sprint_time"): "%H:%M:%S",
    ("lap_times", "time"): "%M:%S.%f",
    ("qualifying", "q1"): "%M:%S.%f",
    ("qualifying", "q2"): "%M:%S.%f",
    ("qualifying", "q3"): "%M:%S.%f",
    ("results", "time"): "%H:%M:%S.%f",
    ("results", "fastestLapTime"): "%H:%M:%S.%f",
    ("sprint_results", "time"): "%M:%S.%f",
    ("sprint_results", "fastestLapTime"): "%M:%S.%f",
}


def _identificador(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def _tipo_sql(tabela: str, coluna: str) -> str:
    if coluna in INTEGER_COLUMNS.get(tabela, set()):
        return "INTEGER"
    if coluna in DECIMAL_COLUMNS.get(tabela, set()):
        return "DECIMAL(18, 6)"
    if coluna in DOUBLE_COLUMNS:
        return "DOUBLE"
    if coluna in DATE_COLUMNS:
        return "DATE"
    if coluna in INTERVAL_COLUMNS.get(tabela, set()):
        return "INTERVAL"
    if coluna in TIME_COLUMNS:
        return "TIME"
    return "VARCHAR"


def _tempo_sql(tabela: str, coluna: str, valor: str) -> str:
    formato = TIME_FORMATS.get((tabela, coluna), "%H:%M:%S")
    if tabela == "results" and coluna == "time":
        segundos = f"CAST(substr({valor}, 2) AS DOUBLE)"
        return (
            f"CASE WHEN starts_with({valor}, '+') THEN "
            f"make_time(CAST(floor({segundos} / 3600) AS BIGINT), "
            f"CAST(floor({segundos} / 60) % 60 AS BIGINT), {segundos} % 60) "
            f"WHEN (length({valor}) - length(replace({valor}, ':', ''))) = 1 THEN "
            f"CASE WHEN strpos({valor}, '.') > 0 THEN "
            f"strptime({valor}, '%M:%S.%f')::TIME ELSE "
            f"strptime({valor}, '%M:%S')::TIME END "
            f"WHEN strpos({valor}, '.') > 0 THEN "
            f"strptime({valor}, '{formato}')::TIME "
            f"ELSE strptime({valor}, '%H:%M:%S')::TIME END"
        )
    if formato == "%M:%S.%f":
        return (
            f"CASE WHEN (length({valor}) - length(replace({valor}, ':', ''))) = 2 "
            f"THEN CASE WHEN strpos({valor}, '.') > 0 THEN "
            f"strptime({valor}, '%H:%M:%S.%f')::TIME ELSE "
            f"strptime({valor}, '%H:%M:%S')::TIME END "
            f"WHEN strpos({valor}, '.') > 0 THEN "
            f"strptime({valor}, '{formato}')::TIME ELSE "
            f"strptime({valor}, '%M:%S')::TIME END"
        )
    return f"strptime({valor}, '{formato}')::TIME"


def _intervalo_sql(valor: str) -> str:
    base = f"CASE WHEN starts_with({valor}, '+') THEN substr({valor}, 2) ELSE {valor} END"
    segundo_separador = (
        f"strpos(substr({base}, strpos({base}, ':') + 1), ':')"
    )
    texto = (
        f"CASE WHEN strpos({base}, ':') = 0 THEN "
        f"{base} || ' seconds' "
        f"WHEN {segundo_separador} = 0 THEN "
        f"split_part({base}, ':', 1) || ' minutes ' || "
        f"split_part({base}, ':', 2) || ' seconds' "
        f"ELSE split_part({base}, ':', 1) || ' hours ' || "
        f"split_part({base}, ':', 2) || ' minutes ' || "
        f"split_part({base}, ':', 3) || ' seconds' END"
    )
    return f"CAST(({texto}) AS INTERVAL)"


def _expressao(tabela: str, coluna: str) -> str:
    identificador = _identificador(coluna)
    valor = f"NULLIF({identificador}, chr(92) || 'N')"
    tipo = _tipo_sql(tabela, coluna)
    if tipo == "DATE":
        return f"strptime({valor}, '%Y-%m-%d')::DATE AS {identificador}"
    if tipo == "INTERVAL":
        return f"{_intervalo_sql(valor)} AS {identificador}"
    if tipo == "TIME":
        return f"{_tempo_sql(tabela, coluna, valor)} AS {identificador}"
    if tipo == "VARCHAR":
        return f"{valor} AS {identificador}"
    return f"CAST({valor} AS {tipo}) AS {identificador}"


def _tabelas_ausentes(con: duckdb.DuckDBPyConnection) -> list[str]:
    encontrados = {
        linha[0]
        for linha in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'raw'"
        ).fetchall()
    }
    return [tabela for tabela in TABLES if tabela not in encontrados]


def _exemplo_do_erro(erro: Exception) -> str:
    mensagem = str(erro)
    encontrado = re.search(r"(?:string|value) ['\"]([^'\"]+)['\"]", mensagem)
    return encontrado.group(1) if encontrado else "não identificado pelo DuckDB"


def _validar_conversoes(con: duckdb.DuckDBPyConnection, tabela: str, colunas: list[str]) -> None:
    for coluna in colunas:
        tipo = _tipo_sql(tabela, coluna)
        if tipo == "VARCHAR":
            continue
        expressao = _expressao(tabela, coluna).rsplit(" AS ", 1)[0]
        try:
            con.execute(
                f"SELECT {expressao} FROM raw.{_identificador(tabela)}"
            ).fetchall()
        except duckdb.Error as erro:
            print(
                f"Falha na conversão: tabela={tabela}, coluna={coluna}, "
                f"valor={_exemplo_do_erro(erro)}"
            )
            sys.exit(1)


def transformar() -> None:
    """Valida as entradas RAW e recria as 14 tabelas REFINED."""
    con = conectar()
    try:
        ausentes = _tabelas_ausentes(con)
        if ausentes:
            print(
                "Tabelas ausentes no schema raw: "
                f"{', '.join(ausentes)}. Rode: uv run python -m pipeline.ingestao"
            )
            sys.exit(1)

        colunas_por_tabela: dict[str, list[str]] = {}
        for tabela in TABLES:
            colunas = [
                linha[0]
                for linha in con.execute(
                    f"DESCRIBE raw.{_identificador(tabela)}"
                ).fetchall()
            ]
            colunas_por_tabela[tabela] = colunas
            _validar_conversoes(con, tabela, colunas)

        criar_schema(con, "refined")
        for tabela, colunas in colunas_por_tabela.items():
            selecao = ", ".join(_expressao(tabela, coluna) for coluna in colunas)
            con.execute(
                f"CREATE OR REPLACE TABLE refined.{_identificador(tabela)} AS "
                f"SELECT {selecao} FROM raw.{_identificador(tabela)}"
            )
    finally:
        con.close()

    print(f"REFINED: {len(TABLES)} tabelas recriadas")


if __name__ == "__main__":
    transformar()
