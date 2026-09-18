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
     chutar, e CONFERE contra a tabela oficial transcrita de
     cartola.globo.com/#!/entenda-mais em data/cartola_tabela_pontuacao.json.
     Filtrando so as cinco posicoes de linha, a regressao de `pontos` contra
     os scouts e exata: R2 = 1.0000, erro 0.0000, os 19 scouts batendo na
     casa decimal com a tabela oficial (G=8, A=5, SG=5, DP=7, DS=1.5, ...).
     Se o Cartola mexer na pontuacao, os dados divergem do arquivo e o script
     avisa em vez de seguir escalando com peso velho.

  2. Estima a TAXA DE CADA SCOUT por jogador com encolhimento de Bayes
     empirico na media da posicao, com forca de encolhimento MEDIDA POR
     SCOUT. Antes era K=5 para todos, como se gol e desarme fossem
     igualmente previsiveis; a autocorrelacao de rodada para rodada diz o
     contrario (DS 0.231, FS 0.292 contra G 0.090, A 0.055). Desarme e
     habito, gol e evento -- ver scripts/lib/pontuacao.py.

  3. AJUSTA PELO CONFRONTO, que e o ponto que a media sozinha ignora:
     - scouts ofensivos escalam pelo xG esperado do time NAQUELE jogo;
     - SG (+5, o maior premio de defensor e goleiro) vira a probabilidade
       de nao sofrer gol, P(Poisson(xG_adversario) = 0);
     - GS (-1 por gol sofrido, goleiro) vira o xG esperado do adversario;
     - defesas do goleiro escalam com a pressao ofensiva do adversario;
     - DESARME de zagueiro e lateral sobe contra ataque forte, com o
       coeficiente medido nos dados (ver medir_resposta_desarme).
     Um zagueiro do Flamengo contra o Mirassol e um zagueiro do Mirassol
     contra o Flamengo nao valem a mesma coisa, e a media nao sabe disso.

  4. OTIMIZA de verdade: programacao dinamica sobre orcamento, por posicao,
     para cada uma das 7 formacoes. Nao e "pegue os melhores de cada
     posicao" -- e a melhor combinacao que cabe nas cartoletas.

  5. SEGUE AS REGRAS OFICIAIS de tecnico e capitao (conferidas em
     cartola.globo.com/#!/entenda-mais em setembro/2026):

     TECNICO -- "soma de todos os seus jogadores que pontuaram dividida por
     11, acrescida de 1 ponto em caso de vitoria". Usavamos
     3,42 + 4,34 * P(vitoria), tirado da media historica; aquele 4,34
     confundia o bonus de vitoria (que e 1) com o fato de que time que vence
     tambem pontua mais. Nas 461 observacoes de 2026 a formula oficial tem
     erro MEDIANO de 0,004 ponto (R2=0,944) contra 1,010 do modelo antigo.

     CAPITAO -- multiplica por 1,5, nao por 2, e multiplica tambem a
     pontuacao NEGATIVA. O script sugere dois: o de maior E[pts] (melhor pela
     media) e o de maior desvio (melhor pra quem precisa de cauda). A
     braçadeira entra no bootstrap tambem.

QUANDO VOCE PRECISA ARRISCAR (--risco)
--------------------------------------
Maximizar pontuacao esperada e o certo pra nao perder, e o errado pra ganhar.
Quem esta atras na liga nao precisa do time com maior media -- precisa do time
com maior chance de fazer uma rodada MUITO alta, porque empatar com o pelotao
nao recupera posicao nenhuma.

--risco L troca o criterio de E[pts] para E[pts] + L * desvio, onde o desvio e
o do proprio jogador, medido nas rodadas em que ele jogou. Com L=0 nada muda.
L entre 0,3 e 0,7 ja reordena bastante sem cair no lixo.

O script mostra a distribuicao dos dois times por BOOTSTRAP: reamostra a
pontuacao real de cada jogador nas rodadas que ele jogou, soma o time, repete
20 mil vezes. Nao assume normalidade -- usa a cara real da distribuicao do
Cartola, que e torta (muita rodada perto de zero, poucas explosoes).

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
from lib.fixtures import historico_por_time_rodada, load_fixtures
from lib.index_data import read_data
from lib.pontuacao import (agrupar_por_jogador, carregar_tabela_oficial,
                           conferir_tabela, estimar_k_encolhimento, jogou,
                           medias_posicionais, recuperar_tabela,
                           scout_vale_para, scouts_do_historico,
                           taxas_encolhidas)
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
# Posicoes cujo desarme responde ao confronto (ver medir_resposta_desarme)
POSICOES_DESARME = ("ZAG", "LAT")

GRAO = 0.1        # granularidade do orcamento na DP, em cartoletas


def norm_nome(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def amostras_de_pontos(hist, scouts):
    """{atleta_id: {rodada: pontos}} das rodadas em que o jogador atuou.

    E a materia-prima do bootstrap: em vez de assumir que a pontuacao do
    jogador e normal em torno da media, reamostramos o que ele realmente fez.
    A distribuicao do Cartola e torta -- muita rodada perto de zero e poucas
    explosoes -- e e justamente a cauda direita que interessa a quem precisa
    arriscar.

    Guardamos POR RODADA, nao so a lista de valores, porque o bootstrap
    precisa saber quem pontuou junto com quem -- ver bootstrap_time.
    """
    por = defaultdict(dict)
    for r in hist:
        if r["posicao"] in POSICOES and jogou(r, scouts):
            por[r["atleta_id"]][int(r["rodada"])] = float(r["pontos"] or 0)
    return por


def bootstrap_time(grupos, n=20000, semente=42, independente=False):
    """Distribuicao do total do time, respeitando quem pontua junto com quem.

    O PONTO: pontuacoes NAO sao independentes dentro de uma partida. Quatro
    jogadores do mesmo jogo sobem e descem juntos -- se o Flamengo golear, o
    atacante, o meia e o zagueiro pontuam na mesma rodada; se travar, todos
    travam. E isso importa exatamente pra quem quer arriscar, porque EMPILHAR
    um time e em si uma estrategia de variancia.

    Metodo: agrupa os escalados por PARTIDA da proxima rodada. Para cada grupo
    sorteia uma rodada passada e soma o que aqueles jogadores REALMENTE
    fizeram naquela rodada (quem nao jogou entra com a propria media). Grupos
    diferentes sorteiam rodadas diferentes, de forma independente.

    Assim a correlacao entra sozinha, do jeito que aconteceu, sem estimar
    matriz de covariancia nenhuma -- e, por recombinar partidas distintas,
    ainda gera muito mais combinacoes do que sortear a rodada inteira (que so
    tem ~26 blocos e nao consegue enxergar cauda alguma alem do ja observado).

    `grupos` e uma lista de listas de {rodada: pontos}. Com independente=True
    cada jogador vira seu proprio grupo, que e a versao ingenua -- serve pra
    medir quanto a correlacao esta pesando.
    """
    rng = np.random.default_rng(semente)
    if independente:
        grupos = [[jogador] for grupo in grupos for jogador in grupo]

    total = np.zeros(n)
    for grupo in grupos:
        grupo = [p for p in grupo if p]
        if not grupo:
            continue
        rodadas = sorted({rod for p in grupo for rod in p})
        medias = [np.mean(list(p.values())) for p in grupo]
        totais = np.array([sum(p.get(rod, m) for p, m in zip(grupo, medias))
                           for rod in rodadas], dtype=float)
        total += rng.choice(totais, n, replace=True)
    return total


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


def medir_resposta_desarme(hist, scouts):
    """Quanto o DESARME de zagueiro e lateral responde a forca do ataque adversario.

    O desarme e o scout que mais pesa na pontuacao de defensor (1,5 ponto cada,
    1,31 por jogo de lateral e 1,04 de zagueiro -- mais do que o SG rende na
    media), e ate agora entrava aqui como taxa fixa, alheia ao confronto.

    A leitura ingenua desses dados engana, e vale registrar porque: a correlacao
    CRUA entre desarmes do time por jogo e gols sofridos por jogo e NEGATIVA
    (-0.37 entre os 20 times). Quem sofre mais gol desarma menos. Isso nao e o
    efeito do confronto, e confusao com a qualidade do time: time bom desarma
    mais E sofre menos (corr(DS, gols marcados) = +0.39). Quem e atropelado nao
    desarma, corre atras.

    Com efeito fixo de jogador -- comparando o MESMO jogador contra adversarios
    diferentes, que e a pergunta certa -- o sinal inverte e fica positivo:

        ZAG+LAT  +0.311 desarme por gol/jogo de ataque adversario  (t=+2.39)
        MEI      +0.149                                            (t=+1.16)
        ATA      -0.005                                            (t=-0.05)

    So ZAG/LAT tem efeito significativo, e so eles recebem o ajuste. E um efeito
    modesto e proposital: entre o ataque mais fraco e o mais forte da liga da
    cerca de 0,3 desarme, uns 0,4 ponto. Ajuste ADITIVO, na escala em que foi
    medido -- multiplicativo estouraria com pouco dado, que foi o defeito que
    medir_elasticidades ja teve que corrigir com o goleiro do Remo.

    Devolve (coeficiente, t, n). Coeficiente 0.0 quando nao da pra medir.
    """
    mapa = historico_por_time_rodada()
    ataque_medio = defaultdict(list)
    for (time, _), j in mapa.items():
        ataque_medio[time].append(j["gols_pro"])
    forca_ataque = {t: float(np.mean(v)) for t, v in ataque_medio.items()}

    jogadores, linhas = {}, []
    for r in hist:
        if r["posicao"] not in POSICOES_DESARME or not jogou(r, scouts):
            continue
        time = canonical_or_none(r["clube"])
        j = mapa.get((time, int(r["rodada"]))) if time else None
        if not j or j["adv"] not in forca_ataque:
            continue
        aid = r["atleta_id"]
        jogadores.setdefault(aid, len(jogadores))
        linhas.append((jogadores[aid], forca_ataque[j["adv"]],
                       float(r["scout_DS"] or 0)))

    # Regressao com uma dummy por jogador: o coeficiente do ataque adversario
    # sai limpo da diferenca entre jogos do mesmo jogador, sem carregar o
    # quanto cada um desarma em geral.
    if len(linhas) < 200 or len(jogadores) < 20:
        return 0.0, 0.0, len(linhas)
    X = np.zeros((len(linhas), len(jogadores) + 1))
    y = np.empty(len(linhas))
    for i, (idx, ataque, ds) in enumerate(linhas):
        X[i, idx] = 1.0
        X[i, -1] = ataque
        y[i] = ds
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    residuo = y - X @ beta
    graus = len(linhas) - np.linalg.matrix_rank(X)
    if graus <= 0:
        return 0.0, 0.0, len(linhas)
    var = (residuo ** 2).sum() / graus * np.linalg.pinv(X.T @ X)
    erro = float(np.sqrt(np.diag(var))[-1])
    coef = float(beta[-1])
    t = coef / erro if erro > 0 else 0.0
    # Coeficiente sem significancia entra como zero: melhor nao ajustar do que
    # ajustar por ruido -- mesmo criterio que ja tirou outros sinais do projeto.
    return (coef if abs(t) > 2 else 0.0), t, len(linhas)


def contexto_da_rodada():
    """xG e probabilidades de cada time nesta rodada, vindos do modelo.

    Times cujo jogo NAO pontua no Cartola ficam de fora. Partida antecipada
    para antes do fechamento do mercado acontece de verdade (e continua no
    modelo de partidas do site), mas nao rende ponto nenhum -- escalar alguem
    dela e garantir zero. Na rodada 27 foi Coritiba x Athletico, antecipado
    pra sexta; o modelo estava disposto a recomendar esses jogadores.
    """
    rodada, fixtures, meta = load_fixtures()
    nao_valem = {t for j in fixtures if not j.get("vale_cartola", True)
                 for t in (j["home"], j["away"])}
    por_time = {}
    for jogo in read_data(REPO / "index.html"):
        h, a = canonical(jogo["home"]), canonical(jogo["away"])
        if h in nao_valem or a in nao_valem:
            continue
        xg_h, xg_a = jogo["xg"]
        p_h, p_d, p_a = jogo["model"]
        por_time[h] = {"adv": a, "casa": True, "xg_pro": xg_h, "xg_contra": xg_a,
                       "p_vit": p_h, "p_emp": p_d}
        por_time[a] = {"adv": h, "casa": False, "xg_pro": xg_a, "xg_contra": xg_h,
                       "p_vit": p_a, "p_emp": p_d}
    return rodada, meta, por_time, sorted(nao_valem)


def pontos_esperados(taxa, pos, ctx, xg_medio):
    """Pontuacao esperada do jogador neste confronto especifico.

    Devolve (total, parcelas) -- parcelas separa quanto vem de desarme, de SG e
    do resto, pra tela poder mostrar de onde sai a nota em vez de so um numero.
    """
    xg_pro, xg_contra = ctx["xg_pro"], ctx["xg_contra"]
    # Expoentes medidos nos dados (ver medir_elasticidades), nao 1.0: a resposta
    # dos scouts ao confronto e bem mais achatada do que proporcional.
    mult_ofensivo = (xg_pro / xg_medio) ** ELAST["ofensiva"]
    mult_defensivo = (xg_contra / xg_medio) ** ELAST["defesas"]
    p_sg = math.exp(-xg_contra)          # P(adversario nao marca)

    # Desarme responde ao confronto so em ZAG/LAT, e de forma aditiva na escala
    # em que foi medido (ver medir_resposta_desarme). xg_contra e o gol esperado
    # do adversario neste jogo; a medicao usou gols/jogo do adversario na
    # temporada -- mesma escala, entao o coeficiente transfere.
    taxa_ds = taxa.get("DS", 0.0)
    if pos in POSICOES_DESARME and DS_COEF:
        taxa_ds = max(0.0, taxa_ds + DS_COEF * (xg_contra - xg_medio))

    total, pts_ds = 0.0, 0.0
    for s, peso in TABELA.items():
        if s in ESPECIAIS or not scout_vale_para(s, pos):
            continue
        if s == "DS":
            pts_ds = peso * taxa_ds
            total += pts_ds
            continue
        total += peso * (taxa[s] * mult_ofensivo if s in OFENSIVOS else taxa[s])

    pts_sg = 0.0
    if scout_vale_para("SG", pos):
        pts_sg = TABELA.get("SG", 5.0) * p_sg
        total += pts_sg
    if pos == "GOL":
        total += TABELA.get("GS", -1.0) * xg_contra
        total += TABELA.get("DE", 1.3) * taxa.get("DE", 0.0) * mult_defensivo
        total += TABELA.get("DP", 7.0) * taxa.get("DP", 0.0)
    return total, {"DS": pts_ds, "SG": pts_sg, "taxa_ds": taxa_ds}


def melhor_por_posicao(cands, k, orcamento):
    """DP: melhor pontuacao usando exatamente k jogadores, por nivel de custo.

    Devolve (pontos[c], escolha[c]) indexado pelo custo em passos de GRAO.
    """
    C = int(round(orcamento / GRAO)) + 1
    NEG = -1e9
    dp = np.full((k + 1, C), NEG)
    dp[0, 0] = 0.0
    escolha = [[None] * C for _ in range(k + 1)]

    for j, cand in enumerate(cands):
        preco, pts = cand[3], cand[4]
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
    global TABELA, ELAST, DS_COEF
    ap = argparse.ArgumentParser()
    ap.add_argument("--orcamento", type=float, default=120.0,
                    help="cartoletas disponiveis (padrao 120)")
    ap.add_argument("--formacao", choices=sorted(FORMACOES), default=None,
                    help="fixa uma formacao; sem isso, testa todas")
    ap.add_argument("--incluir-duvidas", action="store_true",
                    help="alem de Provavel, aceita jogadores em Duvida")
    ap.add_argument("--risco", type=float, default=0.0,
                    help="peso do desvio no criterio (0 = so media; 0.3-0.7 = "
                         "busca upside). Ver o cabecalho do arquivo.")
    ap.add_argument("--evitar", default="",
                    help="nomes a excluir, separados por virgula -- pra fugir "
                         "dos mais escalados e diferenciar de verdade")
    ap.add_argument("--min-jogos", type=int, default=3,
                    help="minimo de jogos na temporada (padrao 3)")
    args = ap.parse_args()

    hist = list(csv.DictReader((DATA / "cartola_historico_2026_completo.csv")
                               .open(encoding="utf-8")))
    scouts = scouts_do_historico(hist)

    TABELA, diag = recuperar_tabela(hist)
    print(f"Tabela de pontuacao recuperada de {diag['n']} observacoes: "
          f"R2={diag['r2']:.4f}, erro medio {diag['erro_medio']:.4f} ponto")

    # Confere contra a tabela oficial do cartola.globo.com/#!/entenda-mais.
    # Divergencia aqui significa que o Cartola mexeu na pontuacao -- o script
    # segue (os dados mandam), mas nao deixa isso passar em silencio.
    oficial, doc_oficial = carregar_tabela_oficial()
    problemas = conferir_tabela(TABELA, oficial)
    if problemas:
        print("\n[ATENCAO] a pontuacao nos dados nao bate com "
              f"data/cartola_tabela_pontuacao.json (conferida em "
              f"{doc_oficial['_conferido_em']}):")
        for p in problemas:
            print(f"    - {p}")
        print("    Confira " + doc_oficial["_fonte"] + " e atualize o arquivo.\n")
    else:
        print(f"Confere com a tabela oficial de {doc_oficial['_conferido_em']} "
              f"({len(oficial)} scouts): DS={TABELA.get('DS')}, "
              f"DE={TABELA.get('DE')}, G={TABELA.get('G')}, SG={TABELA.get('SG')}")

    ELAST = medir_elasticidades(hist)
    print(f"Elasticidades medidas: ofensiva {ELAST['ofensiva']:.2f} "
          f"(R2={ELAST['r2_ofensiva']:.2f}), defesas do goleiro "
          f"{ELAST['defesas']:.2f} (R2={ELAST['r2_defesas']:.2f})")

    DS_COEF, ds_t, ds_n = medir_resposta_desarme(hist, scouts)
    if DS_COEF:
        print(f"Desarme de ZAG/LAT responde ao confronto: {DS_COEF:+.3f} desarme "
              f"por gol/jogo do ataque adversario (t={ds_t:+.2f}, n={ds_n})")
    else:
        print(f"Desarme sem resposta significativa ao confronto (t={ds_t:+.2f}, "
              f"n={ds_n}) -- entra como taxa fixa")

    # Encolhimento por scout: gol de zagueiro nao se repete, desarme sim.
    por_jogador = agrupar_por_jogador(hist, scouts)
    media_pos = medias_posicionais(por_jogador, scouts)
    K = estimar_k_encolhimento(por_jogador, scouts)
    taxas = taxas_encolhidas(por_jogador, scouts, K, media_pos)
    amostra_k = ", ".join(
        f"{s} {K[(s, 'ZAG')]:.0f}" for s in ("DS", "FS", "SG", "G", "A")
        if (s, "ZAG") in K)
    print(f"Encolhimento por scout (Bayes empirico, K de zagueiro): {amostra_k}")

    amostras = amostras_de_pontos(hist, scouts)
    evitar = {norm_nome(x) for x in args.evitar.split(",") if x.strip()}
    if evitar:
        print(f"Evitando {len(evitar)} nome(s) a pedido (diferenciacao)")

    rodada, meta, ctx_time, sem_pontuar = contexto_da_rodada()
    if sem_pontuar:
        print(f"Fora da rodada do Cartola (jogo nao pontua): "
              f"{', '.join(sem_pontuar)}")
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
            # Pontuado no segundo passo: a regra oficial depende dos jogadores
            # do clube, que ainda nao foram todos processados aqui.
            tecnicos.append([r["atleta_id"], r["name"], time, preco, None])
            continue
        info = taxas.get(r["atleta_id"])
        if info is None or info["n"] < args.min_jogos:
            fora[f"menos de {args.min_jogos} jogos"] += 1
            continue
        if norm_nome(r["name"]) in evitar:
            fora["evitados"] += 1
            continue
        pts, parcelas = pontos_esperados(info["taxas"], r["pos"], ctx, xg_medio)
        parcelas["ds_observado"] = info["cru"].get("DS", 0.0)
        amostra = amostras.get(r["atleta_id"], {})
        desvio = float(np.std(list(amostra.values()))) if len(amostra) >= 3 else 0.0
        parcelas["desvio"] = desvio
        parcelas["amostra"] = amostra
        # O criterio que a otimizacao maximiza. Com --risco 0 e a propria
        # pontuacao esperada, como sempre foi.
        criterio = pts + args.risco * desvio
        cands[r["pos"]].append((r["atleta_id"], r["name"], time, preco, criterio,
                                parcelas, pts))

    # TECNICO PELA REGRA OFICIAL (cartola.globo.com, secao 2.6/3.1):
    # "a pontuacao do tecnico e a soma de todos os seus jogadores que pontuaram
    # dividida por 11, acrescida de 1 ponto em caso de vitoria".
    #
    # Usavamos 3.42 + 4.34 * P(vitoria), tirado da media historica. O numero
    # 4.34 conflundia duas coisas: o bonus de vitoria (que e 1, nao 4.34) e o
    # fato de que time que vence tambem pontua mais no total. Conferido nas 461
    # observacoes de 2026, a formula oficial acerta com erro MEDIANO de 0.004
    # ponto (R2=0.944) contra 1.010 do modelo antigo.
    #
    # E[soma do clube] aproximado pelos 11 maiores E[pts] elegiveis do clube --
    # os melhores tendem a ser os titulares. E aproximacao, e a unica parte
    # desta conta que nao vem direto da regra.
    por_clube = defaultdict(list)
    for p in POSICOES:
        for c in cands[p]:
            por_clube[c[2]].append(c[6])
    for t in tecnicos:
        time_tec = t[2]
        melhores = sorted(por_clube.get(time_tec, []), reverse=True)[:11]
        soma = sum(melhores)
        t[4] = soma / 11.0 + ctx_time[time_tec]["p_vit"]
    tecnicos = [tuple(t) for t in tecnicos if t[4] is not None]

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
    largura = 100
    print("=" * largura)
    print(f"TIME IDEAL DA RODADA {rodada}  |  formacao {formacao}")
    print("=" * largura)
    print(f"{'POS':<5}{'JOGADOR':<24}{'TIME':<14}{'PRECO':>7}{'E[pts]':>9}"
          f"{'desvio':>8}{'DS/jogo':>9}{'pts DS':>8}  CONFRONTO")
    print("-" * largura)
    total_ds = 0.0
    grupos = {}
    soma_epts = 0.0
    candidatos_cap = []   # o tecnico nao pode ser capitao (regra 2.7)
    for p in POSICOES:
        for aid, nome, time, preco, criterio, parc, pts in escalacao.get(p, []):
            adv = ctx_time[time]["adv"]
            casa = "x" if ctx_time[time]["casa"] else "@"
            total_ds += parc["DS"]
            chave = frozenset((time, ctx_time[time]["adv"]))
            grupos.setdefault(chave, []).append(parc.get("amostra", {}))
            candidatos_cap.append((nome, pts, parc["desvio"], chave,
                                   parc.get("amostra", {})))
            soma_epts += pts
            print(f"{p:<5}{nome[:23]:<24}{time[:13]:<14}{preco:>7.2f}{pts:>9.2f}"
                  f"{parc['desvio']:>8.2f}{parc['ds_observado']:>9.2f}"
                  f"{parc['DS']:>8.2f}  {casa} {adv}")
    print(f"{'TEC':<5}{tec[1][:23]:<24}{tec[2][:13]:<14}{tec[3]:>7.2f}{tec[4]:>9.2f}")
    grupos.setdefault(frozenset((tec[2], ctx_time[tec[2]]["adv"])), []).append(
        amostras.get(tec[0], {}))
    soma_epts += tec[4]
    print("-" * largura)
    print(f"{'':<43}{custo:>7.2f}{pontos:>9.2f}{'':>9}{total_ds:>8.2f}")
    print(f"\nOrcamento {args.orcamento:.2f} | gasto {custo:.2f} | "
          f"sobra {args.orcamento - custo:.2f}")
    # CAPITAO (regra 2.7): pontuacao multiplicada por 1,5 -- inclusive a
    # negativa. Some 0,5 x a pontuacao dele ao total, nao 1,0: a conta de
    # "dobra" que fizemos na rodada 27 estava errada.
    #
    # Por expectativa, capitao e quem tem o maior E[pts]. Por upside, e quem
    # tem o maior desvio -- a braçadeira amplifica a cauda nos dois sentidos,
    # entao os dois candidatos aparecem.
    if candidatos_cap:
        por_media = max(candidatos_cap, key=lambda c: c[1])
        por_upside = max(candidatos_cap, key=lambda c: c[2])
        print()
        print("CAPITAO (x1,5 -- some metade da pontuacao dele de novo)")
        print(f"  por expectativa: {por_media[0]:<22} +{0.5 * por_media[1]:.2f} "
              f"(E[pts] {por_media[1]:.2f})")
        if por_upside[0] != por_media[0]:
            print(f"  por upside:      {por_upside[0]:<22} +{0.5 * por_upside[1]:.2f} "
                  f"(desvio {por_upside[2]:.2f}, o maior do time)")
        soma_epts += 0.5 * por_media[1]
        # A braçadeira entra no bootstrap tambem: multiplica as pontuacoes
        # reais do capitao por 1,5, inclusive as negativas. Sem isso a
        # distribuicao subestima as duas caudas.
        cap_chave, cap_amostra = por_media[3], por_media[4]
        if cap_amostra and cap_chave in grupos:
            grupo = grupos[cap_chave]
            for i, a in enumerate(grupo):
                if a is cap_amostra:
                    grupo[i] = {rod: v * 1.5 for rod, v in a.items()}
                    break

    print(f"Pontuacao esperada: {soma_epts:.2f} "
          f"({total_ds:.2f} vem de desarme, {100 * total_ds / soma_epts:.0f}%)")
    if args.risco:
        print(f"Criterio otimizado: E[pts] + {args.risco:g} x desvio "
              f"(= {pontos:.2f}); a coluna E[pts] acima e so a media.")

    # Distribuicao do total, por bootstrap das rodadas que cada um jogou.
    limpos = {k: [a for a in v if len(a) >= 3] for k, v in grupos.items()}
    limpos = {k: v for k, v in limpos.items() if v}
    n_jog = sum(len(v) for v in limpos.values())
    if n_jog >= 8:
        dist = bootstrap_time(list(limpos.values()))
        indep = bootstrap_time(list(limpos.values()), independente=True)
        faltam = sum(len(v) for v in grupos.values()) - n_jog
        amostra_time = [a for v in limpos.values() for a in v]
        print()
        print(f"DISTRIBUICAO ({n_jog} jogadores em {len(limpos)} partidas"
              + (f", {faltam} sem amostra suficiente" if faltam else "") + ")")
        p10, p50, p90 = np.percentile(dist, [10, 50, 90])
        print(f"  mediana {p50:.0f} | 10% pior {p10:.0f} | 10% melhor {p90:.0f} "
              f"| desvio {dist.std():.1f}")
        for alvo in (80, 100, 120):
            print(f"  P(fazer mais de {alvo} pontos) = {100 * (dist > alvo).mean():.1f}%"
                  f"   (ignorando a correlacao daria {100 * (indep > alvo).mean():.1f}%)")
    print("DS/jogo = desarmes por jogo observados na temporada (sem encolher); "
          "pts DS = quanto\ndisso entra na pontuacao esperada, ja encolhido e "
          "ajustado ao confronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
