#!/usr/bin/env python3
"""
compute_advanced_signals.py

Calcula 3 sinais avancados por jogador a partir do historico rodada-a-rodada
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
   entrou em campo (entrou_em_campo=True), independente do status "Provavel"
   atual. Jogador "Provavel" que so jogou 1 dos ultimos 5 jogos e sinal de
   risco de rotacao que o status sozinho nao capta.

Uso:
    python3 compute_advanced_signals.py --repo-dir /caminho/para/repo
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

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


def scout_val(row, col):
    v = row.get(col)
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def per_round_scout(games, col):
    """Converte o scout `col` (ex: 'G', 'A') pra valor POR RODADA.

    IMPORTANTE: nas rodadas <=18 (dataset caRtola) o scout e' CUMULATIVO
    (acumulado da temporada ate aquela rodada); nas rodadas >=19 (coletado do
    endpoint /atletas/pontuados) ja e' POR RODADA. Somar direto o cumulativo
    infla tudo (foi o bug que corrompia o playmaking). Aqui: no bloco <=18
    tiramos a diferenca entre rodadas consecutivas; de 19 em diante usamos o
    valor como esta. Retorna dict {rodada_id: valor_por_rodada}.
    """
    games = sorted(games, key=lambda g: int(g["rodada"]))
    out = {}
    prev_cum = 0.0
    for g in games:
        rod = int(g["rodada"])
        v = scout_val(g, col)
        if rod <= 18:
            pr = v - prev_cum
            prev_cum = v
        else:
            pr = v  # ja e' por-rodada
        out[rod] = max(pr, 0.0)  # clip: diffs negativos (correcao de scout) viram 0
    return out


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
    by_player = defaultdict(list)
    for r in hist_rows:
        by_player[r["atleta_id"]].append(r)
    for pid in by_player:
        by_player[pid].sort(key=lambda r: int(r["rodada"]))

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

        played = [g for g in games if g["entrou_em_campo"] == "True"]

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
            participou = sum(1 for g in last5_all if g["entrou_em_campo"] == "True")
            risco_rotacao = round(1 - participou / len(last5_all), 3)
        else:
            risco_rotacao = None

        output_rows.append({
            "atleta_id": pid,
            "ult5_sos": ult5_sos if ult5_sos is not None else "",
            "playmaking": playmaking if playmaking is not None else "",
            "risco_rotacao": risco_rotacao if risco_rotacao is not None else "",
            "goalShare": goal_share if goal_share is not None else "",
        })

    out_path = repo / "data" / "advanced_signals.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["atleta_id", "ult5_sos", "playmaking", "risco_rotacao", "goalShare"])
        w.writeheader()
        w.writerows(output_rows)
    print(f"OK: {len(output_rows)} jogadores salvos em {out_path}")


if __name__ == "__main__":
    main()
