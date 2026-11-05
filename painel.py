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


def ordenar(df: pd.DataFrame, coluna: str, ascending: bool = False) -> pd.DataFrame:
    """Ordena um DataFrame sem alterar o original."""
    return df.sort_values(coluna, ascending=ascending).reset_index(drop=True)


def limitar(df: pd.DataFrame, linhas: int) -> pd.DataFrame:
    """Limita a quantidade exibida de linhas."""
    return df.head(linhas).copy()


def formatar_numero(valor: object, casas: int = 0) -> str:
    """Formata um valor escalar para leitura no dashboard."""
    if pd.isna(valor):
        return "—"
    return f"{float(valor):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_percentual(valor: object) -> str:
    """Formata um percentual já calculado no mart."""
    return f"{formatar_numero(valor, 2)}%"
