"""Dashboard histórico da Fórmula 1."""

import pandas as pd
import streamlit as st

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
)


st.set_page_config(
    page_title="F1 | Panorama histórico",
    page_icon=":material/sports_motorsports:",
    layout="wide",
)

MARTS = [
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
]


@st.cache_data
def carregar_marts() -> dict[str, pd.DataFrame]:
    return ler(MARTS)


def panorama(marts: dict[str, pd.DataFrame]) -> None:
    st.header("Panorama histórico da Fórmula 1")
    kpi = marts["overview_kpis"].iloc[0]
    with st.container(horizontal=True):
        st.metric("Temporadas analisadas", formatar_numero(kpi["total_seasons"]), border=True)
        st.metric("Pilotos campeões únicos", formatar_numero(kpi["unique_champion_drivers"]), border=True)
        st.metric("Equipes campeãs únicas", formatar_numero(kpi["unique_champion_constructors"]), border=True)
        st.metric("GPs realizados", formatar_numero(kpi["total_races"]), border=True)
        st.metric(
            "Nacionalidade com mais títulos",
            str(kpi["top_champion_nationality"]),
            f"{formatar_numero(kpi['top_champion_nationality_titles'])} títulos",
            border=True,
        )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Vitórias por nacionalidade")
            st.plotly_chart(grafico_nacionalidade(marts["nationality_stats"]), width="stretch")
    with right:
        with st.container(border=True):
            st.subheader("Títulos de construtores")
            st.plotly_chart(grafico_titulos_construtores(marts["constructor_titles_by_decade"]), width="stretch")

    with st.container(border=True):
        st.subheader("Evolução histórica de vitórias")
        st.plotly_chart(grafico_vitorias_construtores(marts["constructor_wins_by_year"]), width="stretch")

    with st.container(border=True):
        st.subheader("Hall da fama")
        fame = marts["hall_of_fame"].copy()
        fame["win_efficiency_pct"] = fame["win_efficiency_pct"].map(formatar_percentual)
        fame = fame.rename(
            columns={
                "driver": "Piloto",
                "titles": "Títulos",
                "wins": "Vitórias",
                "podiums": "Pódios",
                "poles": "Poles",
                "races": "Corridas",
                "win_efficiency_pct": "Eficiência",
            }
        )
        st.dataframe(fame.drop(columns=["driverId"]), hide_index=True, width="stretch", alt="Ranking histórico dos pilotos")


def temporada(marts: dict[str, pd.DataFrame]) -> None:
    st.header("Análise detalhada por temporada")
    anos = marts["season_kpis"]["year"].dropna().astype(int).tolist()
    ano = st.selectbox("Ano da temporada", anos, index=len(anos) - 1)
    kpi = filtrar_ano(marts["season_kpis"], ano).iloc[0]

    with st.container(horizontal=True):
        st.metric("Campeão de pilotos", str(kpi["driver_champion"]), f"{formatar_numero(kpi['driver_champion_points'], 1)} pontos", border=True)
        st.metric("Campeão de construtores", str(kpi["constructor_champion"]), f"{formatar_numero(kpi['constructor_champion_points'], 1)} pontos", border=True)
        st.metric("Corridas", formatar_numero(kpi["races"]), border=True)
        st.metric("Abandonos", formatar_numero(kpi["dnfs"]), border=True)

    progressao = filtrar_ano(marts["championship_progression"], ano)
    gap = filtrar_ano(marts["championship_gap"], ano)
    grid = filtrar_ano(marts["grid_performance"], ano)
    pits = filtrar_ano(marts["pit_stop_performance"], ano)
    dnfs = filtrar_ano(marts["dnf_reliability"], ano)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(grafico_progressao(progressao), width="stretch")
    with right:
        st.plotly_chart(grafico_gap(gap), width="stretch")
    st.plotly_chart(grafico_grid(grid), width="stretch")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(grafico_pit_stops(pits), width="stretch")
    with right:
        st.plotly_chart(grafico_dnfs(dnfs), width="stretch")


marts = carregar_marts()
tab_panorama, tab_temporada = st.tabs(["Panorâmico histórico", "Análise por temporada"])
with tab_panorama:
    panorama(marts)
with tab_temporada:
    temporada(marts)
