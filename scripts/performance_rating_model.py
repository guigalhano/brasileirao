"""
Performance Rating a la soccerstats.com: PR = (2*team_pPPG + opponents_pPPG) / 3
where pPPG = performance points per game (win=1, draw=0.5, loss=0), computed
season-to-date (strictly before the current match, so no look-ahead), and
opponents_pPPG = average current pPPG of previously-faced opponents.

We turn this into a forecasting model the same way as ELO-Result/Goals/Odds:
rating_diff (PR_home - PR_away) is fed as a single covariate into a
multinomial logistic regression, fit on 2014-2016, evaluated out-of-sample
on 2017-2026 -- identical protocol to elo_odds_model.py for a fair comparison.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

df = pd.read_csv("/home/claude/brasileirao/matches_2012_2026.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
df = df.dropna(subset=["avg_odds_home", "avg_odds_draw", "avg_odds_away"]).reset_index(drop=True)
df["result"] = np.where(df.home_goals > df.away_goals, "H", np.where(df.home_goals == df.away_goals, "D", "A"))

MIN_GAMES = 3  # need at least this many games this season before PR is considered reliable

diffs = np.full(len(df), np.nan)

for season, sdf in df.groupby("season"):
    sdf = sdf.sort_values("date")
    points = {}   # team -> list of performance points this season so far
    cur_pppg = {}  # team -> current pPPG (updated after each match)

    for idx, row in sdf.iterrows():
        home, away = row.home_team, row.away_team
        h_games = points.get(home, [])
        a_games = points.get(away, [])

        if len(h_games) >= MIN_GAMES and len(a_games) >= MIN_GAMES:
            home_pppg = np.mean(h_games)
            away_pppg = np.mean(a_games)
            # opponents' pPPG: current pPPG of teams already faced (as of now)
            # (approximation of soccerstats' home/away-split opponent pPPG)
            h_opp_faced = [o for o in points.get(home + "__opp", [])]
            a_opp_faced = [o for o in points.get(away + "__opp", [])]
            h_opp_pppg = np.mean([cur_pppg.get(o, 0.5) for o in h_opp_faced]) if h_opp_faced else 0.5
            a_opp_pppg = np.mean([cur_pppg.get(o, 0.5) for o in a_opp_faced]) if a_opp_faced else 0.5

            PR_home = (2 * home_pppg + h_opp_pppg) / 3
            PR_away = (2 * away_pppg + a_opp_pppg) / 3
            diffs[idx] = PR_home - PR_away

        # update records AFTER computing this match's covariate (no look-ahead)
        pts_h = 1.0 if row.home_goals > row.away_goals else (0.5 if row.home_goals == row.away_goals else 0.0)
        pts_a = 1.0 - pts_h
        points.setdefault(home, []).append(pts_h)
        points.setdefault(away, []).append(pts_a)
        points.setdefault(home + "__opp", []).append(away)
        points.setdefault(away + "__opp", []).append(home)
        cur_pppg[home] = np.mean(points[home])
        cur_pppg[away] = np.mean(points[away])

df["pr_diff"] = diffs
valid = df.dropna(subset=["pr_diff"]).copy()
print(f"Matches with valid Performance Rating (>= {MIN_GAMES} games played by both sides this season): {len(valid)} / {len(df)}")

fit_mask = (valid.season >= 2014) & (valid.season < 2017)
test_mask = valid.season >= 2017
print(f"Fit: {fit_mask.sum()}  Test: {test_mask.sum()}")

X_fit = valid.loc[fit_mask, "pr_diff"].values.reshape(-1, 1)
y_fit = valid.loc[fit_mask, "result"].values
clf = LogisticRegression(max_iter=1000).fit(X_fit, y_fit)

X_test = valid.loc[test_mask, "pr_diff"].values.reshape(-1, 1)
y_test = valid.loc[test_mask, "result"].values
probs = clf.predict_proba(X_test)
classes = clf.classes_
idx = {c: i for i, c in enumerate(classes)}
eps = 1e-12
losses = [-np.log(max(p[idx[r]], eps)) for p, r in zip(probs, y_test)]
print(f"\nPerformance Rating log-loss (out-of-sample, {len(losses)} matches): {np.mean(losses):.4f}")

# Save coefficients + final team pPPG snapshot for potential later use
print("\nCoef:", clf.coef_.flatten(), "Intercept:", clf.intercept_.flatten())
