"""
ELO-Result, ELO-Goals, ELO-Odds for the Brasileirao, following Wunderlich &
Memmert (2018, PLOS ONE). Sequential Elo updates mean every prediction only
uses information strictly prior to that match -- no look-ahead by construction.
"""
import numpy as np
import pandas as pd

df = pd.read_csv("/home/claude/brasileirao/matches_2012_2026.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
df = df.dropna(subset=["avg_odds_home", "avg_odds_draw", "avg_odds_away"]).reset_index(drop=True)

inv_h = 1 / df.avg_odds_home
inv_d = 1 / df.avg_odds_draw
inv_a = 1 / df.avg_odds_away
overround = inv_h + inv_d + inv_a
df["mkt_pH"] = inv_h / overround
df["mkt_pD"] = inv_d / overround
df["mkt_pA"] = inv_a / overround
df["result"] = np.where(df.home_goals > df.away_goals, "H", np.where(df.home_goals == df.away_goals, "D", "A"))

teams = sorted(set(df.home_team) | set(df.away_team))


def run_elo(df, k, omega, mode="result", k0=None, lam=None, c=10.0, d=400.0):
    """mode in {'result','goals','odds'}. Returns array of rating_diff (Hi - Ai + omega) BEFORE each match."""
    ratings = {t: 1000.0 for t in teams}
    diffs = np.zeros(len(df))
    for i, row in df.iterrows():
        H = ratings[row.home_team]
        A = ratings[row.away_team]
        diffs[i] = H - A + omega
        eH = 1.0 / (1.0 + c ** ((A - H - omega) / d))
        eA = 1.0 - eH
        if mode == "result":
            aH = 1.0 if row.home_goals > row.away_goals else (0.5 if row.home_goals == row.away_goals else 0.0)
            aA = 1.0 - aH
            step = k
        elif mode == "goals":
            aH = 1.0 if row.home_goals > row.away_goals else (0.5 if row.home_goals == row.away_goals else 0.0)
            aA = 1.0 - aH
            delta = abs(row.home_goals - row.away_goals)
            step = k0 * (1 + delta) ** lam
        elif mode == "odds":
            aH = row.mkt_pH + 0.5 * row.mkt_pD
            aA = row.mkt_pA + 0.5 * row.mkt_pD
            step = k
        ratings[row.home_team] = H + step * (aH - eH)
        ratings[row.away_team] = A + step * (aA - eA)
    return diffs


# --- Split: 2012-2013 init only, 2014-2016 fit ordered-logit mapping, 2017-2026 held-out test ---
init_end = df.season < 2014
fit_mask = (df.season >= 2014) & (df.season < 2017)
test_mask = df.season >= 2017

print(f"Init: {init_end.sum()}  Fit: {fit_mask.sum()}  Test: {test_mask.sum()}")


def multinomial_fit_predict(rating_diff, result, fit_mask, test_mask):
    """Simple multinomial logistic regression (3-class) using rating_diff as
    the single covariate, fit on fit_mask, evaluated on test_mask."""
    from sklearn.linear_model import LogisticRegression
    X_fit = rating_diff[fit_mask].reshape(-1, 1)
    y_fit = result[fit_mask]
    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_fit, y_fit)
    X_test = rating_diff[test_mask].reshape(-1, 1)
    probs = clf.predict_proba(X_test)
    classes = clf.classes_
    return probs, classes


def log_loss_eval(probs, classes, result_test):
    idx = {c: i for i, c in enumerate(classes)}
    eps = 1e-12
    ll = 0.0
    for p_row, r in zip(probs, result_test):
        p = max(p_row[idx[r]], eps)
        ll += -np.log(p)
    return ll / len(result_test)


result_arr = df["result"].values

results_summary = []

# ELO-Result: grid over k
best = None
for k in [8, 10, 12, 14, 16, 20, 25]:
    diffs = run_elo(df, k=k, omega=60, mode="result")
    probs, classes = multinomial_fit_predict(diffs, result_arr, fit_mask.values, fit_mask.values)  # calibrate loss on fit set
    ll = log_loss_eval(probs, classes, result_arr[fit_mask.values])
    if best is None or ll < best[0]:
        best = (ll, k)
k_result = best[1]
diffs_result = run_elo(df, k=k_result, omega=60, mode="result")
probs, classes = multinomial_fit_predict(diffs_result, result_arr, fit_mask.values, test_mask.values)
ll_result = log_loss_eval(probs, classes, result_arr[test_mask.values])
results_summary.append(("ELO-Result", k_result, ll_result))

# ELO-Goals: grid over k0, lambda
best = None
for k0 in [2, 4, 6, 8]:
    for lam in [1.0, 1.2, 1.4, 1.6, 1.8]:
        diffs = run_elo(df, k=None, omega=60, mode="goals", k0=k0, lam=lam)
        probs, classes = multinomial_fit_predict(diffs, result_arr, fit_mask.values, fit_mask.values)
        ll = log_loss_eval(probs, classes, result_arr[fit_mask.values])
        if best is None or ll < best[0]:
            best = (ll, k0, lam)
k0_goals, lam_goals = best[1], best[2]
diffs_goals = run_elo(df, k=None, omega=60, mode="goals", k0=k0_goals, lam=lam_goals)
probs, classes = multinomial_fit_predict(diffs_goals, result_arr, fit_mask.values, test_mask.values)
ll_goals = log_loss_eval(probs, classes, result_arr[test_mask.values])
results_summary.append(("ELO-Goals", f"k0={k0_goals},lam={lam_goals}", ll_goals))

# ELO-Odds: grid over k
best = None
for k in [50, 100, 150, 175, 200, 250, 300, 400]:
    diffs = run_elo(df, k=k, omega=60, mode="odds")
    probs, classes = multinomial_fit_predict(diffs, result_arr, fit_mask.values, fit_mask.values)
    ll = log_loss_eval(probs, classes, result_arr[fit_mask.values])
    if best is None or ll < best[0]:
        best = (ll, k)
k_odds = best[1]
diffs_odds = run_elo(df, k=k_odds, omega=60, mode="odds")
probs, classes = multinomial_fit_predict(diffs_odds, result_arr, fit_mask.values, test_mask.values)
ll_odds = log_loss_eval(probs, classes, result_arr[test_mask.values])
results_summary.append(("ELO-Odds", k_odds, ll_odds))

# Betting odds themselves (market) as a benchmark forecaster
eps = 1e-12
mkt_ll = []
for _, row in df[test_mask].iterrows():
    p = {"H": row.mkt_pH, "D": row.mkt_pD, "A": row.mkt_pA}[row.result]
    mkt_ll.append(-np.log(max(p, eps)))
results_summary.append(("Betting Odds (mercado)", "-", np.mean(mkt_ll)))

print("\n" + "=" * 60)
print(f"{'Modelo':<26}{'Parametro':<18}{'Log-loss (menor=melhor)'}")
for name, param, ll in sorted(results_summary, key=lambda x: x[2]):
    print(f"{name:<26}{str(param):<18}{ll:.4f}")
