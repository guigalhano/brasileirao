#!/usr/bin/env python3
"""
compute_advanced_signals.py

Calcula os sinais avancados por jogador a partir do historico rodada-a-rodada
(data/cartola_historico_2026_completo.csv) e grava em
data/advanced_signals.csv, para o build_index.py incluir no array PLAYERS.

1) ult5_sos: "forma recente" (ultimas 5 rodadas jogadas) AJUSTADA pela forca
   do adversario enfrentado em cada uma delas. 5 boas atuacoes contra times
   fracos NAO contam igual a 5 boas atuacoes contra times fortes.
   Formula por rodada: pontos_ajustados = pontos_reais / dificuldade,
   onde dificuldade e o mesmo "matchup factor" (Poisson/Dixon-Coles) usado
   no resto do site -- >1 = jogo facil (desconta), <1 = jogo dificil (premia).

2) playmaking: taxa real de assistencias por jogo (A somado / jogos com
   participacao), so pra MEI -- sinal de criacao de chance que hoje nao
   existe (so tinhamos finalizacao/xG, nada de criacao).

3) risco_rotacao: fracao das ultimas 5 rodadas em que o jogador REALMENTE
   entrou em campo, independente do status "Provavel" atual. Jogador
   "Provavel" que so jogou 1 dos ultimos 5 jogos e sinal de risco de
   rotacao que o status sozinho nao capta.

4) ds_jogo: desarmes por jogo. E o scout que mais decide a pontuacao de
   defensor -- 1,5 ponto cada, 1,31 por jogo de lateral, 1,04 de zagueiro --
   e o unico sinal desses que se repete de rodada pra rodada de verdade
   (autocorrelacao 0,231 contra 0,090 do gol). Numero observado, sem
   encolher: serve pra mostrar na tela.

5) epts_scouts: pontuacao esperada montada scout a scout, com encolhimento
   de Bayes empirico por scout (lib/pontuacao.py). E o sinal defensivo que
   faltava: em backtest walk-forward nas rodadas 8-21, para ZAG/LAT a
   correlacao com a pontuacao da rodada seguinte foi 0,177 contra 0,120 da
   media -- e a diferenca contra o encolhimento uniforme e significativa
   (t=+2,5). Neutro quanto a confronto de proposito: o ajuste de adversario
   ja e aplicado no index.html, aplicar aqui tambem contaria duas vezes.

DUAS CORRECOES FEITAS AQUI (agosto/2026)
----------------------------------------
a) O script estava QUEBRADO: lia g["entrou_em_campo"], coluna que nao existe
   mais no CSV do historico, e morria com KeyError. Ninguem percebeu porque
   o build_index.py so le o advanced_signals.csv que ja estava no disco --
   entao o site vinha servindo sinais congelados em 29/07 com cara de atual.
   Agora "jogou" e deduzido do proprio scout (lib.pontuacao.jogou).

b) O per_round_scout() diferenciava os scouts das rodadas <=18 achando que
   vinham cumulativos da temporada. Nao vem: em 24% dos pares de rodadas
   consecutivas o scout DIMINUI, o que e impossivel num acumulado, e a
   regressao de pontos (que sao por rodada) contra os scouts crus da
   R2=1,0000 com erro zero -- so fecha se scout e pontos estiverem na mesma
   base. A diferenciacao estava subtraindo valor legitimo e zerando o
   restante, corrompendo goalShare e playmaking. Removida.

Uso:
    python3 compute_advanced_signals.py --repo-dir /caminho/para/repo
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.pontuacao import (agrupar_por_jogador, estimar_k_encolhimento, jogou,
                           medias_posicionais, recuperar_tabela,
                           scout_vale_para, scouts_do_historico,
                           taxas_encolhidas)

CLUB_ABBREV_TO_NAME = {
    "BAH": "Bahia", "BOT": "Botafogo", "CAM": "Atletico-MG", "CAP": "Atletico-PR",
    "CFC": "Coritiba", "CHA": "Chapecoense", "COR": "Corinthians", "CRU": "Cruzeiro",
    "FLA": "Flamengo", "FLU": "Fluminense", "GRE": "Gremio", "INT": "Internacional",
    "MIR": "Mirassol", "PAL": "Palmeiras", "RBB": "Bragantino", "REM": "Remo",
    "SAN": "Santos", "SAO": "Sao Paulo", "VAS": "Vasco", "VIT": "Vitoria",
}
POSICAO_ID_TO_POS = {"1": "GOL", "2": "LAT", "3": "ZAG", "4": "MEI", "5": "ATA", "6": "TEC"}
AVG_LAM_HIST = None  # calculado a partir dos proprios jogos do ano, ver main()


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def scout_val(row, scout):
    """Valor do scout (ex: 'G', 'DS') naquela rodada.

    TERCEIRA falha silenciosa deste arquivo (agosto/2026): a versao anterior
    recebia o nome da coluna e fazia row.get(col) com col="G". A coluna do CSV
    chama scout_G, nao G, entao o get devolvia None, o codigo convertia em 0.0
    e seguia. Todo goalShare e todo playmaking do site foram zero desde sempre
    por causa disso -- sem erro, sem aviso, so um numero errado.

    Agora recebe a SIGLA do scout, monta o nome da coluna e levanta erro se
    ela nao existir. Coluna faltando e problema de coleta e tem que aparecer.
    """
    col = f"scout_{scout}"
    if col not in row:
        raise KeyError(
            f"Coluna {col!r} nao existe no historico do Cartola. "
            f"Colunas de scout disponiveis: "
            f"{sorted(c for c in row if c.startswith('scout_'))}")
    v = row[col]
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def per_round_scout(games, col):
    """Scout `col` (ex: 'G', 'A') por rodada: {rodada_id: valor}.

    O scout ja vem por rodada no CSV, em toda a temporada -- ver a correcao
    (b) no cabecalho deste arquivo. Esta funcao so indexa por rodada.
    """
    return {int(g["rodada"]): scout_val(g, col)
            for g in sorted(games, key=lambda g: int(g["rodada"]))}


def build_team_fixtures_by_round(matches_path):
    rows = list(csv.DictReader(open(matches_path, encoding="utf-8")))
    s2026 = [r for r in rows if r["season"] == "2026"]
    matches_by_team = defaultdict(list)
    for r in s2026:
        matches_by_team[r["home_team"]].append(r)
        matches_by_team[r["away_team"]].append(r)
    for team in matches_by_team:
        matches_by_team[team] = sorted(matches_by_team[team], key=lambda r: r["date"])
    fixture_by_team_round = {}
    for team, matches in matches_by_team.items():
        for i, m in enumerate(matches, start=1):
            is_home = m["home_team"] == team
            opponent = m["away_team"] if is_home else m["home_team"]
            fixture_by_team_round[(team, i)] = {"opponent": opponent, "is_home": is_home}
    return fixture_by_team_round


def matchup_difficulty(pos, ratings, home_adv, avg_lam, team, opponent, is_home):
    """>1 = jogo facil (adversario fraco), <1 = jogo dificil (adversario forte)."""
    if team not in ratings or opponent not in ratings:
        return 1.0
    if is_home:
        lam_for = math.exp(ratings[team]["attack"] - ratings[opponent]["defense"] + home_adv)
        lam_against = math.exp(ratings[opponent]["attack"] - ratings[team]["defense"])
    else:
        lam_for = math.exp(ratings[team]["attack"] - ratings[opponent]["defense"])
        lam_against = math.exp(ratings[opponent]["attack"] - ratings[team]["defense"] + home_adv)

    avg_cs = poisson_pmf(0, avg_lam)
    clean_sheet_prob = poisson_pmf(0, lam_against)
    attack_factor = lam_for / avg_lam
    defense_factor = clean_sheet_prob / avg_cs

    if pos in ("ATA", "MEI"):
        factor = attack_factor
    elif pos in ("GOL", "ZAG"):
        factor = defense_factor
    elif pos == "LAT":
        factor = 0.6 * defense_factor + 0.4 * attack_factor
    else:
        factor = 0.5 * attack_factor + 0.5 * defense_factor
    return max(0.5, min(1.8, factor))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()
    repo = Path(args.repo_dir)

    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"
    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    matches = [r for r in csv.DictReader(open(repo / "data" / "matches_2012_2026.csv", encoding="utf-8"))
               if r["season"] == "2026"]
    matches = [m for m in matches if m["home_team"] in ratings and m["away_team"] in ratings]
    lams = []
    for m in matches:
        h, a = m["home_team"], m["away_team"]
        lams.append(math.exp(ratings[h]["attack"] - ratings[a]["defense"] + home_adv))
        lams.append(math.exp(ratings[a]["attack"] - ratings[h]["defense"]))
    avg_lam = sum(lams) / len(lams)
    print(f"AVG_LAM usado (calculado dos jogos 2026): {avg_lam:.4f}")

    fixture_by_team_round = build_team_fixtures_by_round(repo / "data" / "matches_2012_2026.csv")

    hist_rows = list(csv.DictReader(open(repo / "data" / "cartola_historico_2026_completo.csv", encoding="utf-8")))
    scouts = scouts_do_historico(hist_rows)
    by_player = defaultdict(list)
    for r in hist_rows:
        by_player[r["atleta_id"]].append(r)
    for pid in by_player:
        by_player[pid].sort(key=lambda r: int(r["rodada"]))

    # Pontuacao esperada por scout, com encolhimento medido por scout/posicao.
    # Sem ajuste de confronto: o index.html aplica o dele por cima.
    tabela, diag = recuperar_tabela(hist_rows)
    print(f"Tabela de pontuacao recuperada: R2={diag['r2']:.4f} "
          f"({diag['n']} observacoes)")
    por_jogador = agrupar_por_jogador(hist_rows, scouts)
    media_pos = medias_posicionais(por_jogador, scouts)
    K = estimar_k_encolhimento(por_jogador, scouts)
    taxas = taxas_encolhidas(por_jogador, scouts, K, media_pos)
    epts_por_jogador = {}
    for pid, info in taxas.items():
        epts_por_jogador[pid] = round(sum(
            peso * info["taxas"][s] for s, peso in tabela.items()
            if scout_vale_para(s, info["pos"])), 3)

    # Gols POR RODADA de cada jogador (normalizados) e total por time -- pro goalShare.
    player_goals_pr = {}   # pid -> total de gols por-rodada na temporada
    team_goals_total = defaultdict(float)
    for pid, games in by_player.items():
        g_pr = per_round_scout(games, "G")
        total_g = sum(g_pr.values())
        player_goals_pr[pid] = total_g
        team_abbrev = games[0]["clube"]
        team_goals_total[team_abbrev] += total_g

    output_rows = []
    for pid, games in by_player.items():
        team_abbrev = games[0]["clube"]
        team = CLUB_ABBREV_TO_NAME.get(team_abbrev)
        pos = games[0]["posicao"]
        if team is None or pos is None:
            continue

        # "Entrou em campo" deduzido do proprio scout: a coluna entrou_em_campo
        # nao existe mais no CSV, e era ela que derrubava este script.
        played = [g for g in games if jogou(g, scouts)]

        # 1) ult5 ajustado por forca do adversario (ultimas 5 rodadas jogadas)
        last5 = played[-5:]
        adj_scores = []
        for g in last5:
            rodada = int(g["rodada"])
            fx = fixture_by_team_round.get((team, rodada))
            dificuldade = 1.0
            if fx:
                dificuldade = matchup_difficulty(pos, ratings, home_adv, avg_lam,
                                                  team, fx["opponent"], fx["is_home"])
            pontos = float(g["pontos"])
            adj_scores.append(pontos / dificuldade if dificuldade > 0 else pontos)
        ult5_sos = round(sum(adj_scores) / len(adj_scores), 3) if adj_scores else None

        # 2) playmaking real (assistencias POR RODADA por jogo), so relevante pra MEI.
        # CONSERTADO: usa o scout A normalizado pra por-rodada (antes somava o
        # cumulativo, inflando ~5x). So conta os jogos em que entrou em campo.
        playmaking = None
        if pos == "MEI" and played:
            a_pr = per_round_scout(games, "A")
            rounds_played = {int(g["rodada"]) for g in played}
            total_a = sum(v for rod, v in a_pr.items() if rod in rounds_played)
            playmaking = round(total_a / len(played), 3)

        # 4) goalShare: fatia dos gols do TIME que esse jogador concentrou na
        # temporada (gols por-rodada normalizados). So pra ATA/MEI -- validado
        # em backtest walk-forward (r=0.162, acima do limiar de ruido ~0.10).
        goal_share = None
        if pos in ("ATA", "MEI"):
            tg = team_goals_total.get(team_abbrev, 0.0)
            if tg > 0:
                goal_share = round(player_goals_pr.get(pid, 0.0) / tg, 4)

        # 3) risco de rotacao: fracao das ultimas 5 rodadas (jogadas ou nao)
        # em que o jogador de fato entrou em campo
        last5_all = games[-5:]
        if last5_all:
            participou = sum(1 for g in last5_all if jogou(g, scouts))
            risco_rotacao = round(1 - participou / len(last5_all), 3)
        else:
            risco_rotacao = None

        # 5) desarme: taxa observada (pra mostrar) e quanto ela vale em ponto.
        ds_jogo = round(sum(scout_val(g, "DS") for g in played) / len(played), 3) \
            if played else None
        epts_scouts = epts_por_jogador.get(pid)

        output_rows.append({
            "atleta_id": pid,
            "ult5_sos": ult5_sos if ult5_sos is not None else "",
            "playmaking": playmaking if playmaking is not None else "",
            "risco_rotacao": risco_rotacao if risco_rotacao is not None else "",
            "goalShare": goal_share if goal_share is not None else "",
            "ds_jogo": ds_jogo if ds_jogo is not None else "",
            "epts_scouts": epts_scouts if epts_scouts is not None else "",
        })

    out_path = repo / "data" / "advanced_signals.csv"
    campos = ["atleta_id", "ult5_sos", "playmaking", "risco_rotacao",
              "goalShare", "ds_jogo", "epts_scouts"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(output_rows)
    com_ds = sum(1 for r in output_rows if r["ds_jogo"] != "")
    print(f"OK: {len(output_rows)} jogadores salvos em {out_path} "
          f"({com_ds} com desarme por jogo)")


if __name__ == "__main__":
    main()
