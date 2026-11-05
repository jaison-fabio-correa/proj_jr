from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from painel import (
    filtrar_ano,
    formatar_numero,
    formatar_percentual,
    grafico_dnfs,
    grafico_gap,
    grafico_grid,
    grafico_nacionalidade,
    grafico_pit_stops,
    grafico_progressao,
    grafico_titulos_construtores,
    grafico_vitorias_construtores,
    ler,
    limitar,
    ordenar,
)
from pipeline import db, ingestao, mart, transformacao

TABLES = [
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
]


def _csvs(path, missing: str | None = None) -> None:
    for table in TABLES:
        if table == missing:
            continue
        # Duas linhas provam preservação de ordem e campo vazio como nulo.
        (path / f"{table}.csv").write_text(
            "id,value\n1,alpha\n2,\n", encoding="utf-8"
        )


def test_ingestao_preserva_linhas_colunas_texto_e_saida_deterministica(
    tmp_path, monkeypatch, capsys
):
    raw = tmp_path / "raw"
    raw.mkdir()
    _csvs(raw)
    monkeypatch.chdir(tmp_path)

    ingestao.ingerir()
    primeira_saida = capsys.readouterr().out
    ingestao.ingerir()
    segunda_saida = capsys.readouterr().out

    assert primeira_saida == "RAW: 14 tabelas recriadas\n"
    assert segunda_saida == primeira_saida
    con = duckdb.connect(str(tmp_path / "olist.duckdb"), read_only=True)
    assert con.execute("SELECT * FROM raw.drivers").fetchall() == [
        ("1", "alpha"),
        ("2", None),
    ]
    assert con.execute(
        "SELECT typeof(id) FROM raw.drivers LIMIT 1"
    ).fetchone() == ("VARCHAR",)
    con.close()


def test_ingestao_faltando_arquivo_encerra_antes_de_criar_banco(
    tmp_path, monkeypatch, capsys
):
    raw = tmp_path / "raw"
    raw.mkdir()
    _csvs(raw, missing="status")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        ingestao.ingerir()

    assert "status.csv" in capsys.readouterr().out
    assert not (tmp_path / "olist.duckdb").exists()


def _raw_tables(
    path, overrides: dict[str, str] | None = None
) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA raw")
    overrides = overrides or {}
    for table in TABLES:
        ddl = overrides.get(table, "id VARCHAR")
        con.execute(f'CREATE TABLE raw."{table}" ({ddl})')
    return con


def test_transformacao_converte_data_decimal_intervalo_e_preserva_linhas(
    tmp_path, monkeypatch
):
    database = tmp_path / "olist.duckdb"
    overrides = {
        "races": "raceId VARCHAR, year VARCHAR, round VARCHAR, circuitId VARCHAR, date VARCHAR, time VARCHAR",
        "constructor_results": "constructorResultsId VARCHAR, raceId VARCHAR, constructorId VARCHAR, points VARCHAR, status VARCHAR",
        "results": "resultId VARCHAR, raceId VARCHAR, driverId VARCHAR, constructorId VARCHAR, grid VARCHAR, positionOrder VARCHAR, points VARCHAR, time VARCHAR, fastestLapTime VARCHAR, statusId VARCHAR",
    }
    con = _raw_tables(database, overrides)
    con.execute(
        "INSERT INTO raw.races VALUES ('1', '2020', '1', '1', '2020-07-05', '14:10:00')"
    )
    con.execute(
        "INSERT INTO raw.constructor_results VALUES ('1', '1', '1', '12.5', 'ok')"
    )
    con.execute(
        "INSERT INTO raw.results VALUES ('1', '1', '1', '1', '2', '1', '25.5', '1:34:50.616', '1:27.452', '1')"
    )
    con.close()
    monkeypatch.setattr(db, "DATABASE_PATH", database)

    transformacao.transformar()

    con = duckdb.connect(str(database), read_only=True)
    assert con.execute("SELECT COUNT(*) FROM refined.results").fetchone() == (
        1,
    )
    assert con.execute(
        "SELECT typeof(points), typeof(time) FROM refined.results"
    ).fetchone() == ("DECIMAL(18,6)", "INTERVAL")
    assert con.execute(
        "SELECT typeof(date), typeof(time) FROM refined.races"
    ).fetchone() == ("DATE", "TIME")
    con.close()


def test_transformacao_valor_invalido_encerra_com_tabela_coluna_e_exemplo(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "olist.duckdb"
    overrides = {
        "constructor_results": "constructorResultsId VARCHAR, raceId VARCHAR, constructorId VARCHAR, points VARCHAR"
    }
    con = _raw_tables(database, overrides)
    con.execute(
        "INSERT INTO raw.constructor_results VALUES ('1', '1', '1', 'invalido')"
    )
    con.close()
    monkeypatch.setattr(db, "DATABASE_PATH", database)

    with pytest.raises(SystemExit):
        transformacao.transformar()

    mensagem = capsys.readouterr().out
    assert "constructor_results" in mensagem
    assert "points" in mensagem
    assert "invalido" in mensagem


def test_transformacao_sem_tabelas_refined_pede_ingestao_anterior(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "olist.duckdb"
    con = duckdb.connect(str(database))
    con.close()
    monkeypatch.setattr(db, "DATABASE_PATH", database)

    with pytest.raises(SystemExit):
        transformacao.transformar()

    assert "uv run python -m pipeline.ingestao" in capsys.readouterr().out


def _refined_database(path):
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA refined")
    empty = {
        "circuits": "id INTEGER",
        "constructor_results": "id INTEGER",
        "lap_times": "id INTEGER",
        "sprint_results": "id INTEGER",
    }
    for table, ddl in empty.items():
        con.execute(f'CREATE TABLE refined."{table}" ({ddl})')
    con.execute("CREATE TABLE refined.seasons (year INTEGER)")
    con.execute("INSERT INTO refined.seasons VALUES (2020)")
    con.execute(
        "CREATE TABLE refined.constructors (constructorId INTEGER, name VARCHAR)"
    )
    con.execute("INSERT INTO refined.constructors VALUES (1, 'Equipe A')")
    con.execute(
        "CREATE TABLE refined.drivers (driverId INTEGER, forename VARCHAR, surname VARCHAR, nationality VARCHAR)"
    )
    con.execute(
        "INSERT INTO refined.drivers VALUES (1, 'Ada', 'Pilot', 'Brazilian'), (2, 'Bia', 'Racer', 'British')"
    )
    con.execute(
        "CREATE TABLE refined.races (raceId INTEGER, year INTEGER, round INTEGER, name VARCHAR)"
    )
    con.execute(
        "INSERT INTO refined.races VALUES (1, 2020, 1, 'GP Teste'), (2, 2020, 2, 'GP Final')"
    )
    con.execute(
        "CREATE TABLE refined.driver_standings (driverStandingsId INTEGER, raceId INTEGER, driverId INTEGER, points DECIMAL(18,6), position INTEGER)"
    )
    con.execute(
        "INSERT INTO refined.driver_standings VALUES (1, 2, 1, 43, 1), (2, 2, 2, 18, 2)"
    )
    con.execute(
        "CREATE TABLE refined.constructor_standings (constructorStandingsId INTEGER, raceId INTEGER, constructorId INTEGER, points DECIMAL(18,6), position INTEGER)"
    )
    con.execute(
        "INSERT INTO refined.constructor_standings VALUES (1, 2, 1, 61, 1)"
    )
    con.execute(
        "CREATE TABLE refined.results (resultId INTEGER, raceId INTEGER, driverId INTEGER, constructorId INTEGER, grid INTEGER, positionOrder INTEGER, points DECIMAL(18,6), time INTERVAL, fastestLapTime INTERVAL, statusId INTEGER)"
    )
    con.execute(
        "INSERT INTO refined.results VALUES (1, 1, 1, 1, 2, 1, 25, INTERVAL '1 minute 34.5 seconds', INTERVAL '1 minute 27.4 seconds', 1), (2, 1, 2, 1, 1, 2, 18, INTERVAL '1 minute 35 seconds', INTERVAL '1 minute 28 seconds', 2), (3, 2, 1, 1, 1, 1, 18, INTERVAL '1 minute 30 seconds', INTERVAL '1 minute 26 seconds', 1)"
    )
    con.execute(
        "CREATE TABLE refined.qualifying (qualifyId INTEGER, raceId INTEGER, driverId INTEGER, constructorId INTEGER, number INTEGER, position INTEGER)"
    )
    con.execute(
        "INSERT INTO refined.qualifying VALUES (1, 1, 1, 1, 1, 1), (2, 1, 2, 1, 2, 2)"
    )
    con.execute(
        "CREATE TABLE refined.pit_stops (raceId INTEGER, driverId INTEGER, stop INTEGER, lap INTEGER, time TIME, duration INTERVAL)"
    )
    con.execute(
        "INSERT INTO refined.pit_stops VALUES (1, 1, 1, 10, TIME '14:00:00', INTERVAL '20 seconds'), (1, 2, 1, 10, TIME '14:01:00', INTERVAL '25 seconds')"
    )
    con.execute(
        "CREATE TABLE refined.status (statusId INTEGER, status VARCHAR)"
    )
    con.execute(
        "INSERT INTO refined.status VALUES (1, 'Finished'), (2, 'Accident')"
    )
    con.close()


def test_mart_gera_tabelas_agregadas_sem_alterar_refined(
    tmp_path, monkeypatch
):
    database = tmp_path / "olist.duckdb"
    _refined_database(database)
    monkeypatch.setattr(db, "DATABASE_PATH", database)

    mart.gerar()

    con = duckdb.connect(str(database), read_only=True)
    tabelas = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'mart'"
        ).fetchall()
    }
    assert tabelas == set(mart.TABLES)
    assert con.execute("SELECT COUNT(*) FROM refined.results").fetchone() == (
        3,
    )
    assert (
        con.execute("SELECT COUNT(*) FROM mart.hall_of_fame").fetchone()[0]
        == 2
    )
    con.close()


def test_mart_sem_refined_encerra_com_instrucao(tmp_path, monkeypatch, capsys):
    database = tmp_path / "olist.duckdb"
    con = duckdb.connect(str(database))
    con.close()
    monkeypatch.setattr(db, "DATABASE_PATH", database)

    with pytest.raises(SystemExit):
        mart.gerar()

    assert "uv run python -m pipeline.transformacao" in capsys.readouterr().out


def test_painel_le_filtra_ordena_limita_e_formata_em_duckdb_real(
    tmp_path, monkeypatch
):
    database = tmp_path / "olist.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.sample (year INTEGER, value INTEGER)")
    con.execute("INSERT INTO mart.sample VALUES (2020, 2), (2021, 1)")
    con.close()
    monkeypatch.chdir(tmp_path)

    dados = ler(["sample"])["sample"]
    assert dados.to_dict("records") == [
        {"year": 2020, "value": 2},
        {"year": 2021, "value": 1},
    ]
    assert filtrar_ano(dados, 2021)["value"].tolist() == [1]
    assert ordenar(dados, "value")["value"].tolist() == [2, 1]
    assert limitar(dados, 1).shape[0] == 1
    assert formatar_numero(1234.5, 1) == "1.234,5"
    assert formatar_numero(None) == "—"
    assert formatar_percentual(12.5) == "12,50%"


def test_painel_graficos_devolvem_figuras_com_dados_inventados():
    assert grafico_nacionalidade(
        pd.DataFrame({"nationality": ["A"], "wins": [2], "titles": [1]})
    ).data
    assert grafico_titulos_construtores(
        pd.DataFrame({"decade": [2020], "constructor": ["A"], "titles": [1]})
    ).data
    assert grafico_vitorias_construtores(
        pd.DataFrame({"year": [2020], "constructor": ["A"], "wins": [1]})
    ).data
    assert grafico_progressao(
        pd.DataFrame(
            {
                "round": [1],
                "driver": ["A"],
                "cumulative_points": [25],
                "race": ["GP"],
            }
        )
    ).data
    assert grafico_gap(
        pd.DataFrame(
            {"round": [1], "gap_to_second": [7], "gap_to_third": [10]}
        )
    ).data
    assert grafico_grid(
        pd.DataFrame({"driver": ["A"], "average_grid_gain": [2.0]})
    ).data
    assert grafico_pit_stops(
        pd.DataFrame(
            {
                "constructor": ["A"],
                "average_stop_seconds": [22.0],
                "fastest_stop_seconds": [20.0],
            }
        )
    ).data
    assert grafico_dnfs(
        pd.DataFrame(
            {
                "constructor": ["A"],
                "incident_category": ["Mecânica/outros"],
                "dnfs": [1],
            }
        )
    ).data
