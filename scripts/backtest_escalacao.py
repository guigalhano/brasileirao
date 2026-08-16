#!/usr/bin/env python3
"""
Backtest do criterio de escalacao: o modelo de pontuacao esperada realmente
escolhe times melhores que os criterios simples? E o encolhimento por scout
(que e o que faz o desarme pesar) melhora ou piora?

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
  - taxas, medias e o K de encolhimento vem so das rodadas < R (sem vazamento;
    o K e reestimado do zero a cada rodada);
  - escolhe-se o XI por cada criterio, respeitando 4-3-3;
  - soma-se a pontuacao REAL da rodada R.

DUAS METRICAS, DE PROPOSITO
---------------------------
1. Pontos do XI escolhido. E o que interessa na pratica, mas e barulhento:
   11 jogadores, ~14 rodadas, desvio de 15 a 19 pontos por rodada. So detecta
   diferenca grande.
2. Correlacao entre o criterio e a pontuacao real, entre todos os candidatos
   daquela rodada. Usa centenas de jogadores por rodada em vez de 11, entao
   enxerga diferenca que a primeira nao alcanca, e permite teste pareado
   rodada a rodada.

Foi a segunda metrica que mostrou o ganho do encolhimento por scout em
zagueiro e lateral (t=+2.9), invisivel na primeira.

O ajuste de confronto nao entra aqui: as duas variantes de E[pts] usam so as
taxas historicas. E de proposito -- isola o efeito do encolhimento, que e o
que esta em teste.

Uso:
    python scripts/backtest_escalacao.py
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.pontuacao import (agrupar_por_jogador, estimar_k_encolhimento,
                           medias_posicionais, recuperar_tabela,
                           scout_vale_para, scouts_do_historico)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

FORMACAO = {"GOL": 1, "LAT": 2, "ZAG": 2, "MEI": 3, "ATA": 3}
MIN_JOGOS = 3
K_UNIFORME = 5.0          # o que o script usava antes, para todo scout
PRIMEIRA_RODADA_TESTE = 8

CRITERIOS = {
    "media": "media historica",
    "k5": f"E[pts], encolhimento K={K_UNIFORME:.0f} para todo scout",
    "eb": "E[pts], encolhimento por scout (Bayes empirico)",
    "ds": "so desarme (1,5 x DS/jogo)",
}
GRUPOS = [("TODOS", ("GOL", "LAT", "ZAG", "MEI", "ATA")),
          ("ZAG+LAT", ("ZAG", "LAT")), ("MEI", ("MEI",)), ("ATA", ("ATA",))]


def esperado(jogos, pos, tabela, media_pos, k_de):
    """E[pts] historico: soma de taxa encolhida x peso do scout."""
    n = len(jogos)
    total = 0.0
    for s, peso in tabela.items():
        if not scout_vale_para(s, pos):
            continue
        cru = sum(float(r[f"scout_{s}"] or 0) for r in jogos) / n
        w = n / (n + k_de(s, pos))
        total += peso * (w * cru + (1 - w) * media_pos[pos][s])
    return total


def main():
    hist = list(csv.DictReader((DATA / "cartola_historico_2026_completo.csv")
                               .open(encoding="utf-8")))
    scouts = scouts_do_historico(hist)
    tabela, diag = recuperar_tabela(hist)
    for r in hist:
        r["rodada"] = int(r["rodada"])
        r["pontos"] = float(r["pontos"] or 0)

    rodadas = sorted({r["rodada"] for r in hist})
    teste = [r for r in rodadas if r >= PRIMEIRA_RODADA_TESTE]
    print(f"Tabela recuperada: R2={diag['r2']:.4f} em {diag['n']} observacoes")
    print(f"Rodadas no historico: {rodadas[0]}-{rodadas[-1]}")
    print(f"Testando rodadas {teste[0]}-{teste[-1]} ({len(teste)} rodadas)\n")

    pontos_xi = defaultdict(list)
    correl = defaultdict(lambda: defaultdict(list))

    for R in teste:
        passado = [r for r in hist if r["rodada"] < R]
        atual = {r["atleta_id"]: r for r in hist if r["rodada"] == R}
        if not atual:
            continue

        por_jogador = agrupar_por_jogador(passado, scouts)
        media_pos = medias_posicionais(por_jogador, scouts)
        K = estimar_k_encolhimento(por_jogador, scouts)

        cands = defaultdict(list)
        for aid, jogos in por_jogador.items():
            pos = jogos[0]["posicao"]
            if pos not in FORMACAO or len(jogos) < MIN_JOGOS or aid not in atual:
                continue
            n = len(jogos)
            cands[pos].append({
                "pos": pos,
                "real": atual[aid]["pontos"],
                "media": sum(r["pontos"] for r in jogos) / n,
                "k5": esperado(jogos, pos, tabela, media_pos,
                               lambda s, p: K_UNIFORME),
                "eb": esperado(jogos, pos, tabela, media_pos,
                               lambda s, p: K.get((s, p), K_UNIFORME)),
                "ds": tabela.get("DS", 1.5) * sum(
                    float(r["scout_DS"] or 0) for r in jogos) / n,
            })

        if any(len(cands[p]) < k for p, k in FORMACAO.items()):
            continue

        for crit in CRITERIOS:
            total = 0.0
            for p, k in FORMACAO.items():
                melhores = sorted(cands[p], key=lambda x: -x[crit])[:k]
                total += sum(x["real"] for x in melhores)
            pontos_xi[crit].append(total)

        todos = [x for p in cands for x in cands[p]]
        for nome, poss in GRUPOS:
            sub = [x for x in todos if x["pos"] in poss]
            if len(sub) < 30:
                continue
            real = [x["real"] for x in sub]
            for crit in CRITERIOS:
                vals = [x[crit] for x in sub]
                if np.std(vals) > 0 and np.std(real) > 0:
                    correl[nome][crit].append(float(np.corrcoef(vals, real)[0, 1]))

    n_rod = len(pontos_xi["media"])
    print("=" * 78)
    print(f"1) XI ideal por criterio -- pontos REAIS na rodada seguinte ({n_rod} rodadas)")
    print("=" * 78)
    print(f"{'CRITERIO':<46}{'pts/rodada':>14}{'desvio':>12}")
    for crit in sorted(CRITERIOS, key=lambda c: -np.mean(pontos_xi[c])):
        v = np.array(pontos_xi[crit])
        print(f"{CRITERIOS[crit]:<46}{v.mean():>14.2f}{v.std():>12.2f}")

    print("\n" + "=" * 78)
    print("2) Correlacao do criterio com a pontuacao real da rodada seguinte")
    print("=" * 78)
    print(f"{'CRITERIO':<46}" + "".join(f"{g:>10}" for g, _ in GRUPOS))
    for crit in CRITERIOS:
        linha = "".join(
            f"{np.mean(correl[g][crit]):>10.4f}" if correl[g][crit] else f"{'-':>10}"
            for g, _ in GRUPOS)
        print(f"{CRITERIOS[crit]:<46}{linha}")

    print("\n" + "=" * 78)
    print("3) Encolhimento por scout vs K uniforme -- teste pareado por rodada")
    print("=" * 78)
    print(f"{'GRUPO':<12}{'dif. media':>12}{'t':>8}{'significativo':>16}")
    for grupo, _ in GRUPOS:
        if not correl[grupo]["eb"]:
            continue
        d = np.array(correl[grupo]["eb"]) - np.array(correl[grupo]["k5"])
        t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if d.std(ddof=1) > 0 else 0.0
        marca = "sim" if abs(t) > 2.16 else "nao"
        print(f"{grupo:<12}{d.mean():>12.4f}{t:>8.2f}{marca:>16}")
    print("\nLeitura: o ganho aparece em ZAG+LAT, que e onde o desarme domina a")
    print("pontuacao -- encolher gol e assistencia de defensor para a media da")
    print("posicao deixa o desarme, que se repete, decidir o ranking. Nas outras")
    print("posicoes a diferenca nao passa do ruido, nos dois sentidos.")

    print("\n" + "=" * 78)
    rng = np.random.default_rng(42)
    for a, b in (("eb", "media"), ("k5", "media"), ("eb", "k5")):
        dif = np.array(pontos_xi[a]) - np.array(pontos_xi[b])
        amostras = np.array([rng.choice(dif, len(dif), replace=True).mean()
                             for _ in range(8000)])
        lo, hi = np.percentile(amostras, [2.5, 97.5])
        print(f"{a:>6} - {b:<6}: {dif.mean():+6.2f} pts/rodada  "
              f"IC95% bootstrap [{lo:+.2f}, {hi:+.2f}]  "
              f"{(amostras > 0).mean():.0%} das reamostragens a favor")
    print("\nOs dois E[pts] ganham da media no XI, mas com IC largo: 14 rodadas de")
    print("11 jogadores nao bastam pra separar as duas variantes por essa metrica.")
    print("A correlacao acima e o teste com poder pra isso.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
