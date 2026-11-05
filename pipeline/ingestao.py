"""Ingestão da camada RAW.

Especificação:

* O schema de destino é ``raw`` e cada CSV vira uma tabela com o mesmo nome,
  para manter uma correspondência direta entre origem e armazenamento.
* Os CSVs são lidos com ``encoding="utf-8"`` e ``dtype=str``. Assim, a
  ingestão não interpreta datas, números ou outros valores e não altera nomes
  de colunas.
* O leitor do pandas mantém campos vazios como nulos; nenhum valor é
  corrigido, preenchido, normalizado ou deduplicado.
* Todos os arquivos são validados antes de abrir o banco, evitando uma
  ingestão parcial quando a fonte está incompleta.
* As tabelas usam ``CREATE OR REPLACE`` para que reexecutar o processo seja
  determinístico e nunca acrescente linhas.
* O processo encerra com ``sys.exit(1)`` em caso de arquivo ausente, para
  deixar o erro explícito ao chamador.

Assumptions not specified:

* O comando é executado a partir da raiz do projeto; por isso ``raw`` e
  ``olist.duckdb`` são caminhos relativos ao diretório atual.
* Todo arquivo ``*.csv`` encontrado em ``raw`` faz parte do contrato, e o
  nome da tabela é o stem do arquivo sem a extensão.
"""

import sys
from pathlib import Path

import pandas as pd

from pipeline.db import conectar, criar_schema

RAW_DIR = Path("raw")


def _arquivos_esperados() -> list[Path]:
    return sorted(RAW_DIR.glob("*.csv"), key=lambda path: path.name)


def _validar_arquivos(arquivos: list[Path]) -> None:
    esperados = {
        "circuits.csv",
        "constructor_results.csv",
        "constructor_standings.csv",
        "constructors.csv",
        "driver_standings.csv",
        "drivers.csv",
        "lap_times.csv",
        "pit_stops.csv",
        "qualifying.csv",
        "races.csv",
        "results.csv",
        "seasons.csv",
        "sprint_results.csv",
        "status.csv",
    }
    encontrados = {arquivo.name for arquivo in arquivos}
    faltantes = sorted(esperados - encontrados)
    if faltantes:
        print(f"Arquivos ausentes em {RAW_DIR}: {', '.join(faltantes)}")
        sys.exit(1)


def ingerir() -> None:
    """Valida as fontes e recria todas as tabelas RAW."""
    arquivos = _arquivos_esperados()
    _validar_arquivos(arquivos)

    con = conectar()
    try:
        criar_schema(con, "raw")
        for arquivo in arquivos:
            tabela = arquivo.stem
            quadro = pd.read_csv(
                arquivo,
                encoding="utf-8",
                dtype=str,
                keep_default_na=True,
            )
            registro = f"_raw_{tabela}"
            con.register(registro, quadro)
            con.execute(
                f'CREATE OR REPLACE TABLE raw."{tabela}" AS '
                f'SELECT * FROM "{registro}"'
            )
            con.unregister(registro)
    finally:
        con.close()

    print(f"RAW: {len(arquivos)} tabelas recriadas")


if __name__ == "__main__":
    ingerir()
