"""Utilitários de conexão e criação de schemas DuckDB."""

from pathlib import Path

import duckdb

DATABASE_PATH = Path("olist.duckdb")


def conectar(*, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre o banco do projeto, opcionalmente em modo somente leitura."""
    return duckdb.connect(str(DATABASE_PATH), read_only=read_only)


def criar_schema(con: duckdb.DuckDBPyConnection, nome: str) -> None:
    """Cria um schema se ele ainda não existir."""
    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{nome}"')
