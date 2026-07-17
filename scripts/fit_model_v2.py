"""
fit_model_v2.py

Ajusta o modelo Dixon-Coles (attack/defense por time + vantagem de campo)
via maxima verossimilhanca ponderada por decaimento temporal (half-life),
usando os resultados historicos de matches_2012_2026.csv.

REGULARIZACAO ANCORADA EM xG REAL (mudanca de 16/07/2026)
------------------------------------------------------------
Antes, a regularizacao so puxava attack/defense pra perto de ZERO
(0.01 * soma dos quadrados), o que ignora completamente o xG real medido
(WhoScored/FootyStats) que ja usamos pra corrigir o modelo em
recalibrar_com_whoscored.py. Isso significa que toda vez que este script
rodasse de novo do zero, ele desfaria a calibracao e voltaria a superestimar
o xG em ~2x, como descobrimos e corrigimos manualmente.

Agora, se data/team_ratings_calibrado.json existir, a regularizacao passa a
puxar attack/defense dos times conhecidos pra PERTO DOS VALORES JA
CALIBRADOS por xG real (regularizacao "ridge" em torno de uma ancora, nao
em torno de zero), em vez de desfazer esse trabalho a cada re-fit. Times
sem calibracao (historicos/rebaixados) continuam regularizados pra zero
como antes.

Uso:
    python3 fit_model_v2.py --repo-dir /caminho/para/repo
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--half-life", type=float, default=450.0)
    ap.add_argument("--reg-zero", type=float, default=0.01,
                     help="peso da regularizacao pra zero (times sem calibracao de xG)")
    ap.add_argument("--reg-anchor", type=float, default=0.05,
                     help="peso da regularizacao ancorada nos ratings calibrados por xG real "
                          "(mais forte que reg-zero de proposito, pra nao desfazer a calibracao "
                          "a toa -- so deve ceder se os dados de resultados discordarem bastante)")
    args = ap.parse_args()
    repo = Path(args.repo_dir)

    df = pd.read_csv(repo / "data" / "matches_2012_2026.csv", parse_dates=["date"])

    teams = sorted(set(df.home_team) | set(df.away_team))
    team_idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    max_date = df["date"].max()
    df["days_ago"] = (max_date - df["date"]).dt.days
    df["weight"] = 0.5 ** (df["days_ago"] / args.half_life)

    home_idx = df["home_team"].map(team_idx).values
    away_idx = df["away_team"].map(team_idx).values
    hg = df["home_goals"].values.astype(float)
    ag = df["away_goals"].values.astype(float)
    w = df["weight"].values

    # Ancora de xG real: vetor com o valor calibrado por time (ou NaN se nao
    # tiver, caindo pra regularizacao-pra-zero padrao nesse caso)
    calib_path = repo / "data" / "team_ratings_calibrado.json"
    anchor_attack = np.full(n, np.nan)
    anchor_defense = np.full(n, np.nan)
    if calib_path.exists():
        calib = json.loads(calib_path.read_text(encoding="utf-8"))
        for team, vals in calib["teams"].items():
            if team in team_idx:
                anchor_attack[team_idx[team]] = vals["attack"]
                anchor_defense[team_idx[team]] = vals["defense"]
        n_anchored = np.sum(~np.isnan(anchor_attack))
        print(f"Usando {calib_path.name} como ancora de regularizacao para {n_anchored} times.")
    else:
        print(f"AVISO: {calib_path.name} nao encontrado -- regularizando todo mundo pra zero "
              f"(sem ancora de xG real). Rode recalibrar_com_whoscored.py antes pra ter esse dado.")

    has_anchor = ~np.isnan(anchor_attack)
    anchor_attack_filled = np.where(has_anchor, anchor_attack, 0.0)
    anchor_defense_filled = np.where(has_anchor, anchor_defense, 0.0)
    reg_weight = np.where(has_anchor, args.reg_anchor, args.reg_zero)

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
        reg = np.sum(reg_weight * (attack - anchor_attack_filled) ** 2) + \
              np.sum(reg_weight * (defense - anchor_defense_filled) ** 2)
        return -np.sum(ll) + reg

    x0 = np.zeros(2 * n + 1)
    x0[:n] = anchor_attack_filled
    x0[n : 2 * n] = anchor_defense_filled
    x0[2 * n] = 0.25

    cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
    res = minimize(neg_log_lik, x0, constraints=[cons], method="SLSQP",
                    options={"maxiter": 500, "ftol": 1e-9})

    print("Optimization success:", res.success, res.message)
    attack, defense, home_adv = unpack(res.x)

    ratings = pd.DataFrame({"team": teams, "attack": attack, "defense": defense})

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

    out_dir = repo / "data"
    ratings.to_csv(out_dir / "team_ratings_v2_all.csv", index=False)
    cur.to_csv(out_dir / "team_ratings_v2_current.csv", index=False)

    out_json = {
        "generated_note": (
            f"Dixon-Coles Poisson model fit on matches_2012_2026.csv, time-decayed, "
            f"half-life {args.half_life} days. Regularizado em torno dos ratings calibrados "
            f"por xG real (team_ratings_calibrado.json) quando disponivel."
        ),
        "home_advantage_log": float(home_adv),
        "teams": {
            row["team"]: {"attack": round(row["attack"], 4), "defense": round(row["defense"], 4)}
            for _, row in cur.iterrows()
        },
    }
    with open(out_dir / "team_ratings_final_v2.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2, ensure_ascii=False)

    print(f"\nSalvo em {out_dir}/team_ratings_v2_all.csv, team_ratings_v2_current.csv, "
          f"team_ratings_final_v2.json")


if __name__ == "__main__":
    main()
