#!/usr/bin/env python3
"""
Atualiza os proximos jogos do index.html a partir de data/proximos_jogos.json.

O QUE MUDOU (fase 1 da auditoria)
---------------------------------
1. MERGE em vez de sobrescrita. Antes este script regravava o `var DATA`
   inteiro com so {home, away, day, time, model, xg}, apagando analysis,
   analysis_grid, forecast, matchup, market e odds. Foi o que matou a aba
   de analises do site no commit b69d041 -- e como o workflow diario roda
   este script, ela morria de novo a cada execucao. Agora ele so escreve
   model/xg e preserva o resto.

2. FALHA ALTO em time desconhecido. Antes imprimia "[AVISO] ... pulando" e
   seguia: na rodada 23, 7 dos 20 nomes nao casaram e o site foi publicado
   com 5 dos 10 jogos. Agora nomes passam por lib.teams.canonical(), que
   levanta erro -- meia rodada no ar e pior do que pipeline quebrado.

3. Confrontos vem so de data/proximos_jogos.json, via lib.fixtures.

Uso:
    python scripts/update_next_matches_dynamic.py --repo-dir .
    python scripts/update_next_matches_dynamic.py --repo-dir . --dry-run
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.fixtures import load_fixtures, FixturesError
from lib.index_data import write_data, set_round_label, CAMPOS_ANALISE
from lib.teams import check_ratings_cover_canonical, UnknownTeamError


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def match_probs(lam_home, lam_away, max_goals=10):
    p_home = p_draw = p_away = 0.0
    for i in range(max_goals + 1):
        pi = poisson_pmf(i, lam_home)
        for j in range(max_goals + 1):
            p = pi * poisson_pmf(j, lam_away)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


def expected_goals(ratings, home_adv, home_team, away_team):
    h, a = ratings[home_team], ratings[away_team]
    return (math.exp(h["attack"] - a["defense"] + home_adv),
            math.exp(a["attack"] - h["defense"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="calcula e mostra, sem gravar no index.html")
    args = ap.parse_args()

    repo = Path(args.repo_dir).resolve()
    index_path = repo / "index.html"

    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"

    try:
        rodada, jogos, meta = load_fixtures(repo / "data" / "proximos_jogos.json")
    except (FixturesError, UnknownTeamError) as e:
        print(f"[ERRO] {e}")
        return 1

    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    try:
        check_ratings_cover_canonical(ratings)
    except UnknownTeamError as e:
        print(f"[ERRO] {ratings_path.name}: {e}")
        return 1

    print(f"\n{'=' * 74}")
    print(f"Rodada {rodada} ({meta['data_inicio']} - {meta['data_fim']})")
    print(f"{'=' * 74}\n")

    novos = []
    for j in jogos:
        home, away = j["home"], j["away"]
        lam_h, lam_a = expected_goals(ratings, home_adv, home, away)
        p_h, p_d, p_a = match_probs(lam_h, lam_a)
        novos.append({
            "home": home, "away": away, "day": j["day"], "time": j["time"],
            "model": [round(p_h, 4), round(p_d, 4), round(p_a, 4)],
            "xg": [round(lam_h, 2), round(lam_a, 2)],
        })
        print(f"{home:16} vs {away:16} | xG: {lam_h:.2f}-{lam_a:.2f} "
              f"| P: {p_h:.1%} {p_d:.1%} {p_a:.1%}")

    if len(novos) != len(jogos):
        print(f"[ERRO] {len(jogos)} confrontos entraram, {len(novos)} sairam.")
        return 1

    if args.dry_run:
        print(f"\n[DRY-RUN] {len(novos)} jogos calculados. Nada foi gravado.")
        return 0

    preservados = write_data(index_path, novos, merge=True)
    set_round_label(index_path, rodada)

    print(f"\n[OK] {len(novos)}/{len(jogos)} jogos gravados para a rodada {rodada}")
    if preservados:
        print(f"[MERGE] {preservados} jogo(s) mantiveram campos ja existentes "
              f"({', '.join(CAMPOS_ANALISE)}...)")
    else:
        print("[MERGE] nenhum campo anterior a preservar "
              "(rode generate_advanced_analytics.py para popular as analises)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
