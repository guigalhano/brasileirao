import numpy as np
import pandas as pd
from scipy.optimize import minimize

df = pd.read_csv("/home/claude/brasileirao/matches_2012_2026.csv", parse_dates=["date"])

teams = sorted(set(df.home_team) | set(df.away_team))
team_idx = {t: i for i, t in enumerate(teams)}
n = len(teams)

half_life = 450.0
max_date = df["date"].max()
df["days_ago"] = (max_date - df["date"]).dt.days
df["weight"] = 0.5 ** (df["days_ago"] / half_life)

home_idx = df["home_team"].map(team_idx).values
away_idx = df["away_team"].map(team_idx).values
hg = df["home_goals"].values.astype(float)
ag = df["away_goals"].values.astype(float)
w = df["weight"].values


def unpack(params):
    attack = params[:n]
    defense = params[n : 2 * n]
    home_adv = params[2 * n]
    return attack, defense, home_adv


def neg_log_lik(params):
    attack, defense, home_adv = unpack(params)
    lam_h = np.exp(attack[home_idx] - defense[away_idx] + home_adv)
    lam_a = np.exp(attack[away_idx] - defense[home_idx])
    ll = w * (hg * np.log(lam_h) - lam_h + ag * np.log(lam_a) - lam_a)
    reg = 0.01 * np.sum(attack**2) + 0.01 * np.sum(defense**2)
    return -np.sum(ll) + reg


x0 = np.zeros(2 * n + 1)
x0[2 * n] = 0.25

cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
res = minimize(neg_log_lik, x0, constraints=[cons], method="SLSQP",
                options={"maxiter": 500, "ftol": 1e-9})

print("Optimization success:", res.success, res.message)
attack, defense, home_adv = unpack(res.x)

ratings = pd.DataFrame({"team": teams, "attack": attack, "defense": defense})

# Only keep current 2026 Serie A teams for the final export (others are
# historical / relegated clubs still useful for training but not for the picker)
current_teams = [
    "Palmeiras", "Flamengo", "Fluminense", "Atletico-PR", "Bragantino", "Bahia",
    "Coritiba", "Sao Paulo", "Atletico-MG", "Corinthians", "Cruzeiro", "Botafogo",
    "Vitoria", "Internacional", "Santos", "Gremio", "Vasco", "Remo", "Mirassol",
    "Chapecoense",
]

print("\nHome advantage (log-scale):", home_adv)
print("\nAll current Serie A 2026 teams, sorted by attack:")
cur = ratings[ratings.team.isin(current_teams)].sort_values("attack", ascending=False)
print(cur.to_string(index=False))

ratings.to_csv("/home/claude/brasileirao/team_ratings_v2_all.csv", index=False)
cur.to_csv("/home/claude/brasileirao/team_ratings_v2_current.csv", index=False)
with open("/home/claude/brasileirao/home_adv_v2.txt", "w") as f:
    f.write(str(home_adv))
print("\nSaved.")
