"""Leitura e formatação dos Data Marts para o dashboard.

Especificação:

* ``ler`` abre ``olist.duckdb`` em modo somente leitura e fecha a conexão
  dentro da própria função, evitando conexões persistentes no dashboard.
* Para cada mart, a única consulta executada é ``SELECT *``; toda métrica já
  deve existir na camada MART.
* Este módulo não calcula métricas. Ele apenas lê, filtra, ordena, limita e
  formata valores para apresentação.

Assumptions not specified:

* O parâmetro ``marts`` contém nomes de tabelas confiáveis produzidos por
  ``pipeline.mart``.
* A formatação numérica usa o padrão visual brasileiro apenas na camada de
  apresentação; os DataFrames retornados por ``ler`` não são alterados.
"""

from __future__ import annotations

from collections.abc import Iterable

import duckdb
import pandas as pd
import plotly.express as px


def ler(marts: Iterable[str]) -> dict[str, pd.DataFrame]:
    """Lê cada mart com uma consulta ``SELECT *`` e fecha o banco."""
    nomes = list(marts)
    con = duckdb.connect("olist.duckdb", read_only=True)
    try:
        return {
            nome: con.execute(f'SELECT * FROM mart."{nome}"').df()
            for nome in nomes
        }
    finally:
        con.close()


def filtrar_ano(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Retorna apenas as linhas do ano escolhido."""
    if "year" not in df.columns:
        return df
    return df.loc[df["year"].eq(ano)].copy()


def ordenar(
    df: pd.DataFrame, coluna: str, ascending: bool = False
) -> pd.DataFrame:
    """Ordena um DataFrame sem alterar o original."""
    return df.sort_values(coluna, ascending=ascending).reset_index(drop=True)


def limitar(df: pd.DataFrame, linhas: int) -> pd.DataFrame:
    """Limita a quantidade exibida de linhas."""
    return df.head(linhas).copy()


def formatar_numero(valor: object, casas: int = 0) -> str:
    """Formata um valor escalar para leitura no dashboard."""
    if pd.isna(valor):
        return "—"
    return (
        f"{float(valor):,.{casas}f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def formatar_percentual(valor: object) -> str:
    """Formata um percentual já calculado no mart."""
    return f"{formatar_numero(valor, 2)}%"


def grafico_nacionalidade(df: pd.DataFrame):
    dados = limitar(ordenar(df, "titles"), 10)
    return px.bar(
        dados,
        x="wins",
        y="nationality",
        color="titles",
        orientation="h",
        title="Top 10 nacionalidades por vitórias",
        labels={
            "wins": "Vitórias",
            "nationality": "Nacionalidade",
            "titles": "Títulos",
        },
    )


def grafico_titulos_construtores(df: pd.DataFrame):
    return px.bar(
        df,
        x="decade",
        y="titles",
        color="constructor",
        barmode="stack",
        title="Títulos de construtores por década",
        labels={
            "decade": "Década",
            "titles": "Títulos",
            "constructor": "Construtor",
        },
    )


def grafico_vitorias_construtores(df: pd.DataFrame):
    return px.line(
        df,
        x="year",
        y="wins",
        color="constructor",
        markers=True,
        title="Evolução das vitórias por construtor",
        labels={
            "year": "Ano",
            "wins": "Vitórias",
            "constructor": "Construtor",
        },
    )


def grafico_progressao(df: pd.DataFrame):
    return px.line(
        df,
        x="round",
        y="cumulative_points",
        color="driver",
        hover_data=["race"],
        markers=True,
        title="Progressão do campeonato de pilotos",
        labels={
            "round": "Rodada",
            "cumulative_points": "Pontos acumulados",
            "driver": "Piloto",
        },
    )


def grafico_gap(df: pd.DataFrame):
    return px.area(
        df,
        x="round",
        y=["gap_to_second", "gap_to_third"],
        title="Diferença para o líder",
        labels={
            "round": "Rodada",
            "value": "Pontos de diferença",
            "variable": "Posição",
        },
    )


def grafico_grid(df: pd.DataFrame):
    return px.bar(
        df.sort_values("average_grid_gain"),
        x="average_grid_gain",
        y="driver",
        orientation="h",
        title="Posições ganhas ou perdidas",
        labels={
            "average_grid_gain": "Ganho médio de posições",
            "driver": "Piloto",
        },
    )


def grafico_pit_stops(df: pd.DataFrame):
    return px.bar(
        df,
        x="constructor",
        y=["average_stop_seconds", "fastest_stop_seconds"],
        barmode="group",
        title="Performance de pit stops",
        labels={
            "value": "Segundos",
            "constructor": "Construtor",
            "variable": "Métrica",
        },
    )


def grafico_dnfs(df: pd.DataFrame):
    return px.bar(
        df,
        x="constructor",
        y="dnfs",
        color="incident_category",
        barmode="stack",
        title="Confiabilidade e incidentes",
        labels={
            "constructor": "Construtor",
            "dnfs": "Abandonos",
            "incident_category": "Categoria",
        },
    )
