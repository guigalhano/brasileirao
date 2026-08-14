#!/usr/bin/env python3
"""
Combina Elo-Odds e Dixon-Coles e mede se a mistura realmente ganha dos dois.

POR QUE ISSO EXISTE
-------------------
O repo tinha dois modelos que nunca se encontraram:

  - Elo-Odds, anunciado no README como o melhor modelo nao-mercado
    (log-loss 1.023 contra 1.002 do mercado), mas com path de sandbox
    hardcoded -- nunca rodou aqui;
  - Dixon-Coles Poisson, que e o que de fato alimenta o site.

Eles erram de formas diferentes: o Elo-Odds destila a opiniao do mercado
(bom em nivel de time, cego pra placar), o Dixon-Coles modela gols
(da placar e over/under, mas reage devagar). Misturar PODE ganhar dos dois
-- ou pode nao ganhar. Este script mede, nao supoe.

PROTOCOLO (o ponto que faz a medicao valer)
-------------------------------------------
  2012-2013  aquecimento do Elo (nenhuma avaliacao)
  2014-2016  ajuste do mapeamento ordered-logit do Elo
  2017-2021  VALIDACAO: e aqui que o peso w da mistura e escolhido
  2022-2026  TESTE: numero reportado, nunca usado pra escolher nada

Escolher w no proprio teste inflaria o resultado -- seria o modelo se
avaliando na prova que ja viu. O Dixon-Coles e reajustado a cada mes usando
so partidas anteriores aquele mes, e SEM a ancora de xG do
team_ratings_calibrado.json: essa ancora e derivada da temporada inteira e
vazaria o futuro para dentro do passado.

Uso:
    python scripts/ensemble_model.py
    python scripts/ensemble_model.py --half-life 450 --salvar
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
EPS = 1e-12
CLASSES = ("H", "D", "A")


def carregar():
    df = (pd.read_csv(DATA / "matches_2012_2026.csv", parse_dates=["date"])
            .sort_values("date").reset_index(drop=True))
    df = df.dropna(subset=["avg_odds_home", "avg_odds_draw", "avg_odds_away"])
    df = df.reset_index(drop=True)
    inv = 1 / df[["avg_odds_home", "avg_odds_draw", "avg_odds_away"]].values
    df[["mkt_pH", "mkt_pD", "mkt_pA"]] = inv / inv.sum(axis=1, keepdims=True)
    df["result"] = np.where(df.home_goals > df.away_goals, "H",
                            np.where(df.home_goals == df.away_goals, "D", "A"))
    return df


# ---------------------------------------------------------------- Elo-Odds
def elo_odds_diffs(df, k=250, omega=60, c=10.0, d=400.0):
    """Rating diff ANTES de cada jogo. Sequencial: nunca olha o futuro."""
    times = sorted(set(df.home_team) | set(df.away_team))
    r = {t: 1000.0 for t in times}
    diffs = np.zeros(len(df))
    for i, row in enumerate(df.itertuples()):
        H, A = r[row.home_team], r[row.away_team]
        diffs[i] = H - A + omega
        eH = 1.0 / (1.0 + c ** ((A - H - omega) / d))
        aH = row.mkt_pH + 0.5 * row.mkt_pD
        aA = row.mkt_pA + 0.5 * row.mkt_pD
        r[row.home_team] = H + k * (aH - eH)
        r[row.away_team] = A + k * (aA - (1.0 - eH))
    return diffs


# ------------------------------------------------------------- Dixon-Coles
def ajustar_dc(hist, times, half_life, reg=0.05):
    """Ajusta ataque/defesa/mando em `hist`. Sem ancora externa: a ancora do
    pipeline vem da temporada corrente e vazaria o futuro neste backtest."""
    idx = {t: i for i, t in enumerate(times)}
    n = len(times)
    hi = hist.home_team.map(idx).values
    ai = hist.away_team.map(idx).values
    hg = hist.home_goals.values.astype(float)
    ag = hist.away_goals.values.astype(float)
    dias = (hist.date.max() - hist.date).dt.days.values
    w = 0.5 ** (dias / half_life)

    def nll(p):
        atk, dfn, ha = p[:n], p[n:2 * n], p[2 * n]
        lam_h = np.exp(atk[hi] - dfn[ai] + ha)
        lam_a = np.exp(atk[ai] - dfn[hi])
        ll = w * (hg * np.log(lam_h) - lam_h + ag * np.log(lam_a) - lam_a)
        return -ll.sum() + reg * (np.sum(p[:2 * n] ** 2))

    x0 = np.zeros(2 * n + 1)
    x0[2 * n] = 0.25
    res = minimize(nll, x0, method="SLSQP", options={"maxiter": 300, "ftol": 1e-8},
                   constraints=[{"type": "eq", "fun": lambda p: p[:n].sum()}])
    atk, dfn, ha = res.x[:n], res.x[n:2 * n], res.x[2 * n]
    return {"atk": atk, "dfn": dfn, "ha": ha, "idx": idx}


def probs_dc(m, home, away, max_gols=10):
    """P(H), P(D), P(A) por Poisson bivariada independente."""
    if home not in m["idx"] or away not in m["idx"]:
        return None
    h, a = m["idx"][home], m["idx"][away]
    lh = np.exp(m["atk"][h] - m["dfn"][a] + m["ha"])
    la = np.exp(m["atk"][a] - m["dfn"][h])
    k = np.arange(max_gols + 1)
    fat = np.array([math.factorial(int(i)) for i in k], dtype=float)
    ph = np.exp(-lh) * lh ** k / fat
    pa = np.exp(-la) * la ** k / fat
    M = np.outer(ph, pa)
    pH = np.triu(M, 1).sum()
    pD = np.trace(M)
    pA = np.tril(M, -1).sum()
    tot = pH + pD + pA
    return np.array([pH / tot, pD / tot, pA / tot])


def dc_walk_forward(df, half_life):
    """Reajusta o DC no inicio de cada mes, so com partidas anteriores."""
    times = sorted(set(df.home_team) | set(df.away_team))
    saida = np.full((len(df), 3), np.nan)
    df = df.assign(_mes=df.date.dt.to_period("M"))
    meses = sorted(df.loc[df.season >= 2017, "_mes"].unique())
    print(f"  Dixon-Coles walk-forward: {len(meses)} reajustes mensais...")
    for j, mes in enumerate(meses, 1):
        hist = df[df._mes < mes]
        if len(hist) < 200:
            continue
        modelo = ajustar_dc(hist, times, half_life)
        alvo = df.index[df._mes == mes]
        for i in alvo:
            p = probs_dc(modelo, df.at[i, "home_team"], df.at[i, "away_team"])
            if p is not None:
                saida[i] = p
        if j % 20 == 0:
            print(f"    {j}/{len(meses)} ({mes})")
    return saida


# ------------------------------------------------------------- avaliacao
def log_loss(probs, results):
    idx = {c: i for i, c in enumerate(CLASSES)}
    p = np.array([max(probs[i][idx[r]], EPS) for i, r in enumerate(results)])
    return float(-np.log(p).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half-life", type=float, default=450.0)
    ap.add_argument("--k-elo", type=float, default=250.0)
    ap.add_argument("--salvar", action="store_true",
                    help="grava data/ensemble_weights.json com o peso escolhido")
    args = ap.parse_args()

    df = carregar()
    print(f"{len(df)} jogos com odds, {df.date.min().date()} a {df.date.max().date()}\n")

    fit = (df.season >= 2014) & (df.season < 2017)
    val = (df.season >= 2017) & (df.season < 2022)
    tst = df.season >= 2022
    print(f"Ajuste Elo   2014-2016: {fit.sum():5} jogos")
    print(f"Validacao    2017-2021: {val.sum():5} jogos  (escolhe o peso w)")
    print(f"Teste        2022-2026: {tst.sum():5} jogos  (numero reportado)\n")

    print("Rodando Elo-Odds...")
    diffs = elo_odds_diffs(df, k=args.k_elo)
    clf = LogisticRegression(max_iter=1000)
    clf.fit(diffs[fit.values].reshape(-1, 1), df.result[fit].values)
    ordem = [list(clf.classes_).index(c) for c in CLASSES]
    p_elo = clf.predict_proba(diffs.reshape(-1, 1))[:, ordem]

    print("Rodando Dixon-Coles...")
    p_dc = dc_walk_forward(df, args.half_life)

    p_mkt = df[["mkt_pH", "mkt_pD", "mkt_pA"]].values
    ok = ~np.isnan(p_dc).any(axis=1)
    res = df.result.values

    def avaliar(mask, w):
        m = mask.values & ok
        mistura = w * p_elo[m] + (1 - w) * p_dc[m]
        return log_loss(mistura, res[m])

    # --- peso escolhido SO na validacao ---
    pesos = np.arange(0, 1.001, 0.05)
    perdas_val = [avaliar(val, w) for w in pesos]
    w_star = float(pesos[int(np.argmin(perdas_val))])

    print(f"\nPeso escolhido na validacao: w = {w_star:.2f} "
          f"({w_star:.0%} Elo-Odds, {1 - w_star:.0%} Dixon-Coles)\n")

    mt = tst.values & ok
    linhas = [
        ("Mercado (referencia)", log_loss(p_mkt[mt], res[mt])),
        (f"Ensemble w={w_star:.2f}", avaliar(tst, w_star)),
        ("Elo-Odds puro", avaliar(tst, 1.0)),
        ("Dixon-Coles puro", avaliar(tst, 0.0)),
    ]
    print("=" * 62)
    print(f"TESTE 2022-2026 ({mt.sum()} jogos){'':10}log-loss (menor=melhor)")
    print("=" * 62)
    for nome, ll in sorted(linhas, key=lambda x: x[1]):
        print(f"  {nome:<34}{ll:.4f}")

    ll_ens = avaliar(tst, w_star)
    ll_elo, ll_dc = avaliar(tst, 1.0), avaliar(tst, 0.0)
    melhor_puro = min(ll_elo, ll_dc)
    ganho = melhor_puro - ll_ens

    # O ganho medio sozinho nao diz se e sinal ou ruido de amostra. Bootstrap
    # pareado: reamostra os jogos do teste e ve em que fracao das reamostragens
    # a mistura continua na frente. Se o intervalo cruza zero, o ganho nao se
    # distingue de acaso e nao justifica trocar o modelo de producao.
    idxc = {c: i for i, c in enumerate(CLASSES)}
    res_t = res[mt]
    p_ens = w_star * p_elo[mt] + (1 - w_star) * p_dc[mt]
    p_pur = p_elo[mt] if ll_elo <= ll_dc else p_dc[mt]
    perda = lambda P: np.array([-np.log(max(P[i][idxc[r]], EPS))
                                for i, r in enumerate(res_t)])
    dif = perda(p_pur) - perda(p_ens)          # >0 = mistura melhor

    rng = np.random.default_rng(42)
    amostras = np.array([rng.choice(dif, size=len(dif), replace=True).mean()
                         for _ in range(5000)])
    lo, hi = np.percentile(amostras, [2.5, 97.5])
    frac = float((amostras > 0).mean())
    print(f"\nBootstrap pareado (5000 reamostragens, n={len(dif)}):")
    print(f"  ganho medio {dif.mean():+.4f}, IC95% [{lo:+.4f}, {hi:+.4f}]")
    print(f"  mistura a frente em {frac:.1%} das reamostragens")
    significativo = lo > 0

    print("\n" + "=" * 62)
    if significativo:
        print(f"VEREDITO: a mistura ganha do melhor modelo puro "
              f"({ganho:+.4f}) e o IC95% nao cruza zero -- ganho real.")
    elif ganho > 0:
        print(f"VEREDITO: a mistura ganha na media ({ganho:+.4f}), mas o "
              f"IC95% cruza zero -- indistinguivel de ruido de amostra.")
    else:
        print(f"VEREDITO: a mistura NAO ganha ({ganho:+.4f}). "
              f"Fique com o modelo puro melhor.")
    print("=" * 62)

    if args.salvar:
        alvo = DATA / "ensemble_weights.json"
        alvo.write_text(json.dumps({
            "w_elo": w_star,
            "w_dixon_coles": round(1 - w_star, 4),
            "half_life": args.half_life,
            "k_elo": args.k_elo,
            "validacao": "2017-2021",
            "teste": "2022-2026",
            "log_loss_teste": {
                "ensemble": round(ll_ens, 4),
                "elo_odds": round(ll_elo, 4),
                "dixon_coles": round(ll_dc, 4),
                "mercado": round(log_loss(p_mkt[mt], res[mt]), 4),
            },
            "n_jogos_teste": int(mt.sum()),
        }, indent=2), encoding="utf-8")
        print(f"\nSalvo: {alvo.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
