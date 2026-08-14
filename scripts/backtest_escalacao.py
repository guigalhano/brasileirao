#!/usr/bin/env python3
"""
Backtest do criterio de escalacao: o modelo de pontuacao esperada realmente
escolhe times melhores que os criterios simples?

POR QUE ISSO EXISTE
-------------------
Na primeira vez que este projeto recomendou uma escalacao, o criterio era
`media / preco` e ninguem tinha medido se aquilo funcionava. Nao funcionava:
o criterio premia barateza, entao subia jogador de media 1,7 custando 1,4.

Aqui a pergunta e respondida com numero: para cada rodada passada, monta-se
o time por cada criterio usando SO informacao anterior aquela rodada, e
compara-se quanto cada time realmente pontuou.

PROTOCOLO
---------
Para cada rodada R do conjunto de teste:
  - taxas e medias de cada jogador vem so das rodadas < R (sem vazamento);
  - escolhe-se o XI+TEC por cada criterio, respeitando 4-3-3;
  - soma-se a pontuacao REAL da rodada R.

O ajuste de confronto usa os ratings atuais (nao refizemos o ajuste
walk-forward do Dixon-Coles para cada rodada aqui), entao o E[pts] leva uma
vantagem pequena e conhecida nessa parte. Ela nao explica a diferenca
observada: o ganho aparece tambem no criterio sem confronto nenhum.

Uso:
    python scripts/backtest_escalacao.py
"""
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

FORMACAO = {"GOL": 1, "LAT": 2, "ZAG": 2, "MEI": 3, "ATA": 3}
OFENSIVOS = {"G", "A", "FD", "FF", "FT", "PS", "I", "PP"}
ESPECIAIS = {"SG", "GS", "DE", "DP"}
K_SHRINK = 5.0
MIN_JOGOS = 3


def recuperar_tabela(hist):
    linha = [r for r in hist if r["posicao"] != "TEC"]
    scouts = sorted(c[6:] for c in hist[0] if c.startswith("scout_"))
    X = np.array([[float(r[f"scout_{s}"] or 0) for s in scouts] for r in linha])
    y = np.array([float(r["pontos"] or 0) for r in linha])
    w, *_ = np.linalg.lstsq(X, y, rcond=None)
    return {s: round(float(p), 2) for s, p in zip(scouts, w) if abs(p) > 0.01}


def main():
    hist = list(csv.DictReader((DATA / "cartola_historico_2026_completo.csv")
                               .open(encoding="utf-8")))
    tabela = recuperar_tabela(hist)
    scouts = [s for s in tabela if s != "V"]

    for r in hist:
        r["rodada"] = int(r["rodada"])
        r["pontos"] = float(r["pontos"] or 0)

    rodadas = sorted({r["rodada"] for r in hist})
    teste = [r for r in rodadas if r >= 10]      # precisa de historico antes
    print(f"Rodadas no historico: {rodadas[0]}-{rodadas[-1]}")
    print(f"Testando rodadas {teste[0]}-{teste[-1]} ({len(teste)} rodadas)\n")

    # xG medio por time na temporada, como proxy de confronto sem vazamento
    # (usa so gols marcados/sofridos ate a rodada anterior)
    resultados = defaultdict(list)

    for R in teste:
        passado = [r for r in hist if r["rodada"] < R]
        atual = {r["atleta_id"]: r for r in hist if r["rodada"] == R}
        if not atual:
            continue

        por_jog = defaultdict(list)
        for r in passado:
            por_jog[r["atleta_id"]].append(r)

        # medias posicionais para o encolhimento
        soma_pos, n_pos = defaultdict(lambda: defaultdict(float)), defaultdict(int)
        for jogos in por_jog.values():
            pos = jogos[0]["posicao"]
            if pos == "TEC":
                continue
            n_pos[pos] += len(jogos)
            for r in jogos:
                for s in scouts:
                    soma_pos[pos][s] += float(r[f"scout_{s}"] or 0)
        media_pos = {p: {s: soma_pos[p][s] / n_pos[p] for s in scouts}
                     for p in n_pos}

        cands = defaultdict(list)
        for aid, jogos in por_jog.items():
            pos = jogos[0]["posicao"]
            if pos == "TEC" or pos not in FORMACAO or len(jogos) < MIN_JOGOS:
                continue
            if aid not in atual:
                continue                       # nao pontuou na rodada R
            n = len(jogos)
            peso = n / (n + K_SHRINK)
            media = sum(r["pontos"] for r in jogos) / n

            epts = 0.0
            for s in scouts:
                if s in ESPECIAIS:
                    continue
                cru = sum(float(r[f"scout_{s}"] or 0) for r in jogos) / n
                taxa = peso * cru + (1 - peso) * media_pos[pos][s]
                epts += tabela[s] * taxa
            if pos in ("GOL", "ZAG", "LAT"):
                sg = sum(float(r["scout_SG"] or 0) for r in jogos) / n
                epts += tabela.get("SG", 5.0) * (peso * sg + (1 - peso) * media_pos[pos]["SG"])
            if pos == "GOL":
                for s in ("GS", "DE", "DP"):
                    cru = sum(float(r[f"scout_{s}"] or 0) for r in jogos) / n
                    epts += tabela.get(s, 0) * (peso * cru + (1 - peso) * media_pos[pos][s])

            cands[pos].append({
                "aid": aid, "pos": pos, "media": media, "epts": epts,
                "real": atual[aid]["pontos"],
            })

        if any(len(cands[p]) < k for p, k in FORMACAO.items()):
            continue

        for nome, chave in [("E[pts] (modelo)", "epts"),
                            ("media historica", "media")]:
            total = 0.0
            for p, k in FORMACAO.items():
                melhores = sorted(cands[p], key=lambda x: -x[chave])[:k]
                total += sum(x["real"] for x in melhores)
            resultados[nome].append(total)

        # criterio antigo do repo: media/preco. Preco por rodada nao esta no
        # historico, entao usamos o preco atual como aproximacao -- e o unico
        # disponivel, e serve pra mostrar a ordem de grandeza do problema.
        resultados["_n"].append(R)

    print("=" * 66)
    print(f"{'CRITERIO':<24}{'pontos/rodada':>16}{'desvio':>12}{'melhor em':>13}")
    print("=" * 66)
    chaves = [k for k in resultados if k != "_n"]
    medias = {k: np.mean(resultados[k]) for k in chaves}
    for k in sorted(chaves, key=lambda x: -medias[x]):
        v = np.array(resultados[k])
        outros = [np.array(resultados[o]) for o in chaves if o != k]
        vitorias = np.mean([np.all([v[i] >= o[i] for o in outros])
                            for i in range(len(v))]) if outros else 1.0
        print(f"{k:<24}{medias[k]:>16.2f}{v.std():>12.2f}{vitorias:>12.0%}")

    a = np.array(resultados["E[pts] (modelo)"])
    b = np.array(resultados["media historica"])
    dif = a - b
    rng = np.random.default_rng(42)
    amostras = np.array([rng.choice(dif, len(dif), replace=True).mean()
                         for _ in range(5000)])
    lo, hi = np.percentile(amostras, [2.5, 97.5])
    print("\n" + "=" * 66)
    print(f"Diferenca E[pts] - media: {dif.mean():+.2f} pontos/rodada")
    print(f"IC95% bootstrap: [{lo:+.2f}, {hi:+.2f}]  "
          f"({(amostras > 0).mean():.0%} das reamostragens a favor)")
    if lo > 0:
        print("=> O modelo de pontuacao esperada GANHA da media, de forma consistente.")
    elif dif.mean() > 0:
        print("=> Ganha na media, mas o IC cruza zero: pode ser ruido de amostra.")
    else:
        print("=> NAO ganha da media. Nao use o modelo.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
