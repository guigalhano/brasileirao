#!/usr/bin/env python3
"""
Atualiza os próximos jogos (DATA array) no index.html para a rodada 22
(11-12 de agosto de 2026).

Uso:
    python update_next_matches.py --repo-dir D:\\brasileirao
"""

import argparse
import json
import math
import re
from pathlib import Path

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def match_probs(lam_home, lam_away, max_goals=10):
    p_home = p_draw = p_away = 0.0
    for i in range(max_goals + 1):
        pi = poisson_pmf(i, lam_home)
        for j in range(max_goals + 1):
            pj = poisson_pmf(j, lam_away)
            p = pi * pj
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total

def expected_goals(ratings, home_adv, home_team, away_team):
    h = ratings[home_team]
    a = ratings[away_team]
    lam_home = math.exp(h["attack"] - a["defense"] + home_adv)
    lam_away = math.exp(a["attack"] - h["defense"])
    return lam_home, lam_away

# Rodada 22 - próximos 10 jogos (11-12 de agosto de 2026)
NEXT_MATCHES_R22 = [
    {"home": "Flamengo", "away": "Chapecoense", "day": "Dom 11/08", "time": "18:30"},
    {"home": "Palmeiras", "away": "Corinthians", "day": "Dom 11/08", "time": "18:30"},
    {"home": "Bahia", "away": "Fluminense", "day": "Dom 11/08", "time": "18:30"},
    {"home": "Gremio", "away": "Coritiba", "day": "Dom 11/08", "time": "20:30"},
    {"home": "Atletico-PR", "away": "Botafogo", "day": "Dom 11/08", "time": "20:30"},
    {"home": "Santos", "away": "Vitoria", "day": "Dom 11/08", "time": "20:30"},
    {"home": "Vasco", "away": "Atletico-MG", "day": "Seg 12/08", "time": "20:30"},
    {"home": "Cruzeiro", "away": "Mirassol", "day": "Seg 12/08", "time": "20:30"},
    {"home": "Bragantino", "away": "Internacional", "day": "Ter 13/08", "time": "19:30"},
    {"home": "Remo", "away": "Sao Paulo", "day": "Ter 13/08", "time": "21:30"},
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    index_path = repo / "index.html"
    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"

    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    # Calcular xG e probabilidades para cada jogo
    data = []
    for match in NEXT_MATCHES_R22:
        home = match["home"]
        away = match["away"]

        if home not in ratings or away not in ratings:
            print(f"Aviso: {home} ou {away} não têm ratings, pulando")
            continue

        lam_home, lam_away = expected_goals(ratings, home_adv, home, away)
        p_home, p_draw, p_away = match_probs(lam_home, lam_away)

        match_data = {
            "home": home,
            "away": away,
            "day": match["day"],
            "time": match["time"],
            "model": [round(p_home, 4), round(p_draw, 4), round(p_away, 4)],
            "xg": [round(lam_home, 2), round(lam_away, 2)]
        }
        data.append(match_data)
        print(f"{home:20} vs {away:20} | xG: {lam_home:.2f}-{lam_away:.2f} | P: {p_home:.1%} {p_draw:.1%} {p_away:.1%}")

    # Atualizar o arquivo HTML
    html_text = index_path.read_text(encoding="utf-8")
    json_str = json.dumps(data)
    new_html = re.sub(
        r"var DATA = \[.*?\];",
        f"var DATA = {json_str};",
        html_text,
        flags=re.DOTALL
    )

    index_path.write_text(new_html, encoding="utf-8")

    # Atualizar o título da rodada
    new_html = re.sub(
        r"Próximos jogos.*?Rodada \d+",
        "Próximos jogos · Rodada 22",
        new_html
    )

    print(f"\nOK: {len(data)} jogos atualizados para Rodada 22 (11-13/08)")

if __name__ == "__main__":
    main()
