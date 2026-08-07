#!/usr/bin/env python3
"""
Atualiza os próximos jogos dinamicamente a partir de data/proximos_jogos.json
Basta editar o arquivo JSON para atualizar os confrontos da próxima rodada!

Uso:
    python update_next_matches_dynamic.py --repo-dir D:\\brasileirao
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    index_path = repo / "index.html"
    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"

    proximos_path = repo / "data" / "proximos_jogos.json"
    if not proximos_path.exists():
        print(f"Erro: arquivo {proximos_path} não encontrado!")
        return

    # Carregar dados
    proximos_doc = json.loads(proximos_path.read_text(encoding="utf-8"))
    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))

    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]
    rodada = proximos_doc["rodada"]
    matches = proximos_doc["jogos"]

    # Calcular xG e probabilidades para cada jogo
    data = []
    print(f"\n{'='*70}")
    print(f"Rodada {rodada} ({proximos_doc['data_inicio']} - {proximos_doc['data_fim']})")
    print(f"{'='*70}\n")

    for match in matches:
        home = match["home"]
        away = match["away"]

        if home not in ratings or away not in ratings:
            print(f"[AVISO] {home} ou {away} nao tem ratings, pulando")
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

    # Substituir DATA array de forma segura
    start_idx = html_text.find("var DATA = [")
    end_idx = html_text.find("];", start_idx) + 2
    if start_idx != -1 and end_idx > start_idx:
        new_html = html_text[:start_idx] + f"var DATA = {json_str};" + html_text[end_idx:]

        # Atualizar o título da rodada
        new_html = re.sub(
            r"Próximos jogos.*?Rodada \d+",
            f"Próximos jogos · Rodada {rodada}",
            new_html
        )

        index_path.write_text(new_html, encoding="utf-8")
    else:
        print("[ERRO] Nao conseguiu encontrar var DATA no HTML")

    print(f"\n[OK] {len(data)} jogos atualizados para Rodada {rodada}")
    print(f"[DATAS] {proximos_doc['data_inicio']} a {proximos_doc['data_fim']}")

if __name__ == "__main__":
    main()
