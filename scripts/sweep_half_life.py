"""
Testa diferentes valores de meia-vida (half-life) para o decaimento temporal
do Dixon-Coles, usando a mesma validacao walk-forward rigorosa (fit em
temporadas anteriores, teste fora da amostra em 2017-2026) para comparar
log-loss contra o mercado.

Objetivo: achar a meia-vida que da a melhor calibracao geral, nao so
"consertar" o caso do Chapecoense por acaso.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

df_all = pd.read_csv("/home/claude/brasileirao/matches_2012_2026.csv", parse_dates=["date"])
df_all = df_all.dropna(subset=["avg_odds_home", "avg_odds_draw", "avg_odds_away"]).reset_index(drop=True)


def fit_dixon_coles(train_df, as_of_date, half_life):
    teams = sorted(set(train_df.home_team) | set(train_df.away_team))
    team_idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    days_ago = (as_of_date - train_df["date"]).dt.days.clip(lower=0)
    weight = 0.5 ** (days_ago / half_life)

    home_idx = train_df["home_team"].map(team_idx).values
    away_idx = train_df["away_team"].map(team_idx).values
    hg = train_df["home_goals"].values.astype(float)
    ag = train_df["away_goals"].values.astype(float)
    w = weight.values

    def unpack(p):
        return p[:n], p[n:2 * n], p[2 * n]

    def neg_ll(p):
        attack, defense, home_adv = unpack(p)
        lam_h = np.exp(attack[home_idx] - defense[away_idx] + home_adv)
        lam_a = np.exp(attack[away_idx] - defense[home_idx])
        ll = w * (hg * np.log(lam_h) - lam_h + ag * np.log(lam_a) - lam_a)
        reg = 0.01 * np.sum(attack**2) + 0.01 * np.sum(defense**2)
        return -np.sum(ll) + reg

    x0 = np.zeros(2 * n + 1)
    x0[2 * n] = 0.25
    cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
    res = minimize(neg_ll, x0, constraints=[cons], method="SLSQP", options={"maxiter": 300, "ftol": 1e-8})
    attack, defense, home_adv = unpack(res.x)
    return {t: {"attack": attack[i], "defense": defense[i]} for i, t in enumerate(teams)}, home_adv


def evaluate_half_life(half_life):
    """Walk-forward: for each season 2015-2026, fit on all prior seasons with
    this half-life, predict H/D/A for that season's matches, compute log-loss."""
    from scipy.stats import poisson

    records = []
    for season in range(2015, 2027):
        train_df = df_all[df_all.season < season]
        test_df = df_all[df_all.season == season]
        if len(train_df) < 300 or len(test_df) == 0:
            continue
        as_of_date = train_df["date"].max()
        ratings, home_adv = fit_dixon_coles(train_df, as_of_date, half_life)

        for _, row in test_df.iterrows():
            th = ratings.get(row.home_team, {"attack": 0, "defense": 0})
            ta = ratings.get(row.away_team, {"attack": 0, "defense": 0})
            lam_h = np.exp(th["attack"] - ta["defense"] + home_adv)
            lam_a = np.exp(ta["attack"] - th["defense"])
            ph = poisson.pmf(np.arange(10), lam_h)
            pa = poisson.pmf(np.arange(10), lam_a)
            M = np.outer(ph, pa)
            p_h = np.tril(M, -1).sum()
            p_d = np.trace(M)
            p_a = np.triu(M, 1).sum()
            result = "H" if row.home_goals > row.away_goals else ("D" if row.home_goals == row.away_goals else "A")
            p = {"H": p_h, "D": p_d, "A": p_a}[result]
            records.append(-np.log(max(p, 1e-12)))

    return np.mean(records), len(records)


HALF_LIVES = [120, 150, 180, 220, 260, 300, 350, 450, 600]
print(f"{'Meia-vida (dias)':<18}{'Log-loss':<12}{'N jogos'}")
results = []
for hl in HALF_LIVES:
    ll, n = evaluate_half_life(hl)
    results.append((hl, ll, n))
    print(f"{hl:<18}{ll:<12.4f}{n}")

best = min(results, key=lambda x: x[1])
print(f"\nMelhor meia-vida: {best[0]} dias (log-loss {best[1]:.4f})")
print("Referencia -- meia-vida atual (450 dias) e mercado (log-loss ~1.001)")
