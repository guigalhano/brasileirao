"""
Pontuacao do Cartola -- fonte unica de verdade.

POR QUE ISSO EXISTE
-------------------
A tabela de pontuacao estava sendo redescoberta por regressao em DOIS lugares
(escalar_time.py e backtest_escalacao.py), com o mesmo defeito nos dois: a
regressao rodava sobre `posicao != "TEC"`, o que deixa passar 17 linhas com
posicao "?" (tecnicos mal classificados na coleta). Essas 17 linhas tem
scout_V preenchido, e como nenhum jogador de linha pontua por vitoria, a
regressao inventava um peso V=+7.35 e degradava todos os outros coeficientes:
R2=0.9902, erro medio 0.038 ponto.

Filtrando para as cinco posicoes reais de linha, a mesma regressao recupera
a tabela EXATA -- R2=1.0000, erro 0.0000, todos os 19 scouts batendo na
casa decimal com a tabela oficial de cartola.globo.com/#!/entenda-mais.
Nao e "quase certo": e a tabela, recuperada dos dados.

O arquivo data/cartola_tabela_pontuacao.json guarda a tabela OFICIAL
transcrita do site. conferir_tabela() cruza as duas a cada execucao. Se o
Cartola mudar a pontuacao no meio da temporada (ja mudou: DS e DE foram
reajustados para cima em temporadas anteriores), os dados novos vao divergir
do arquivo e o pipeline avisa, em vez de seguir escalando com peso velho.

ENCOLHIMENTO (o motivo de existir estimar_k_encolhimento)
--------------------------------------------------------
A taxa de scout de um jogador e uma media de poucos jogos -- a mediana e 10.
Encolher para a media da posicao e obrigatorio. O que este modulo corrige e o
K UNICO: o codigo antigo usava K=5 para todo scout, como se gol e desarme
fossem igualmente previsiveis. Nao sao. Autocorrelacao de rodada para rodada,
medida em 4.727 pares de jogos consecutivos:

    DS 0.231 | FS 0.292 | SG 0.222 | FC 0.179 | FD 0.113 | G 0.090 | A 0.055

Desarme e falta sofrida sao habito; gol e assistencia sao evento. Com K=5
para todos, tres gols em seis jogos viram uma taxa quase intacta valendo 8
pontos cada, enquanto o desarme -- o scout que de fato se repete -- fica
subaproveitado. Bayes empirico resolve isso medindo, por scout e posicao,
K = variancia_dentro_do_jogador / variancia_entre_jogadores: quanto mais
ruidoso o scout, mais forte o encolhimento.

Validado walk-forward nas rodadas 8-21 (correlacao entre criterio e pontuacao
real da rodada seguinte, teste pareado por rodada, tudo estimado so com
rodadas anteriores a cada rodada testada):

    ZAG+LAT   media 0.109  ->  K=5 0.142  ->  Bayes empirico 0.172  (t=+2.91)
    MEI       0.203        ->      0.200  ->                0.192   (t=-0.45)
    ATA       0.210        ->      0.203  ->                0.197   (t=-0.42)

Ganho significativo exatamente onde o desarme domina a pontuacao (zagueiro e
lateral), sem perda estatistica nas outras posicoes.
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TABELA_OFICIAL_PATH = DATA_DIR / "cartola_tabela_pontuacao.json"

# As cinco posicoes de linha. Qualquer outra coisa ("TEC", "?") fica de fora
# da regressao -- ver o cabecalho deste arquivo.
POSICOES_LINHA = ("GOL", "LAT", "ZAG", "MEI", "ATA")

# Scouts que so existem para certas posicoes. Somar SG de atacante ou DE de
# zagueiro so adiciona a media da posicao (que e ~0) ao E[pts] de todo mundo.
SCOUTS_RESTRITOS = {
    "SG": ("GOL", "ZAG", "LAT"),
    "DE": ("GOL",),
    "DP": ("GOL",),
    "GS": ("GOL",),
}

# Vitoria e scout exclusivo de tecnico; nunca entra na pontuacao de linha.
SCOUT_TECNICO = "V"


class TabelaError(RuntimeError):
    pass


def scouts_do_historico(hist):
    """Siglas de scout presentes no CSV, sem o 'V' (exclusivo de tecnico)."""
    return sorted(c[len("scout_"):] for c in hist[0]
                  if c.startswith("scout_") and c != f"scout_{SCOUT_TECNICO}")


def scout_vale_para(scout, pos):
    """O scout pontua nessa posicao?"""
    return pos in SCOUTS_RESTRITOS.get(scout, POSICOES_LINHA)


def linhas_de_linha(hist):
    """So jogadores de linha -- exclui TEC e as linhas com posicao '?'."""
    return [r for r in hist if r["posicao"] in POSICOES_LINHA]


def recuperar_tabela(hist):
    """Recupera quanto vale cada scout regredindo `pontos` contra os scouts.

    Devolve (tabela, diagnostico). Com o filtro de posicao correto isso e
    exato (R2=1.0), entao o diagnostico serve para acusar se algum dia deixar
    de ser -- e sinal de coleta corrompida ou de scout novo na tabela.
    """
    linha = linhas_de_linha(hist)
    if not linha:
        raise TabelaError("Historico sem nenhuma linha de jogador de linha "
                          f"(posicoes esperadas: {', '.join(POSICOES_LINHA)})")

    scouts = scouts_do_historico(hist)
    X = np.array([[float(r[f"scout_{s}"] or 0) for s in scouts] for r in linha])
    y = np.array([float(r["pontos"] or 0) for r in linha])
    pesos, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ pesos

    denom = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ((y - pred) ** 2).sum() / denom if denom else float("nan")
    tabela = {s: round(float(p), 2) for s, p in zip(scouts, pesos) if abs(p) > 0.01}
    diag = {"r2": float(r2), "erro_medio": float(np.abs(y - pred).mean()),
            "n": len(linha)}
    return tabela, diag


def carregar_tabela_oficial(path=None):
    """Tabela transcrita de cartola.globo.com/#!/entenda-mais."""
    path = Path(path) if path else TABELA_OFICIAL_PATH
    if not path.exists():
        raise TabelaError(f"Tabela oficial nao encontrada: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {s: float(d["pontos"]) for s, d in doc["scouts"].items()}, doc


def conferir_tabela(recuperada, oficial, tolerancia=0.005):
    """Cruza a tabela recuperada dos dados com a oficial.

    Devolve lista de divergencias (vazia = tudo batendo). Nao levanta erro:
    quem chama decide se para ou so avisa, mas ninguem escala achando que a
    tabela e uma quando os dados dizem outra.
    """
    problemas = []
    for s, oficial_pts in sorted(oficial.items()):
        if s not in recuperada:
            # Scout que existe na tabela mas nunca aconteceu no historico
            # (ex: DP em poucas rodadas) nao e divergencia.
            continue
        if abs(recuperada[s] - oficial_pts) > tolerancia:
            problemas.append(
                f"{s}: dados dizem {recuperada[s]:+.2f}, tabela oficial diz "
                f"{oficial_pts:+.2f}")
    for s in sorted(set(recuperada) - set(oficial)):
        problemas.append(f"{s}: aparece nos dados ({recuperada[s]:+.2f}) mas "
                         f"nao esta na tabela oficial -- scout novo?")
    return problemas


def jogou(row, scouts):
    """O jogador entrou em campo nessa rodada?

    O historico traz linha para atleta que nao jogou (tudo zerado). Incluir
    esses jogos na media divide a taxa por um denominador inflado.
    """
    if float(row["pontos"] or 0) != 0:
        return True
    return any(float(row[f"scout_{s}"] or 0) for s in scouts)


def agrupar_por_jogador(hist, scouts, apenas_jogados=True):
    """{atleta_id: [rodadas]} para jogadores de linha, ordenado por rodada."""
    por_jogador = defaultdict(list)
    for r in linhas_de_linha(hist):
        if apenas_jogados and not jogou(r, scouts):
            continue
        por_jogador[r["atleta_id"]].append(r)
    for aid in por_jogador:
        por_jogador[aid].sort(key=lambda r: int(r["rodada"]))
    return por_jogador


def medias_posicionais(por_jogador, scouts):
    """Taxa media de cada scout por posicao -- o alvo do encolhimento."""
    soma = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for jogos in por_jogador.values():
        pos = jogos[0]["posicao"]
        n[pos] += len(jogos)
        for r in jogos:
            for s in scouts:
                soma[pos][s] += float(r[f"scout_{s}"] or 0)
    return {p: {s: soma[p][s] / n[p] for s in scouts} for p in n}


# Sem sinal individual detectavel, encolhe tudo para a media da posicao.
K_MAXIMO = 999.0
# Piso: mesmo o scout mais repetivel merece algum encolhimento com 3 jogos.
K_MINIMO = 0.5
MIN_JOGOS_PARA_K = 4      # jogador precisa disso para entrar na estimativa
MIN_JOGADORES_PARA_K = 15  # posicao precisa disso para ter K proprio


def estimar_k_encolhimento(por_jogador, scouts):
    """K de Bayes empirico por (scout, posicao) = var_dentro / var_entre.

    Metodo dos momentos, o mesmo que da a formula de encolhimento
    peso = n/(n+K):

      var(medias observadas) = var_entre + media(var_dentro / n_i)

    entao var_entre = var(medias) - var_dentro * media(1/n_i). Se isso da
    zero ou negativo, o scout nao distingue jogador nenhum dentro da posicao
    (e o caso do gol de zagueiro) e K vai para K_MAXIMO: todo mundo recebe a
    media da posicao, que e a resposta honesta.

    Estimado SO com os jogos passados a quem chama -- em backtest isso
    precisa ser refeito rodada a rodada para nao vazar futuro.
    """
    por_posicao = defaultdict(list)
    for jogos in por_jogador.values():
        if len(jogos) >= MIN_JOGOS_PARA_K:
            por_posicao[jogos[0]["posicao"]].append(jogos)

    K = {}
    for pos, jogadores in por_posicao.items():
        if len(jogadores) < MIN_JOGADORES_PARA_K:
            continue
        n_por_jogador = np.array([len(j) for j in jogadores], dtype=float)
        graus = float((n_por_jogador - 1).sum())
        for s in scouts:
            valores = [np.array([float(r[f"scout_{s}"] or 0) for r in j])
                       for j in jogadores]
            medias = np.array([v.mean() for v in valores])
            if graus <= 0:
                continue
            var_dentro = sum(((v - v.mean()) ** 2).sum() for v in valores) / graus
            var_entre = medias.var(ddof=1) - var_dentro * float(np.mean(1 / n_por_jogador))
            if var_dentro <= 0 or var_entre <= 1e-9:
                K[(s, pos)] = K_MAXIMO
            else:
                K[(s, pos)] = float(np.clip(var_dentro / var_entre, K_MINIMO, K_MAXIMO))
    return K


def taxas_encolhidas(por_jogador, scouts, K, media_pos):
    """Taxa de cada scout por jogador, encolhida com o K daquele scout/posicao.

    {atleta_id: {"pos", "n", "taxas": {scout: taxa}, "cru": {scout: taxa}}}.
    `cru` guarda a media sem encolher -- serve para exibir "desarmes por jogo"
    de verdade na tela, que e um numero observado, nao uma estimativa.
    """
    saida = {}
    for aid, jogos in por_jogador.items():
        pos = jogos[0]["posicao"]
        if pos not in media_pos:
            continue
        n = len(jogos)
        taxas, cru = {}, {}
        for s in scouts:
            bruto = sum(float(r[f"scout_{s}"] or 0) for r in jogos) / n
            k = K.get((s, pos), 5.0)
            peso = n / (n + k)
            cru[s] = bruto
            taxas[s] = peso * bruto + (1 - peso) * media_pos[pos][s]
        saida[aid] = {"pos": pos, "n": n, "taxas": taxas, "cru": cru}
    return saida
