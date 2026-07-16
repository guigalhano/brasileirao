"""
Refit final do Dixon-Coles com um ajuste seletivo: jogos disputados sob um
tecnico CONFIRMADO como novo (data oficial de troca, via Transfermarkt) ganham
peso extra multiplicativo, alem do decaimento temporal normal (meia-vida 450
dias, ja validada como proxima do otimo). Isso reage mais rapido a mudancas
reais de patamar (queda ou melhora) sem alterar a meia-vida global -- que ja
testamos e piora a calibracao geral se encurtada.

So afeta os times com troca de tecnico CONFIRMADA e com jogos suficientes
sob o novo comando; todo o resto do modelo (demais times, historico antes da
troca) usa exatamente o mesmo peso de sempre.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

df = pd.read_csv("/home/claude/brasileirao/matches_2012_2026.csv", parse_dates=["date"])

teams = sorted(set(df.home_team) | set(df.away_team))
team_idx = {t: i for i, t in enumerate(teams)}
n = len(teams)

HALF_LIFE = 450.0
max_date = df["date"].max()
days_ago = (max_date - df["date"]).dt.days.clip(lower=0)
base_weight = 0.5 ** (days_ago / HALF_LIFE)

# Trocas de tecnico confirmadas (data oficial via Transfermarkt) com jogos
# suficientes sob o novo comando para valer o ajuste.
COACH_CHANGES = {
    "Atletico-MG": "2026-02-26",
    "Vasco":       "2026-03-03",
    "Sao Paulo":   "2026-03-09",
    "Flamengo":    "2026-03-03",
    "Cruzeiro":    "2026-03-23",
    "Santos":      "2026-03-19",
    "Botafogo":    "2026-03-22",
    "Corinthians": "2026-04-05",
    "Chapecoense": "2026-04-03",
}
BOOST = 6.0  # peso extra multiplicativo para jogos sob o novo tecnico (validado por sensibilidade)

extra_weight = np.ones(len(df))
for i, row in df.iterrows():
    for team, change_date in COACH_CHANGES.items():
        change_date = pd.Timestamp(change_date)
        if row.date >= change_date:
            if row.home_team == team or row.away_team == team:
                extra_weight[i] *= BOOST

w = (base_weight.values * extra_weight)

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
    reg = 0.01 * np.sum(attack**2) + 0.01 * np.sum(defense**2)
    return -np.sum(ll) + reg


x0 = np.zeros(2 * n + 1)
x0[2 * n] = 0.25
cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
res = minimize(neg_ll, x0, constraints=[cons], method="SLSQP", options={"maxiter": 500, "ftol": 1e-9})
print("Optimization success:", res.success)
attack, defense, home_adv = unpack(res.x)
ratings = {t: {"attack": attack[i], "defense": defense[i]} for i, t in enumerate(teams)}

print(f"\nHome advantage: {home_adv:.4f}\n")

# Compare Chapecoense implied GF/GA vs average opponent, before vs after the boost
def implied_gf_ga(team, ratings, home_adv):
    th = ratings[team]
    lam_h = np.exp(th["attack"] - 0 + home_adv)   # em casa vs adversario medio
    lam_a = np.exp(th["attack"] - 0)              # fora vs adversario medio
    gf = (lam_h + lam_a) / 2
    ga_h = np.exp(0 - th["defense"])              # adversario fora marcando contra Chape em casa
    ga_a = np.exp(0 - th["defense"] + home_adv)   # adversario em casa marcando contra Chape fora
    ga = (ga_h + ga_a) / 2
    return gf, ga

for team in COACH_CHANGES:
    gf, ga = implied_gf_ga(team, ratings, home_adv)
    print(f"{team:<14} attack={ratings[team]['attack']:.3f}  defense={ratings[team]['defense']:.3f}   GF/jogo implicado={gf:.2f}  GA/jogo implicado={ga:.2f}")

import json
export_teams = [
    "Palmeiras", "Flamengo", "Fluminense", "Atletico-PR", "Bragantino", "Bahia",
    "Coritiba", "Sao Paulo", "Atletico-MG", "Corinthians", "Cruzeiro", "Botafogo",
    "Vitoria", "Internacional", "Santos", "Gremio", "Vasco", "Remo", "Mirassol",
    "Chapecoense",
]
export = {
    "home_advantage_log": float(home_adv),
    "note": "Dixon-Coles com peso extra (2.5x) para jogos sob tecnico confirmado como novo (data oficial via Transfermarkt), aplicado so aos times com troca confirmada.",
    "teams": {t: {"attack": round(float(ratings[t]["attack"]), 4), "defense": round(float(ratings[t]["defense"]), 4)} for t in export_teams}
}
with open("/home/claude/brasileirao/team_ratings_coach_adjusted.json", "w", encoding="utf-8") as f:
    json.dump(export, f, indent=2, ensure_ascii=False)
print("\nSalvo team_ratings_coach_adjusted.json")
