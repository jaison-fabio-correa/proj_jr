"""Materialização da camada MART para o dashboard de Fórmula 1.

Especificação:

* A camada lê exclusivamente ``refined`` e grava exclusivamente ``mart``;
  assim, nenhum dashboard precisa conhecer a modelagem das camadas anteriores.
* Todas as métricas e agregações ficam materializadas aqui. ``painel.py`` e
  ``app.py`` somente leem, filtram, ordenam e apresentam os resultados.
* Cada tabela é recriada com ``CREATE OR REPLACE TABLE`` para que o processo
  seja idempotente e não acumule dados em reexecuções.
* O processo exige as 14 tabelas REFINED antes de transformar qualquer dado e
  encerra com instrução para executar a transformação quando faltar alguma.

Assumptions not specified:

* Um abandono é uma linha de resultado cujo status não é ``Finished``.
* A categoria ``Acidente/colisão`` é usada quando o status contém ``Accident``
  ou ``Collision``; os demais abandonos são classificados como mecânicos.
* A eficiência do piloto é vitórias divididas por corridas disputadas, em
  percentual.
"""

from __future__ import annotations

import sys

import duckdb

from pipeline.db import conectar, criar_schema

TABLES = (
    "overview_kpis",
    "nationality_stats",
    "constructor_titles_by_decade",
    "constructor_wins_by_year",
    "hall_of_fame",
    "season_kpis",
    "championship_progression",
    "championship_gap",
    "grid_performance",
    "pit_stop_performance",
    "dnf_reliability",
)


REFINED_TABLES = (
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


QUERIES = {
    "overview_kpis": """
        WITH final_driver_standings AS (
            SELECT
                ds.*,
                r.year,
                ROW_NUMBER() OVER (
                    PARTITION BY r.year, ds.driverId
                    ORDER BY r.round DESC
                ) AS final_row
            FROM refined.driver_standings ds
            JOIN refined.races r ON r.raceId = ds.raceId
        ), driver_titles AS (
            SELECT COUNT(DISTINCT driverId) AS total
            FROM final_driver_standings
            WHERE final_row = 1 AND position = 1
        ), constructor_titles AS (
            SELECT COUNT(DISTINCT constructorId) AS total
            FROM (
                SELECT
                    cs.*,
                    r.year,
                    ROW_NUMBER() OVER (
                        PARTITION BY r.year, cs.constructorId
                        ORDER BY r.round DESC
                    ) AS final_row
                FROM refined.constructor_standings cs
                JOIN refined.races r ON r.raceId = cs.raceId
            ) final_constructor_standings
            WHERE final_row = 1 AND position = 1
        ), top_nationality AS (
            SELECT d.nationality, COUNT(*) AS titles
            FROM final_driver_standings ds
            JOIN refined.drivers d ON d.driverId = ds.driverId
            WHERE ds.final_row = 1 AND ds.position = 1
            GROUP BY d.nationality
            ORDER BY titles DESC, d.nationality
            LIMIT 1
        )
        SELECT
            (SELECT COUNT(DISTINCT year) FROM refined.seasons) AS total_seasons,
            (SELECT total FROM driver_titles) AS unique_champion_drivers,
            (SELECT total FROM constructor_titles) AS unique_champion_constructors,
            (SELECT COUNT(*) FROM refined.races) AS total_races,
            (SELECT nationality FROM top_nationality) AS top_champion_nationality,
            (SELECT titles FROM top_nationality) AS top_champion_nationality_titles
    """,
    "nationality_stats": """
        WITH final_driver_standings AS (
            SELECT
                ds.*,
                r.year,
                ROW_NUMBER() OVER (
                    PARTITION BY r.year, ds.driverId
                    ORDER BY r.round DESC
                ) AS final_row
            FROM refined.driver_standings ds
            JOIN refined.races r ON r.raceId = ds.raceId
        ), titles AS (
            SELECT d.nationality, COUNT(*) AS titles
            FROM final_driver_standings ds
            JOIN refined.drivers d ON d.driverId = ds.driverId
            WHERE ds.final_row = 1 AND ds.position = 1
            GROUP BY d.nationality
        ), wins AS (
            SELECT d.nationality, COUNT(*) AS wins
            FROM refined.results r
            JOIN refined.drivers d ON d.driverId = r.driverId
            WHERE r.positionOrder = 1
            GROUP BY d.nationality
        ), podiums AS (
            SELECT d.nationality, COUNT(*) AS podiums
            FROM refined.results r
            JOIN refined.drivers d ON d.driverId = r.driverId
            WHERE r.positionOrder <= 3
            GROUP BY d.nationality
        )
        SELECT
            COALESCE(t.nationality, w.nationality, p.nationality) AS nationality,
            COALESCE(t.titles, 0) AS titles,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(p.podiums, 0) AS podiums
        FROM titles t
        FULL OUTER JOIN wins w ON w.nationality = t.nationality
        FULL OUTER JOIN podiums p
            ON p.nationality = COALESCE(t.nationality, w.nationality)
        ORDER BY wins DESC, podiums DESC, nationality
    """,
    "constructor_titles_by_decade": """
        WITH final_constructor_standings AS (
            SELECT
                cs.*,
                r.year,
                ROW_NUMBER() OVER (
                    PARTITION BY r.year, cs.constructorId
                    ORDER BY r.round DESC
                ) AS final_row
            FROM refined.constructor_standings cs
            JOIN refined.races r ON r.raceId = cs.raceId
        )
        SELECT
            CAST(FLOOR(year / 10) * 10 AS INTEGER) AS decade,
            c.name AS constructor,
            COUNT(*) AS titles
        FROM final_constructor_standings cs
        JOIN refined.constructors c ON c.constructorId = cs.constructorId
        WHERE cs.final_row = 1 AND cs.position = 1
        GROUP BY decade, c.name
        ORDER BY decade, titles DESC, constructor
    """,
    "constructor_wins_by_year": """
        SELECT
            r.year,
            c.name AS constructor,
            COUNT(*) AS wins
        FROM refined.results res
        JOIN refined.races r ON r.raceId = res.raceId
        JOIN refined.constructors c ON c.constructorId = res.constructorId
        WHERE res.positionOrder = 1
        GROUP BY r.year, c.name
        ORDER BY r.year, wins DESC, constructor
    """,
    "hall_of_fame": """
        WITH final_driver_standings AS (
            SELECT
                ds.*,
                r.year,
                ROW_NUMBER() OVER (
                    PARTITION BY r.year, ds.driverId
                    ORDER BY r.round DESC
                ) AS final_row
            FROM refined.driver_standings ds
            JOIN refined.races r ON r.raceId = ds.raceId
        ), titles AS (
            SELECT driverId, COUNT(*) AS titles
            FROM final_driver_standings
            WHERE final_row = 1 AND position = 1
            GROUP BY driverId
        ), wins AS (
            SELECT driverId, COUNT(*) AS wins
            FROM refined.results
            WHERE positionOrder = 1
            GROUP BY driverId
        ), podiums AS (
            SELECT driverId, COUNT(*) AS podiums
            FROM refined.results
            WHERE positionOrder <= 3
            GROUP BY driverId
        ), poles AS (
            SELECT driverId, COUNT(*) AS poles
            FROM refined.qualifying
            WHERE position = 1
            GROUP BY driverId
        ), races AS (
            SELECT driverId, COUNT(DISTINCT raceId) AS races
            FROM refined.results
            GROUP BY driverId
        )
        SELECT
            d.driverId,
            d.forename || ' ' || d.surname AS driver,
            COALESCE(t.titles, 0) AS titles,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(p.podiums, 0) AS podiums,
            COALESCE(po.poles, 0) AS poles,
            COALESCE(ra.races, 0) AS races,
            CASE WHEN COALESCE(ra.races, 0) = 0 THEN 0
                 ELSE ROUND(100.0 * COALESCE(w.wins, 0) / ra.races, 2)
            END AS win_efficiency_pct
        FROM refined.drivers d
        LEFT JOIN titles t ON t.driverId = d.driverId
        LEFT JOIN wins w ON w.driverId = d.driverId
        LEFT JOIN podiums p ON p.driverId = d.driverId
        LEFT JOIN poles po ON po.driverId = d.driverId
        LEFT JOIN races ra ON ra.driverId = d.driverId
        WHERE COALESCE(ra.races, 0) > 0
        ORDER BY titles DESC, wins DESC, podiums DESC, driver
    """,
    "season_kpis": """
        WITH driver_champions AS (
            SELECT year, driver, points
            FROM (
                SELECT
                    r.year,
                    d.forename || ' ' || d.surname AS driver,
                    ds.points,
                    ROW_NUMBER() OVER (
                        PARTITION BY r.year ORDER BY r.round DESC, ds.points DESC
                    ) AS row_number
                FROM refined.driver_standings ds
                JOIN refined.races r ON r.raceId = ds.raceId
                JOIN refined.drivers d ON d.driverId = ds.driverId
                WHERE ds.position = 1
            ) ranked
            WHERE row_number = 1
        ), constructor_champions AS (
            SELECT year, constructor, points
            FROM (
                SELECT
                    r.year,
                    c.name AS constructor,
                    cs.points,
                    ROW_NUMBER() OVER (
                        PARTITION BY r.year ORDER BY r.round DESC, cs.points DESC
                    ) AS row_number
                FROM refined.constructor_standings cs
                JOIN refined.races r ON r.raceId = cs.raceId
                JOIN refined.constructors c ON c.constructorId = cs.constructorId
                WHERE cs.position = 1
            ) ranked
            WHERE row_number = 1
        ), dnfs AS (
            SELECT r.year, COUNT(*) AS dnfs
            FROM refined.results res
            JOIN refined.races r ON r.raceId = res.raceId
            JOIN refined.status s ON s.statusId = res.statusId
            WHERE s.status <> 'Finished'
            GROUP BY r.year
        )
        SELECT
            s.year,
            dc.driver AS driver_champion,
            dc.points AS driver_champion_points,
            cc.constructor AS constructor_champion,
            cc.points AS constructor_champion_points,
            COUNT(r.raceId) AS races,
            COALESCE(dn.dnfs, 0) AS dnfs
        FROM refined.seasons s
        LEFT JOIN driver_champions dc ON dc.year = s.year
        LEFT JOIN constructor_champions cc ON cc.year = s.year
        LEFT JOIN refined.races r ON r.year = s.year
        LEFT JOIN dnfs dn ON dn.year = s.year
        GROUP BY s.year, dc.driver, dc.points, cc.constructor, cc.points, dn.dnfs
        ORDER BY s.year
    """,
    "championship_progression": """
        WITH points AS (
            SELECT
                r.year,
                r.round,
                r.name AS race,
                d.forename || ' ' || d.surname AS driver,
                SUM(res.points) OVER (
                    PARTITION BY r.year, res.driverId
                    ORDER BY r.round ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS cumulative_points
            FROM refined.results res
            JOIN refined.races r ON r.raceId = res.raceId
            JOIN refined.drivers d ON d.driverId = res.driverId
        )
        SELECT
            year,
            round,
            race,
            driver,
            cumulative_points,
            MAX(cumulative_points) OVER (PARTITION BY year, round) - cumulative_points
                AS gap_to_leader
        FROM points
        ORDER BY year, round, cumulative_points DESC, driver
    """,
    "championship_gap": """
        WITH points AS (
            SELECT
                r.year,
                r.round,
                r.name AS race,
                res.driverId,
                SUM(res.points) OVER (
                    PARTITION BY r.year, res.driverId
                    ORDER BY r.round ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS cumulative_points
            FROM refined.results res
            JOIN refined.races r ON r.raceId = res.raceId
        ), ranked AS (
            SELECT
                year,
                round,
                race,
                cumulative_points,
                ROW_NUMBER() OVER (
                    PARTITION BY year, round ORDER BY cumulative_points DESC, driverId
                ) AS championship_position
            FROM points
        )
        SELECT
            year,
            round,
            race,
            MAX(CASE WHEN championship_position = 1 THEN cumulative_points END)
                - MAX(CASE WHEN championship_position = 2 THEN cumulative_points END)
                AS gap_to_second,
            MAX(CASE WHEN championship_position = 1 THEN cumulative_points END)
                - MAX(CASE WHEN championship_position = 3 THEN cumulative_points END)
                AS gap_to_third
        FROM ranked
        GROUP BY year, round, race
        ORDER BY year, round
    """,
    "grid_performance": """
        SELECT
            r.year,
            d.forename || ' ' || d.surname AS driver,
            AVG(res.grid - res.positionOrder) AS average_grid_gain,
            COUNT(*) AS races
        FROM refined.results res
        JOIN refined.races r ON r.raceId = res.raceId
        JOIN refined.drivers d ON d.driverId = res.driverId
        WHERE res.grid IS NOT NULL AND res.positionOrder IS NOT NULL
        GROUP BY r.year, d.driverId, d.forename, d.surname
        ORDER BY r.year, average_grid_gain DESC, driver
    """,
    "pit_stop_performance": """
        SELECT
            r.year,
            c.name AS constructor,
            ROUND(AVG(epoch(ps.duration)), 3) AS average_stop_seconds,
            ROUND(MIN(epoch(ps.duration)), 3) AS fastest_stop_seconds,
            COUNT(*) AS stops
        FROM refined.pit_stops ps
        JOIN refined.races r ON r.raceId = ps.raceId
        JOIN refined.results res
            ON res.raceId = ps.raceId AND res.driverId = ps.driverId
        JOIN refined.constructors c ON c.constructorId = res.constructorId
        WHERE ps.duration IS NOT NULL
        GROUP BY r.year, c.constructorId, c.name
        ORDER BY r.year, average_stop_seconds, constructor
    """,
    "dnf_reliability": """
        SELECT
            r.year,
            c.name AS constructor,
            CASE
                WHEN lower(s.status) LIKE '%accident%'
                  OR lower(s.status) LIKE '%collision%'
                THEN 'Acidente/colisão'
                ELSE 'Mecânica/outros'
            END AS incident_category,
            COUNT(*) AS dnfs
        FROM refined.results res
        JOIN refined.races r ON r.raceId = res.raceId
        JOIN refined.constructors c ON c.constructorId = res.constructorId
        JOIN refined.status s ON s.statusId = res.statusId
        WHERE s.status <> 'Finished'
        GROUP BY r.year, c.name, incident_category
        ORDER BY r.year, constructor, incident_category
    """,
}


def _tabelas_ausentes(con: duckdb.DuckDBPyConnection) -> list[str]:
    existentes = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'refined'"
        ).fetchall()
    }
    return [table for table in REFINED_TABLES if table not in existentes]


def gerar() -> None:
    """Valida REFINED e materializa todas as tabelas MART."""
    con = conectar()
    try:
        ausentes = _tabelas_ausentes(con)
        if ausentes:
            print(
                "Tabelas ausentes no schema refined: "
                f"{', '.join(ausentes)}. Rode: "
                "uv run python -m pipeline.transformacao"
            )
            sys.exit(1)

        criar_schema(con, "mart")
        for table in TABLES:
            con.execute(
                f'CREATE OR REPLACE TABLE mart."{table}" AS {QUERIES[table]}'
            )
    finally:
        con.close()

    print(f"MART: {len(TABLES)} tabelas recriadas")


if __name__ == "__main__":
    gerar()
