#!/usr/bin/env python3
"""
Gera dados de análise completos para cada jogo, consolidando as 7 análises.
"""

import json
import csv
import math
from collections import defaultdict
from pathlib import Path

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

# Mapeamento de abreviações
ABBREV = {
    'FLA': 'Flamengo', 'CHA': 'Chapecoense', 'PAL': 'Palmeiras', 'COR': 'Corinthians',
    'BAH': 'Bahia', 'FLU': 'Fluminense', 'GRE': 'Gremio', 'CFC': 'Coritiba',
    'CAP': 'Atletico-PR', 'BOT': 'Botafogo', 'SAN': 'Santos', 'VIT': 'Vitoria',
    'VAS': 'Vasco', 'CAM': 'Atletico-MG', 'CRU': 'Cruzeiro', 'MIR': 'Mirassol',
    'RBB': 'Bragantino', 'INT': 'Internacional', 'REM': 'Remo', 'SAO': 'Sao Paulo'
}

def build_analyses(repo_path):
    """Constrói análises para todos os 10 jogos."""

    # Carregar dados
    hist_rows = list(csv.DictReader(open(repo_path / "data" / "cartola_historico_2026_completo.csv", encoding="utf-8")))
    matches = list(csv.DictReader(open(repo_path / "data" / "matches_2012_2026.csv", encoding="utf-8")))
    matches_2026 = [m for m in matches if m['season'] == '2026']

    # Converter gols
    for m in matches_2026:
        m['home_goals'] = int(m['home_goals']) if m['home_goals'] else 0
        m['away_goals'] = int(m['away_goals']) if m['away_goals'] else 0

    # Ratings
    ratings_path = repo_path / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo_path / "data" / "team_ratings_final_v2.json"
    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    # Próximos jogos
    matches_r22 = [
        {"home": "Flamengo", "away": "Chapecoense", "day": "Dom 11/08", "time": "18:30", "model": [0.8121, 0.1188, 0.0691], "xg": [2.99, 0.8]},
        {"home": "Palmeiras", "away": "Corinthians", "day": "Dom 11/08", "time": "18:30", "model": [0.5072, 0.3069, 0.1858], "xg": [1.2, 0.6]},
        {"home": "Bahia", "away": "Fluminense", "day": "Dom 11/08", "time": "18:30", "model": [0.4528, 0.2302, 0.317], "xg": [1.77, 1.45]},
        {"home": "Gremio", "away": "Coritiba", "day": "Dom 11/08", "time": "20:30", "model": [0.4885, 0.2497, 0.2618], "xg": [1.59, 1.1]},
        {"home": "Atletico-PR", "away": "Botafogo", "day": "Dom 11/08", "time": "20:30", "model": [0.6867, 0.1766, 0.1368], "xg": [2.38, 0.97]},
        {"home": "Santos", "away": "Vitoria", "day": "Dom 11/08", "time": "20:30", "model": [0.528, 0.2347, 0.2373], "xg": [1.76, 1.1]},
        {"home": "Vasco", "away": "Atletico-MG", "day": "Seg 12/08", "time": "20:30", "model": [0.5798, 0.2056, 0.2146], "xg": [2.13, 1.23]},
        {"home": "Cruzeiro", "away": "Mirassol", "day": "Seg 12/08", "time": "20:30", "model": [0.567, 0.2319, 0.2011], "xg": [1.78, 0.96]},
        {"home": "Bragantino", "away": "Internacional", "day": "Ter 13/08", "time": "19:30", "model": [0.5408, 0.2185, 0.2407], "xg": [1.97, 1.25]},
        {"home": "Remo", "away": "Sao Paulo", "day": "Ter 13/08", "time": "21:30", "model": [0.3802, 0.2513, 0.3686], "xg": [1.43, 1.4]},
    ]

    # Análise 1 & 2: Forma e H2H
    result = []
    for match in matches_r22:
        home, away = match['home'], match['away']

        # H2H Analysis - Últimos 5 anos
        h2h_all = [m for m in matches if
                  (m['home_team'] == home and m['away_team'] == away) or
                  (m['home_team'] == away and m['away_team'] == home)]

        # Últimos 5 anos (desde 2021)
        h2h_5y = [m for m in h2h_all if int(m['season']) >= 2021]
        h2h_recent = sorted(h2h_5y, key=lambda x: x['date'])[-5:] if h2h_5y else []

        # Calcular stats do mandante nos últimos 5 anos
        home_wins_5y = sum(1 for m in h2h_5y if m['home_team'] == home and m['home_goals'] > m['away_goals'])
        away_wins_5y = sum(1 for m in h2h_5y if m['away_team'] == home and m['away_goals'] > m['home_goals'])
        draws_5y = len(h2h_5y) - home_wins_5y - away_wins_5y

        # Tendência recente (últimos 5 jogos)
        home_wins_recent = sum(1 for m in h2h_recent if m['home_team'] == home and m['home_goals'] > m['away_goals'])
        away_wins_recent = sum(1 for m in h2h_recent if m['away_team'] == home and m['away_goals'] > m['home_goals'])
        draws_recent = len(h2h_recent) - home_wins_recent - away_wins_recent

        # Dominância
        if home_wins_5y > away_wins_5y:
            dominance = "Casa historicamente favorita"
        elif away_wins_5y > home_wins_5y:
            dominance = "Visitante historicamente favorito"
        else:
            dominance = "Equilibrio historico"

        # Tendência
        if len(h2h_recent) > 0:
            if home_wins_recent > away_wins_recent:
                trend = " | Casa em alta"
            elif away_wins_recent > home_wins_recent:
                trend = " | Visitante em alta"
            else:
                trend = " | Padrão misto"
        else:
            trend = ""

        # Formato: "Casa 10-5-3 (5 anos) | Recente: 2-1-2 | Casa histórica"
        h2h_text = f"{home} {home_wins_5y}-{draws_5y}-{away_wins_5y} ({len(h2h_5y)} jogos/5 anos)"
        if h2h_recent:
            h2h_text += f" | Recente: {home_wins_recent}W-{draws_recent}D-{away_wins_recent}L"
        h2h_text += f" | {dominance}{trend}"

        # Casa vs Fora Analysis
        home_games = [m for m in matches_2026 if m['home_team'] == home]
        away_games_visiting = [m for m in matches_2026 if m['away_team'] == away]

        def win_pct(games, is_home):
            if not games:
                return 0
            wins = sum(1 for m in games if (is_home and m['home_goals'] > m['away_goals']) or (not is_home and m['away_goals'] > m['home_goals']))
            return round(100 * wins / len(games), 0)

        home_win = win_pct(home_games, True)
        away_win = win_pct(away_games_visiting, False)

        # Ataque/Defesa Analysis
        def off_def(games, team_name, is_home=None):
            if is_home is None:
                games = [m for m in games if m['home_team'] == team_name or m['away_team'] == team_name]
                gf = [m['home_goals'] if m['home_team'] == team_name else m['away_goals'] for m in games]
                ga = [m['away_goals'] if m['home_team'] == team_name else m['home_goals'] for m in games]
            elif is_home:
                games = [m for m in games if m['home_team'] == team_name]
                gf = [m['home_goals'] for m in games]
                ga = [m['away_goals'] for m in games]
            else:
                games = [m for m in games if m['away_team'] == team_name]
                gf = [m['away_goals'] for m in games]
                ga = [m['home_goals'] for m in games]

            if not games:
                return {'gf': 0, 'ga': 0, 'cs': 0}

            cs = sum(1 for g in ga if g == 0)
            return {
                'gf': round(sum(gf) / len(games), 2),
                'ga': round(sum(ga) / len(games), 2),
                'cs': round(100 * cs / len(games), 0)
            }

        home_stats = off_def(matches_2026, home)
        away_stats = off_def(matches_2026, away)

        # Forecast Analysis
        if home in ratings and away in ratings:
            h = ratings[home]
            a = ratings[away]
            lam_home = math.exp(h["attack"] - a["defense"] + home_adv)
            lam_away = math.exp(a["attack"] - h["defense"])

            scorelines = []
            for i in range(6):
                for j in range(6):
                    pi = poisson_pmf(i, lam_home)
                    pj = poisson_pmf(j, lam_away)
                    scorelines.append({
                        'score': f"{i}-{j}",
                        'prob': round(100 * pi * pj, 1)
                    })

            top3 = sorted(scorelines, key=lambda x: x['prob'], reverse=True)[:3]
            forecast = [f"{s['score']} ({s['prob']:.0f}%)" for s in top3]
        else:
            forecast = []

        # Consolidate all analyses
        analysis = {
            'h2h': h2h_text,
            'form': f"{home} {home_stats['gf']:.2f} gols/jogo vs {away} {away_stats['gf']:.2f} gols/jogo",
            'home_away': f"Casa: {home_win:.0f}% W vs Fora: {away_win:.0f}% W",
            'defense': f"{home} -/{home_stats['ga']:.2f} gols vs {away} -/{away_stats['ga']:.2f} gols",
            'clean_sheets': f"{home} {home_stats['cs']:.0f}% CS vs {away} {away_stats['cs']:.0f}% CS",
            'forecast': " | ".join(forecast) if forecast else "N/A",
            'summary': f"{home} favorito em casa ({home_win:.0f}%). {away} oferece resistencia ({away_win:.0f}%). {dominance} no H2H."
        }

        match_with_analysis = match.copy()
        match_with_analysis['analysis_full'] = analysis
        result.append(match_with_analysis)

    return result

if __name__ == "__main__":
    repo = Path(__file__).resolve().parent.parent
    analyses = build_analyses(repo)

    # Salvar JSON
    with open(repo / "data" / "matches_analysis_r22.json", "w", encoding="utf-8") as f:
        json.dump(analyses, f, ensure_ascii=False, indent=2)

    print(f"\nGerado: {len(analyses)} análises")
    print("Arquivo: data/matches_analysis_r22.json")

    # Preview
    for m in analyses[:2]:
        print(f"\n{m['home']} vs {m['away']}")
        print(f"  H2H: {m['analysis_full']['h2h']}")
        print(f"  Form: {m['analysis_full']['form']}")
        print(f"  Summary: {m['analysis_full']['summary']}")
