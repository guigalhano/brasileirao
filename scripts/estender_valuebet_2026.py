"""
Estende o backtest de 4 modelos da aba "Value Betting" (const DATA embutido no
index.html) com rodadas novas de 2026.

CONTEXTO IMPORTANTE
--------------------
O array `const DATA` do painel Value Betting (5496 jogos, 2012-2026 ate a
rodada 18) foi originalmente gerado por um script que NAO foi preservado no
repositorio (veio de uma sessao anterior, ambiente que nao existe mais).
Este script e uma RECONSTRUCAO da metodologia, feita a partir da nota de
rodape da propria pagina:

- Value Bet Pinnacle: prob justa via devig da odds de fechamento da Pinnacle.
  NAO da pra estender pra 2026 -- a fonte (football-data.co.uk) ainda nao
  publica odds de fechamento da Pinnacle pra temporada em andamento.
- Value Bet Mercado: mesma logica, mas com a media (Avg) das casas como prob
  justa.
- Poisson + Elo (blend): (1) Dixon-Coles Poisson com decaimento temporal
  (meia-vida 2 anos) e correcao de placar baixo (tau de Dixon-Coles 1997),
  (2) Elo sequencial (K=15, sem look-ahead) convertido em probabilidade via
  regressao logistica multinomial (fit em 2014-2016), misturados 25%
  Poisson / 75% Elo.
- Favorito: sempre aposta no lado de menor cota (odds media como referencia).
- TODOS os modelos apostam na MELHOR cota disponivel (Max), nao na media --
  so a probabilidade "justa" usada pra achar valor e que muda por modelo.

VALIDACAO: recomputando essa formula pros 177 jogos de 2026 que ja existiam
(rodadas 1-18) e comparando com os valores ja salvos, o erro medio ficou em
~2 pontos percentuais de probabilidade -- boa mas nao perfeita reproducao,
esperado sem o codigo/hyperparametros exatos originais.

LIMITACAO CONHECIDA: o modelo original parece "esperar" um numero minimo de
jogos acumulados na temporada antes de dar palpite pra times recem-promovidos
(ex: Remo em 2026). Esta reconstrucao nao replica esse gate -- da palpite
assim que o time tiver qualquer historico na janela de dados usada.

COMO USAR
---------
1. Rode scripts/build_dataset_v2.py (ou equivalente) e garanta que
   data/matches_2012_2026.csv esta atualizado com os jogos novos que voce
   quer adicionar (resultados + odds AvgCH/AvgCD/AvgCA + MaxCH/MaxCD/MaxCA
   se disponivel -- sem Max, cai pra usar a media como preco tambem, o que
   e menos fiel ao "aposta na melhor cota" mas ainda funciona).
2. Ajuste NEW_MATCH_DATES abaixo pras datas dos jogos novos (formato YYYY-MM-DD).
3. Rode: python scripts/estender_valuebet_2026.py --repo-dir D:\\brasileirao
4. Confira visualmente o resultado antes de comitar (rode local com
   `python -m http.server` e abra a aba Value Betting).

Uso:
    python scripts/estender_valuebet_2026.py --repo-dir /caminho/para/repo --max-odds-csv caminho/pro/csv/com/MaxCH.csv
"""
import argparse
import csv
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression

# Nomes canonicos (matches_2012_2026.csv) -> nomes usados no array DATA (raw football-data)
NAME_MAP = {
    "Botafogo": "Botafogo RJ",
    "Flamengo": "Flamengo RJ",
    "Chapecoense": "Chapecoense-SC",
    "Atletico-PR": "Athletico-PR",
}


def canon_to_raw(t):
    return NAME_MAP.get(t, t)


def extract_data_array(index_html_text):
    m = re.search(r"const DATA = (\[\[.*?\]\]);", index_html_text, re.DOTALL)
    if not m:
        raise ValueError("Nao encontrei 'const DATA = [[...]]' no index.html")
    return json.loads(m.group(1))


def run_elo_sequential(matches_df, teams, k=15, omega=60):
    """Elo sequencial (sem look-ahead): retorna rating_diff ANTES de cada jogo
    e deixa os ratings finais em `ratings` (mutavel, pra continuar depois)."""
    ratings = {t: 1000.0 for t in teams}
    diffs = np.zeros(len(matches_df))
    for i, row in enumerate(matches_df.itertuples()):
        H, A = ratings[row.home], ratings[row.away]
        diffs[i] = H - A + omega
        eH = 1.0 / (1.0 + 10 ** ((A - H - omega) / 400))
        aH = 1.0 if row.home_goals > row.away_goals else (0.5 if row.home_goals == row.away_goals else 0.0)
        ratings[row.home] = H + k * (aH - eH)
        ratings[row.away] = A + k * ((1 - aH) - (1 - eH))
    return diffs, ratings


def tau_dc(x, y, lam, mu, rho):
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def fit_dixon_coles(train_df, teams, half_life_days=730.0):
    team_idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    max_date = train_df["dateSort"].max()
    weight = 0.5 ** ((max_date - train_df["dateSort"]).dt.days / half_life_days)
    home_idx = train_df.home.map(team_idx).values
    away_idx = train_df.away.map(team_idx).values
    hg = train_df.home_goals.values.astype(float)
    ag = train_df.away_goals.values.astype(float)
    w = weight.values
    lgamma_hg = np.array([math.lgamma(x + 1) for x in hg])
    lgamma_ag = np.array([math.lgamma(x + 1) for x in ag])
    low_idx = np.where((hg <= 1) & (ag <= 1))[0]

    def unpack(p):
        return p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]

    def neg_log_lik(p):
        attack, defense, home_adv, rho = unpack(p)
        lam = np.exp(attack[home_idx] - defense[away_idx] + home_adv)
        mu = np.exp(attack[away_idx] - defense[home_idx])
        ll = w * (hg * np.log(lam) - lam - lgamma_hg + ag * np.log(mu) - mu - lgamma_ag)
        tau_adj = np.zeros(len(hg))
        for i in low_idx:
            tau_adj[i] = math.log(max(tau_dc(int(hg[i]), int(ag[i]), lam[i], mu[i], rho), 1e-6))
        reg = 0.001 * (np.sum(attack ** 2) + np.sum(defense ** 2))
        return -np.sum(w * tau_adj) - np.sum(ll) + reg

    x0 = np.zeros(2 * n + 2)
    x0[2 * n] = 0.3
    cons = {"type": "eq", "fun": lambda p: np.sum(p[:n])}
    res = minimize(neg_log_lik, x0, constraints=[cons], method="SLSQP", options={"maxiter": 500, "ftol": 1e-9})
    attack, defense, home_adv, rho = unpack(res.x)
    ratings = {t: {"attack": attack[i], "defense": defense[i]} for t, i in team_idx.items()}
    return {"home_adv": home_adv, "rho": rho, "teams": ratings}


def dc_probs(home, away, dc, max_g=10):
    ratings, home_adv, rho = dc["teams"], dc["home_adv"], dc["rho"]
    h, a = ratings[home], ratings[away]
    lam = math.exp(h["attack"] - a["defense"] + home_adv)
    mu = math.exp(a["attack"] - h["defense"])
    pH = pD = pA = 0.0
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            p = math.exp(-lam) * lam ** i / math.factorial(i) * math.exp(-mu) * mu ** j / math.factorial(j)
            if i <= 1 and j <= 1:
                p *= tau_dc(i, j, lam, mu, rho)
            if i > j:
                pH += p
            elif i == j:
                pD += p
            else:
                pA += p
    tot = pH + pD + pA
    return pH / tot, pD / tot, pA / tot


def pick_by_ev(probs, odds):
    """probs, odds: dicts {'H':.., 'D':.., 'A':..}. Retorna (side, odds, prob, ev) do maior EV."""
    best = max(("H", "D", "A"), key=lambda s: probs[s] * odds[s] - 1)
    return best, round(odds[best], 2), round(probs[best], 3), round(probs[best] * odds[best] - 1, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--new-dates", default="", help="Datas (YYYY-MM-DD) separadas por virgula dos jogos novos a incluir. Se vazio, usa todo jogo de matches_2012_2026.csv que ainda nao esta no DATA array.")
    ap.add_argument("--max-odds-csv", default=None, help="CSV no formato football-data.co.uk com colunas Date,Home,Away,MaxCH,MaxCD,MaxCA para os jogos novos (opcional, senao usa a media como preco tambem)")
    args = ap.parse_args()
    repo = Path(args.repo_dir)

    index_path = repo / "index.html"
    content = index_path.read_text(encoding="utf-8")
    data = extract_data_array(content)
    print(f"DATA atual: {len(data)} jogos")

    cols = ["date", "dateSort", "season", "home", "away", "score", "result",
            "pinPick", "pinOdds", "pinProb", "pinEv", "pinWon",
            "mktPick", "mktOdds", "mktProb", "mktEv", "mktWon",
            "poiPick", "poiOdds", "poiProb", "poiEv", "poiWon",
            "favPick", "favOdds", "favWon"]
    hist = pd.DataFrame(data, columns=cols)
    hist["dateSort"] = pd.to_datetime(hist["dateSort"])
    hist["home_goals"] = hist["score"].str.split("-").str[0].astype(int)
    hist["away_goals"] = hist["score"].str.split("-").str[1].astype(int)
    hist = hist.sort_values("dateSort").reset_index(drop=True)

    matches_all = pd.read_csv(repo / "data" / "matches_2012_2026.csv")
    matches_all["home"] = matches_all.home_team.map(canon_to_raw)
    matches_all["away"] = matches_all.away_team.map(canon_to_raw)

    already = set(zip(hist.dateSort.dt.strftime("%Y-%m-%d"), hist.home, hist.away))
    new_df = matches_all[~matches_all.apply(lambda r: (r.date, r.home, r.away) in already, axis=1)].copy()
    if args.new_dates:
        wanted = set(args.new_dates.split(","))
        new_df = new_df[new_df.date.isin(wanted)]
    new_df = new_df.sort_values("date").reset_index(drop=True)
    print(f"Jogos novos a adicionar: {len(new_df)}")
    if new_df.empty:
        print("Nada a fazer.")
        return

    teams = sorted(set(hist.home) | set(hist.away) | set(new_df.home) | set(new_df.away))

    # ---- Elo sequencial: continua do historico + processa os jogos novos em ordem ----
    _, ratings_elo = run_elo_sequential(hist, teams)
    fit_mask = (hist.season >= 2014) & (hist.season < 2017)
    diffs_fit, _ = run_elo_sequential(hist[fit_mask].reset_index(drop=True), teams)
    clf = LogisticRegression(max_iter=1000)
    clf.fit(diffs_fit.reshape(-1, 1), hist.loc[fit_mask, "result"].values)

    elo_diffs_new = []
    for row in new_df.itertuples():
        H, A = ratings_elo[row.home], ratings_elo[row.away]
        elo_diffs_new.append(H - A + 60)
        eH = 1.0 / (1.0 + 10 ** ((A - H - 60) / 400))
        aH = 1.0 if row.home_goals > row.away_goals else (0.5 if row.home_goals == row.away_goals else 0.0)
        ratings_elo[row.home] = H + 15 * (aH - eH)
        ratings_elo[row.away] = A + 15 * ((1 - aH) - (1 - eH))
    elo_probs = clf.predict_proba(np.array(elo_diffs_new).reshape(-1, 1))
    classes = list(clf.classes_)

    # ---- Dixon-Coles: fit usando TODO o historico ja conhecido (ate o ultimo jogo do DATA atual) ----
    dc = fit_dixon_coles(hist, teams)
    print(f"Dixon-Coles: home_adv={dc['home_adv']:.4f} rho={dc['rho']:.4f}")

    # ---- odds Max (se fornecido), senao usa a media como preco tambem ----
    max_odds_by_key = {}
    if args.max_odds_csv:
        mo = pd.read_csv(args.max_odds_csv)
        mo["date"] = pd.to_datetime(mo["Date"], format="%d/%m/%Y").dt.strftime("%Y-%m-%d")
        for r in mo.itertuples():
            max_odds_by_key[(r.date, r.Home, r.Away)] = (r.MaxCH, r.MaxCD, r.MaxCA)

    new_rows = []
    for i, row in enumerate(new_df.itertuples()):
        result = "H" if row.home_goals > row.away_goals else ("D" if row.home_goals == row.away_goals else "A")
        score = f"{row.home_goals}-{row.away_goals}"
        avg_odds = {"H": row.avg_odds_home, "D": row.avg_odds_draw, "A": row.avg_odds_away}
        key = (row.date, row.home_team, row.away_team)
        max_h, max_d, max_a = max_odds_by_key.get(key, (row.avg_odds_home, row.avg_odds_draw, row.avg_odds_away))
        max_odds = {"H": max_h, "D": max_d, "A": max_a}

        overround = sum(1 / avg_odds[s] for s in "HDA")
        mkt_probs = {s: (1 / avg_odds[s]) / overround for s in "HDA"}

        if row.home in dc["teams"] and row.away in dc["teams"]:
            pH, pD, pA = dc_probs(row.home, row.away, dc)
        else:
            pH = pD = pA = None

        eH, eD, eA = (elo_probs[i][classes.index(c)] for c in ("H", "D", "A"))
        if pH is not None:
            blend = {"H": 0.25 * pH + 0.75 * eH, "D": 0.25 * pD + 0.75 * eD, "A": 0.25 * pA + 0.75 * eA}
        else:
            blend = {"H": eH, "D": eD, "A": eA}  # sem historico Poisson ainda: usa so Elo

        mktPick, mktOdds, mktProb, mktEv = pick_by_ev(mkt_probs, max_odds)
        poiPick, poiOdds, poiProb, poiEv = pick_by_ev(blend, max_odds)
        favPick = min("HDA", key=lambda s: avg_odds[s])
        favOdds = round(max_odds[favPick], 2)

        new_rows.append([
            pd.to_datetime(row.date).strftime("%d/%m/%Y"), row.date, 2026, row.home, row.away, score, result,
            None, None, None, None, None,
            mktPick, mktOdds, mktProb, mktEv, mktPick == result,
            poiPick, poiOdds, poiProb, poiEv, poiPick == result,
            favPick, favOdds, favPick == result,
        ])

    data.extend(new_rows)

    def to_js(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        return repr(v)

    rows_js = ",".join("[" + ",".join(to_js(x) for x in row) + "]" for row in data)
    new_block = "const DATA = [" + rows_js + "];"
    new_content = re.sub(r"const DATA = \[\[.*?\]\];", lambda m: new_block, content, count=1, flags=re.DOTALL)
    index_path.write_text(new_content, encoding="utf-8")
    print(f"OK: index.html atualizado, {len(data)} jogos no total ({len(new_rows)} novos).")


if __name__ == "__main__":
    main()
