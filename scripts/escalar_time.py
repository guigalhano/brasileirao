#!/usr/bin/env python3
"""
Escala o time ideal da rodada no Cartola: pontuacao esperada + otimizacao
sob orcamento e formacao.

POR QUE ISSO NAO E "media / preco"
-----------------------------------
O criterio que o repo usava premiava jogador barato de media baixa: Andrey
Fernandes (R$ 1,41, media 1,70) aparecia como segundo melhor atacante da
rodada porque 1,70/1,41 = 1,21 e um "otimo custo-beneficio". Ninguem escala
isso -- razao media/preco nao mede pontuacao, mede barateza.

O que este script faz:

  1. RECUPERA a tabela de pontuacao do Cartola dos proprios dados, em vez de
     chutar. Regressao de `pontos` contra os 20 scouts em 6.2k observacoes
     de jogadores de linha: R2 = 0.990, erro medio 0.04 ponto, e todos os
     pesos saem redondos (G=8, A=5, SG=5, DP=7, DS=1.5, ...). Se o Cartola
     mudar a tabela, isto acompanha sozinho.

  2. Estima a TAXA DE CADA SCOUT por jogador com encolhimento empirico de
     Bayes na media da posicao. A mediana e de 10 jogos por jogador --
     amostra curta demais pra confiar na media crua de quem jogou 2 partidas.

  3. AJUSTA PELO CONFRONTO, que e o ponto que a media sozinha ignora:
     - scouts ofensivos escalam pelo xG esperado do time NAQUELE jogo;
     - SG (+5, o maior premio de defensor e goleiro) vira a probabilidade
       de nao sofrer gol, P(Poisson(xG_adversario) = 0);
     - GS (-1 por gol sofrido, goleiro) vira o xG esperado do adversario;
     - defesas do goleiro escalam com a pressao ofensiva do adversario.
     Um zagueiro do Flamengo contra o Mirassol e um zagueiro do Mirassol
     contra o Flamengo nao valem a mesma coisa, e a media nao sabe disso.

  4. OTIMIZA de verdade: programacao dinamica sobre orcamento, por posicao,
     para cada uma das 7 formacoes. Nao e "pegue os melhores de cada
     posicao" -- e a melhor combinacao que cabe nas cartoletas.

Uso:
    python scripts/escalar_time.py --orcamento 120
    python scripts/escalar_time.py --orcamento 120 --formacao 4-3-3
    python scripts/escalar_time.py --orcamento 120 --incluir-duvidas
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.fixtures import load_fixtures
from lib.index_data import read_data
from lib.teams import canonical, canonical_or_none

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

# (GOL, LAT, ZAG, MEI, ATA) -- alem de 1 TEC em todas
FORMACOES = {
    "3-4-3": (1, 0, 3, 4, 3), "3-5-2": (1, 0, 3, 5, 2),
    "4-3-3": (1, 2, 2, 3, 3), "4-4-2": (1, 2, 2, 4, 2),
    "4-5-1": (1, 2, 2, 5, 1), "5-3-2": (1, 2, 3, 3, 2),
    "5-4-1": (1, 2, 3, 4, 1),
}
POSICOES = ("GOL", "LAT", "ZAG", "MEI", "ATA")

# Scouts que escalam com o poder ofensivo do time no jogo
OFENSIVOS = {"G", "A", "FD", "FF", "FT", "PS", "I", "PP"}
# Scouts tratados a parte porque dependem do adversario, nao do jogador
ESPECIAIS = {"SG", "GS", "DE", "DP"}

K_SHRINK = 5.0    # jogos "virtuais" da media posicional no encolhimento
GRAO = 0.1        # granularidade do orcamento na DP, em cartoletas


def recuperar_tabela(hist):
    """Descobre quanto vale cada scout, regredindo pontos contra os scouts."""
    linha = [r for r in hist if r["posicao"] != "TEC"]
    scouts = sorted(c[6:] for c in hist[0] if c.startswith("scout_"))
    X = np.array([[float(r[f"scout_{s}"] or 0) for s in scouts] for r in linha])
    y = np.array([float(r["pontos"] or 0) for r in linha])
    w, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ w
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    tabela = {s: round(float(p), 2) for s, p in zip(scouts, w) if abs(p) > 0.01}
    return tabela, r2, float(np.abs(y - pred).mean()), len(linha)


def medir_elasticidades(hist):
    """Quanto os scouts realmente respondem ao confronto -- medido, nao suposto.

    A primeira versao deste script assumia resposta linear (expoente 1.0): um
    goleiro que enfrenta 1.7x mais xG faria 1.7x mais defesas. Os dados dizem
    outra coisa. Com expoente 1.0 o goleiro do Remo (pior defesa da rodada)
    aparecia como o melhor da rodada, com +8.1 pontos so de defesas -- artefato
    da suposicao, nao do futebol.

    Ofensiva: agregado por time, scouts ofensivos/jogo contra gols/jogo.
    Defesa:   por goleiro, defesas/jogo contra gols sofridos/jogo.
    """
    from collections import defaultdict as _dd
    OF = ["G", "A", "FD", "FF", "FT", "PS"]

    tm = _dd(lambda: {"of": 0.0, "g": 0.0, "rod": set()})
    for r in hist:
        if r["posicao"] in ("TEC", "?"):
            continue
        t = canonical_or_none(r["clube"])
        if not t:
            continue
        tm[t]["of"] += sum(float(r[f"scout_{s}"] or 0) for s in OF)
        tm[t]["g"] += float(r["scout_G"] or 0)
        tm[t]["rod"].add(r["rodada"])
    X = [d["g"] / len(d["rod"]) for d in tm.values() if len(d["rod"]) >= 8 and d["g"] > 0]
    Y = [d["of"] / len(d["rod"]) for d in tm.values() if len(d["rod"]) >= 8 and d["g"] > 0]
    e_of, r_of = 1.0, 0.0
    if len(X) >= 8:
        e_of = float(np.polyfit(np.log(X), np.log(Y), 1)[0])
        r_of = float(np.corrcoef(np.log(X), np.log(Y))[0, 1]) ** 2

    gk = _dd(list)
    for r in hist:
        if r["posicao"] == "GOL":
            gk[r["atleta_id"]].append(r)
    A = [(np.mean([float(r["scout_GS"] or 0) for r in js]),
          np.mean([float(r["scout_DE"] or 0) for r in js]))
         for js in gk.values() if len(js) >= 6]
    A = [(g, d) for g, d in A if g > 0 and d > 0]
    e_de, r_de = 1.0, 0.0
    if len(A) >= 8:
        gs, de = np.array([a[0] for a in A]), np.array([a[1] for a in A])
        e_de = float(np.polyfit(np.log(gs), np.log(de), 1)[0])
        r_de = float(np.corrcoef(np.log(gs), np.log(de))[0, 1]) ** 2
    return {"ofensiva": e_of, "r2_ofensiva": r_of,
            "defesas": e_de, "r2_defesas": r_de}


def taxas_por_jogador(hist, tabela):
    """Taxa media de cada scout por jogo, encolhida na media da posicao."""
    por_jogador = defaultdict(list)
    for r in hist:
        if r["posicao"] == "TEC":
            continue
        por_jogador[r["atleta_id"]].append(r)

    soma_pos, n_pos = defaultdict(lambda: defaultdict(float)), defaultdict(int)
    for jogos in por_jogador.values():
        pos = jogos[0]["posicao"]
        n_pos[pos] += len(jogos)
        for r in jogos:
            for s in tabela:
                soma_pos[pos][s] += float(r[f"scout_{s}"] or 0)
    media_pos = {p: {s: soma_pos[p][s] / n_pos[p] for s in tabela} for p in n_pos}

    taxas = {}
    for aid, jogos in por_jogador.items():
        pos, n = jogos[0]["posicao"], len(jogos)
        if pos not in media_pos:
            continue
        peso = n / (n + K_SHRINK)
        t = {}
        for s in tabela:
            cru = sum(float(r[f"scout_{s}"] or 0) for r in jogos) / n
            t[s] = peso * cru + (1 - peso) * media_pos[pos][s]
        taxas[aid] = {"pos": pos, "n": n, "taxas": t}
    return taxas, media_pos


def contexto_da_rodada():
    """xG e probabilidades de cada time nesta rodada, vindos do modelo."""
    rodada, fixtures, meta = load_fixtures()
    por_time = {}
    for jogo in read_data(REPO / "index.html"):
        h, a = canonical(jogo["home"]), canonical(jogo["away"])
        xg_h, xg_a = jogo["xg"]
        p_h, p_d, p_a = jogo["model"]
        por_time[h] = {"adv": a, "casa": True, "xg_pro": xg_h, "xg_contra": xg_a,
                       "p_vit": p_h, "p_emp": p_d}
        por_time[a] = {"adv": h, "casa": False, "xg_pro": xg_a, "xg_contra": xg_h,
                       "p_vit": p_a, "p_emp": p_d}
    return rodada, meta, por_time


def pontos_esperados(taxa, pos, ctx, xg_medio):
    """Pontuacao esperada do jogador neste confronto especifico."""
    xg_pro, xg_contra = ctx["xg_pro"], ctx["xg_contra"]
    # Expoentes medidos nos dados (ver medir_elasticidades), nao 1.0: a resposta
    # dos scouts ao confronto e bem mais achatada do que proporcional.
    mult_ofensivo = (xg_pro / xg_medio) ** ELAST["ofensiva"]
    mult_defensivo = (xg_contra / xg_medio) ** ELAST["defesas"]
    p_sg = math.exp(-xg_contra)          # P(adversario nao marca)

    total = 0.0
    for s, peso in TABELA.items():
        if s == "V":
            continue                      # so tecnico pontua por vitoria
        if s in ESPECIAIS:
            continue
        r = taxa[s]
        total += peso * (r * mult_ofensivo if s in OFENSIVOS else r)

    if pos in ("GOL", "ZAG", "LAT"):
        total += TABELA.get("SG", 5.0) * p_sg
    if pos == "GOL":
        total += TABELA.get("GS", -1.0) * xg_contra
        total += TABELA.get("DE", 1.3) * taxa.get("DE", 0.0) * mult_defensivo
        total += TABELA.get("DP", 7.0) * taxa.get("DP", 0.0)
    return total


def melhor_por_posicao(cands, k, orcamento):
    """DP: melhor pontuacao usando exatamente k jogadores, por nivel de custo.

    Devolve (pontos[c], escolha[c]) indexado pelo custo em passos de GRAO.
    """
    C = int(round(orcamento / GRAO)) + 1
    NEG = -1e9
    dp = np.full((k + 1, C), NEG)
    dp[0, 0] = 0.0
    escolha = [[None] * C for _ in range(k + 1)]

    for j, (aid, nome, time, preco, pts) in enumerate(cands):
        custo = int(round(preco / GRAO))
        if custo > C - 1:
            continue
        for slot in range(k, 0, -1):
            origem = dp[slot - 1, :C - custo]
            destino = dp[slot, custo:]
            melhora = origem + pts > destino
            idx = np.nonzero(melhora & (origem > NEG / 2))[0]
            for c in idx:
                dp[slot, c + custo] = origem[c] + pts
                escolha[slot][c + custo] = (j, c)
    return dp[k], escolha, k


def reconstruir(escolha, k, custo, cands):
    saida = []
    slot, c = k, custo
    while slot > 0:
        passo = escolha[slot][c]
        if passo is None:
            return []
        j, c_ant = passo
        saida.append(cands[j])
        slot, c = slot - 1, c_ant
    return saida[::-1]


def main():
    global TABELA, ELAST
    ap = argparse.ArgumentParser()
    ap.add_argument("--orcamento", type=float, default=120.0,
                    help="cartoletas disponiveis (padrao 120)")
    ap.add_argument("--formacao", choices=sorted(FORMACOES), default=None,
                    help="fixa uma formacao; sem isso, testa todas")
    ap.add_argument("--incluir-duvidas", action="store_true",
                    help="alem de Provavel, aceita jogadores em Duvida")
    ap.add_argument("--min-jogos", type=int, default=3,
                    help="minimo de jogos na temporada (padrao 3)")
    args = ap.parse_args()

    hist = list(csv.DictReader((DATA / "cartola_historico_2026_completo.csv")
                               .open(encoding="utf-8")))
    TABELA, r2, err, n = recuperar_tabela(hist)
    print(f"Tabela de pontuacao recuperada de {n} observacoes: "
          f"R2={r2:.4f}, erro medio {err:.3f} ponto")

    ELAST = medir_elasticidades(hist)
    print(f"Elasticidades medidas: ofensiva {ELAST['ofensiva']:.2f} "
          f"(R2={ELAST['r2_ofensiva']:.2f}), defesas do goleiro "
          f"{ELAST['defesas']:.2f} (R2={ELAST['r2_defesas']:.2f})")

    taxas, _ = taxas_por_jogador(hist, TABELA)
    rodada, meta, ctx_time = contexto_da_rodada()
    xg_medio = float(np.mean([c["xg_pro"] for c in ctx_time.values()]))
    print(f"Rodada {rodada} ({meta['data_inicio']} - {meta['data_fim']}), "
          f"xG medio da rodada {xg_medio:.2f}\n")

    ok_status = {"Provável", "Provavel"}
    if args.incluir_duvidas:
        ok_status |= {"Dúvida", "Duvida"}

    mercado = list(csv.DictReader((DATA / "cartola_players_enriched.csv")
                                  .open(encoding="utf-8")))
    cands = defaultdict(list)
    tecnicos = []
    fora = defaultdict(int)
    for r in mercado:
        if r["status"] not in ok_status:
            fora["status"] += 1
            continue
        time = canonical_or_none(r["team"])
        if time is None or time not in ctx_time:
            fora["sem jogo na rodada"] += 1
            continue
        ctx = ctx_time[time]
        preco = float(r["price"])
        if r["pos"] == "TEC":
            # tecnico: 7.76 com vitoria, 3.42 sem (medido no historico 2026)
            pts = 3.42 + (7.76 - 3.42) * ctx["p_vit"]
            tecnicos.append((r["atleta_id"], r["name"], time, preco, pts))
            continue
        info = taxas.get(r["atleta_id"])
        if info is None or info["n"] < args.min_jogos:
            fora[f"menos de {args.min_jogos} jogos"] += 1
            continue
        pts = pontos_esperados(info["taxas"], r["pos"], ctx, xg_medio)
        cands[r["pos"]].append((r["atleta_id"], r["name"], time, preco, pts))

    print("Elegiveis: " + ", ".join(f"{p}={len(cands[p])}" for p in POSICOES)
          + f", TEC={len(tecnicos)}")
    print("Descartados: " + ", ".join(f"{k}={v}" for k, v in fora.items()) + "\n")

    for p in cands:
        cands[p].sort(key=lambda x: -x[4])
        cands[p] = cands[p][:60]          # poda: 60 melhores por posicao
    tecnicos.sort(key=lambda x: -x[4])

    formacoes = [args.formacao] if args.formacao else sorted(FORMACOES)
    melhor_geral = None

    for nome_f in formacoes:
        req = dict(zip(POSICOES, FORMACOES[nome_f]))
        # o tecnico mais barato viavel entra primeiro; testamos os 8 melhores
        for tec in tecnicos[:8]:
            orc = args.orcamento - tec[3]
            if orc <= 0:
                continue
            curvas = {}
            viavel = True
            for p in POSICOES:
                k = req[p]
                if k == 0:
                    continue
                if len(cands[p]) < k:
                    viavel = False
                    break
                curvas[p] = melhor_por_posicao(cands[p], k, orc)
            if not viavel:
                continue

            # combina as posicoes com outra DP sobre o orcamento
            C = int(round(orc / GRAO)) + 1
            total = np.full(C, -1e9)
            total[0] = 0.0
            trilha = [{} for _ in range(C)]
            for p in POSICOES:
                if req[p] == 0:
                    continue
                pontos_p, _, _ = curvas[p]
                novo = np.full(C, -1e9)
                nova_trilha = [{} for _ in range(C)]
                validos = np.nonzero(pontos_p > -1e8)[0]
                for c0 in np.nonzero(total > -1e8)[0]:
                    alvo = c0 + validos
                    dentro = alvo < C
                    soma = total[c0] + pontos_p[validos[dentro]]
                    for cc, sv, cp in zip(alvo[dentro], soma, validos[dentro]):
                        if sv > novo[cc]:
                            novo[cc] = sv
                            nova_trilha[cc] = {**trilha[c0], p: cp}
                total, trilha = novo, nova_trilha

            c_best = int(np.argmax(total))
            if total[c_best] < -1e8:
                continue
            pontos_total = total[c_best] + tec[4]
            if melhor_geral is None or pontos_total > melhor_geral[0]:
                escalacao = {}
                for p, cp in trilha[c_best].items():
                    _, esc, k = curvas[p]
                    escalacao[p] = reconstruir(esc, k, cp, cands[p])
                melhor_geral = (pontos_total, nome_f, tec, escalacao,
                                c_best * GRAO + tec[3])

    if melhor_geral is None:
        print("Nenhuma escalacao viavel com esse orcamento.")
        return 1

    pontos, formacao, tec, escalacao, custo = melhor_geral
    print("=" * 74)
    print(f"TIME IDEAL DA RODADA {rodada}  |  formacao {formacao}")
    print("=" * 74)
    print(f"{'POS':<5}{'JOGADOR':<24}{'TIME':<14}{'PRECO':>7}{'E[pts]':>9}")
    print("-" * 74)
    for p in POSICOES:
        for aid, nome, time, preco, pts in escalacao.get(p, []):
            adv = ctx_time[time]["adv"]
            casa = "x" if ctx_time[time]["casa"] else "@"
            print(f"{p:<5}{nome[:23]:<24}{time[:13]:<14}{preco:>7.2f}{pts:>9.2f}"
                  f"   {casa} {adv}")
    print(f"{'TEC':<5}{tec[1][:23]:<24}{tec[2][:13]:<14}{tec[3]:>7.2f}{tec[4]:>9.2f}")
    print("-" * 74)
    print(f"{'':<43}{custo:>7.2f}{pontos:>9.2f}")
    print(f"\nOrcamento {args.orcamento:.2f} | gasto {custo:.2f} | "
          f"sobra {args.orcamento - custo:.2f}")
    print(f"Pontuacao esperada: {pontos:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
