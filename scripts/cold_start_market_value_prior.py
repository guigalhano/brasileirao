"""
Prior de "inicio de temporada" baseado em valor de mercado -- PRONTO PARA MARCO/2027.

Contexto: testamos isso em julho/2026 (rodada 19) e nao fez diferenca nenhuma,
porque com 18 rodadas de dados reais por time, a evidencia dos jogos ja domina
completamente qualquer prior financeiro (confirmado experimentalmente: com a
forca de regularizacao padrao do modelo, 0.01, os ratings saem identicos com
ou sem o prior, ate a terceira casa decimal).

Onde isso REALMENTE ajuda: nas primeiras 1-3 rodadas de uma temporada nova,
quando um time (especialmente recem-promovido) ainda nao tem nenhum jogo na
Serie A atual e o modelo teria que comecar do zero (rating = media da liga).
Nesse momento, o valor de mercado do elenco e uma estimativa melhor que "todo
mundo comeca igual".

COMO USAR (a partir de marco/2027, nas primeiras rodadas da temporada):
1. Colete o valor de mercado atual de cada time (ex: via tmquery, rodando
   localmente -- ver nota abaixo) e preencha MARKET_VALUE.
2. Chame fit_with_market_prior() no lugar do fit normal, passando reg_strength
   mais alto (testamos e serve ~1-10) SO enquanto os times tem poucos jogos
   na temporada corrente. A partir de ~5-8 jogos por time, pode voltar pro
   fit normal sem prior (reg_strength baixo, 0.01), porque os dados reais
   ja tomam conta.

Nota sobre coleta de dados: tentamos usar a biblioteca tmquery (PyPI) para
puxar isso automaticamente, mas ela precisa acessar transfermarkt.com
diretamente, e esse dominio nao esta liberado no sandbox do Claude. Rodando
localmente (fora do Claude), tmquery funciona normalmente:

    pip install tmquery
    from tmquery import TMQuery
    TMQuery().search_club("palmeiras").get_players(season="2026-27").csv()
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize


def fit_with_market_prior(df, teams, market_value, half_life=450.0, reg_strength=5.0,
                            coach_boost_map=None, boost_factor=6.0):
    """
    df: dataframe de partidas (colunas: date, home_team, away_team, home_goals, away_goals)
    teams: lista de times
    market_value: dict {time: valor_em_milhoes}
    reg_strength: forca da regularizacao em direcao ao prior (mais alto = mais
        peso pro valor de mercado; usar mais alto so no inicio da temporada,
        ex: 5-10; diminuir gradualmente conforme os times acumulam jogos).
    coach_boost_map: opcional, dict {time: data_troca_tecnico} para o ajuste
        de troca de tecnico (ver refit_with_coach_boost.py) -- normalmente
        vazio no inicio de temporada, ja que trocas recentes ainda nao existem.
    """
    team_idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    max_date = df["date"].max()
    days_ago = (max_date - df["date"]).dt.days.clip(lower=0)
    base_weight = 0.5 ** (days_ago / half_life)

    extra_weight = np.ones(len(df))
    if coach_boost_map:
        for i, row in df.iterrows():
            for team, change_date in coach_boost_map.items():
                if row.date >= pd.Timestamp(change_date) and (row.home_team == team or row.away_team == team):
                    extra_weight[i] *= boost_factor
    w = base_weight.values * extra_weight

    log_val = {t: np.log(v) for t, v in market_value.items()}
    mean_lv = np.mean(list(log_val.values()))
    std_lv = np.std(list(log_val.values()))
    target_std = 0.28  # espalhamento tipico dos ratings de ataque/defesa do modelo
    scale = target_std / std_lv if std_lv > 0 else 0.0

    prior = np.zeros(n)
    for t, i in team_idx.items():
        if t in log_val:
            prior[i] = scale * (log_val[t] - mean_lv)

    home_idx = df["home_team"].map(team_idx).values
    away_idx = df["away_team"].map(team_idx).values
    hg = df["home_goals"].values.astype(float)
    ag = df["away_goals"].values.astype(float)

    def unpack(p):
        return p[:n], p[n:2 * n], p[2 * n]

    def neg_ll(p):
        attack, defense, home_adv = unpack(p)
        lam_h = np.exp(attack[home_idx] - defense[away_idx] + home_adv)
        lam_a = np.exp(attack[away_idx] - defense[home_idx])
        ll = w * (hg * np.log(lam_h) - lam_h + ag * np.log(lam_a) - lam_a)
        reg = reg_strength * np.sum((attack - prior) ** 2) + reg_strength * np.sum((defense - prior) ** 2)
        return -np.sum(ll) + reg

    x0 = np.zeros(2 * n + 1)
    x0[2 * n] = 0.25
    cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
    res = minimize(neg_ll, x0, constraints=[cons], method="SLSQP", options={"maxiter": 500, "ftol": 1e-9})
    attack, defense, home_adv = unpack(res.x)
    ratings = {t: {"attack": attack[i], "defense": defense[i]} for t, i in team_idx.items()}
    return ratings, home_adv, res.success


# Exemplo de uso (rodar em marco/2027 com dados reais da nova temporada):
if __name__ == "__main__":
    print(__doc__)
    print("\nEste arquivo define fit_with_market_prior(); importe e chame com os")
    print("dados da temporada nova quando ela comecar.")
