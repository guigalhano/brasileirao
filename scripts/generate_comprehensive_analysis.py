#!/usr/bin/env python3
"""
Gera análises completas (Fases 1 + 2) para cada jogo da próxima rodada.
Análises: Forma, H2H, Casa vs Fora, Momentum, Defesa/Ataque, Contexto, Forecast.

Uso:
    python generate_comprehensive_analysis.py --repo-dir D:\\brasileirao
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from datetime import datetime

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def get_team_performance(hist_rows, clube, rodadas_range):
    """Calcula performance de um time em um range de rodadas."""
    games = [r for r in hist_rows if r['clube'] == clube and int(r['rodada']) in rodadas_range]
    if not games:
        return {'jogos': 0, 'pontos_total': 0, 'pontos_media': 0, 'pontos_ultimo': 0}

    pontos = [float(r['pontos']) if r['pontos'] else 0 for r in games]
    return {
        'jogos': len(pontos),
        'pontos_total': sum(pontos),
        'pontos_media': sum(pontos) / len(pontos),
        'pontos_ultimo': pontos[-1] if pontos else 0,
        'pontos_list': pontos
    }

def classify_form(media):
    """Classifica forma em EXCELENTE/BOA/REGULAR/FRACA."""
    if media >= 40:
        return "EXCELENTE"
    elif media >= 30:
        return "BOA"
    elif media >= 20:
        return "REGULAR"
    else:
        return "FRACA"

def get_form_analysis(hist_rows, clube):
    """Análise 1: Forma (últimas 5 rodadas)."""
    perf = get_team_performance(hist_rows, clube, set(range(17, 22)))  # Rodadas 17-21

    if perf['jogos'] < 3:
        return None

    form_class = classify_form(perf['pontos_media'])
    trend = "UP" if perf['pontos_ultimo'] > perf['pontos_media'] else ("DOWN" if perf['pontos_ultimo'] < perf['pontos_media'] else "SAME")

    return {
        'classification': form_class,
        'average': round(perf['pontos_media'], 1),
        'last': round(perf['pontos_ultimo'], 1),
        'trend': trend,
        'games': perf['jogos']
    }

def get_h2h_analysis(matches, home_team, away_team):
    """Análise 2: Histórico H2H (últimos 5 jogos)."""
    h2h = [m for m in matches if
           (m['home_team'] == home_team and m['away_team'] == away_team) or
           (m['home_team'] == away_team and m['away_team'] == home_team)]

    if not h2h:
        return None

    h2h = sorted(h2h, key=lambda x: x['date'])[-5:]  # Últimos 5

    home_wins = sum(1 for m in h2h if m['home_team'] == home_team and m['home_goals'] > m['away_goals'])
    away_wins = sum(1 for m in h2h if m['away_team'] == home_team and m['away_goals'] > m['home_goals'])

    dominance = "HOME" if home_wins > away_wins else ("AWAY" if away_wins > home_wins else "BALANCED")

    return {
        'last_5': f"{home_wins}-{5-home_wins-away_wins}-{away_wins}",
        'dominance': dominance,
        'total_matches': len(h2h)
    }

def get_home_away_analysis(matches, home_team, away_team):
    """Análise 3: Casa vs Fora."""
    home_games = [m for m in matches if m['home_team'] == home_team]
    away_games = [m for m in matches if m['away_team'] == away_team]

    away_games_visiting = [m for m in matches if m['away_team'] == away_team]

    def calc_stats(games, is_home=True):
        if not games:
            return {'win_pct': 0, 'goals_for': 0, 'goals_against': 0, 'cs_pct': 0}

        wins = sum(1 for m in games if
                   (is_home and m['home_goals'] > m['away_goals']) or
                   (not is_home and m['away_goals'] > m['home_goals']))

        goals_for = sum(m['home_goals'] if is_home else m['away_goals'] for m in games)
        goals_against = sum(m['away_goals'] if is_home else m['home_goals'] for m in games)

        cs = sum(1 for m in games if
                (is_home and m['away_goals'] == 0) or
                (not is_home and m['home_goals'] == 0))

        return {
            'win_pct': round(100 * wins / len(games), 0),
            'goals_for': round(goals_for / len(games), 2),
            'goals_against': round(goals_against / len(games), 2),
            'cs_pct': round(100 * cs / len(games), 0)
        }

    return {
        'home': calc_stats(home_games, is_home=True),
        'away': calc_stats(away_games_visiting, is_home=False)
    }

def get_momentum_analysis(hist_rows, clube):
    """Análise 4: Momentum (últimas 3 vs 4-5)."""
    recent3 = get_team_performance(hist_rows, clube, set(range(19, 22)))  # Rodadas 19-21
    previous = get_team_performance(hist_rows, clube, set(range(16, 19)))  # Rodadas 16-18

    if recent3['jogos'] < 2 or previous['jogos'] < 2:
        return None

    momentum = "UP" if recent3['pontos_media'] > previous['pontos_media'] else ("DOWN" if recent3['pontos_media'] < previous['pontos_media'] else "STABLE")

    return {
        'recent_avg': round(recent3['pontos_media'], 1),
        'previous_avg': round(previous['pontos_media'], 1),
        'direction': momentum,
        'delta': round(recent3['pontos_media'] - previous['pontos_media'], 1)
    }

def get_offense_defense(matches, team, is_home=None):
    """Análise 5: Defesa/Ataque."""
    if is_home is True:
        games = [m for m in matches if m['home_team'] == team]
        goals_for = [m['home_goals'] for m in games]
        goals_against = [m['away_goals'] for m in games]
    elif is_home is False:
        games = [m for m in matches if m['away_team'] == team]
        goals_for = [m['away_goals'] for m in games]
        goals_against = [m['home_goals'] for m in games]
    else:
        games = [m for m in matches if m['home_team'] == team or m['away_team'] == team]
        goals_for = [m['home_goals'] if m['home_team'] == team else m['away_goals'] for m in games]
        goals_against = [m['away_goals'] if m['home_team'] == team else m['home_goals'] for m in games]

    if not games:
        return None

    cs = sum(1 for g in goals_against if g == 0)

    return {
        'gf_avg': round(sum(goals_for) / len(goals_for), 2),
        'ga_avg': round(sum(goals_against) / len(goals_against), 2),
        'cs_pct': round(100 * cs / len(games), 0),
        'games': len(games)
    }

def get_context_analysis(matches, team):
    """Análise 6: Contexto/Pressão (posição na tabela)."""
    return {
        'note': 'Posição na tabela não disponível. Implementar com dados de standings.'
    }

def get_forecast_analysis(ratings, home_adv, home_team, away_team):
    """Análise 7: Forecast de placares (top 3 mais prováveis via Poisson)."""
    if home_team not in ratings or away_team not in ratings:
        return None

    h = ratings[home_team]
    a = ratings[away_team]
    lam_home = math.exp(h["attack"] - a["defense"] + home_adv)
    lam_away = math.exp(a["attack"] - h["defense"])

    # Calcular probabilidades de placares
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
    total_prob = sum(s['prob'] for s in top3)

    return {
        'top_3': [f"{s['score']} ({s['prob']:.0f}%)" for s in top3],
        'combined_prob': round(total_prob, 1)
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)

    # Carregar dados
    hist_rows = list(csv.DictReader(open(repo / "data" / "cartola_historico_2026_completo.csv", encoding="utf-8")))
    matches = list(csv.DictReader(open(repo / "data" / "matches_2012_2026.csv", encoding="utf-8")))
    matches = [m for m in matches if m['season'] == '2026']

    # Converter gols para int
    for m in matches:
        m['home_goals'] = int(m['home_goals']) if m['home_goals'] else 0
        m['away_goals'] = int(m['away_goals']) if m['away_goals'] else 0

    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"
    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    # Próximos jogos
    matches_data = [
        {"home": "Flamengo", "away": "Chapecoense"},
        {"home": "Palmeiras", "away": "Corinthians"},
        {"home": "Bahia", "away": "Fluminense"},
        {"home": "Gremio", "away": "Coritiba"},
        {"home": "Atletico-PR", "away": "Botafogo"},
        {"home": "Santos", "away": "Vitoria"},
        {"home": "Vasco", "away": "Atletico-MG"},
        {"home": "Cruzeiro", "away": "Mirassol"},
        {"home": "Bragantino", "away": "Internacional"},
        {"home": "Remo", "away": "Sao Paulo"},
    ]

    print("\n" + "="*80)
    print("GERANDO ANALISES COMPLETAS PARA RODADA 22")
    print("="*80 + "\n")

    for match in matches_data:
        home, away = match['home'], match['away']
        print(f"\n{home:20} vs {away:20}")
        print("-" * 60)

        form_h = get_form_analysis(hist_rows, home)
        form_a = get_form_analysis(hist_rows, away)
        h2h = get_h2h_analysis(matches, home, away)
        ha = get_home_away_analysis(matches, home, away)
        mom_h = get_momentum_analysis(hist_rows, home)
        mom_a = get_momentum_analysis(hist_rows, away)
        off_def_h = get_offense_defense(matches, home)
        off_def_a = get_offense_defense(matches, away)
        forecast = get_forecast_analysis(ratings, home_adv, home, away)

        print(f"  Forma: {form_h['classification'] if form_h else 'N/A'} vs {form_a['classification'] if form_a else 'N/A'}")
        print(f"  H2H: {h2h['dominance'] if h2h else 'N/A'}")
        print(f"  Casa/Fora: {ha['home']['win_pct']:.0f}% vs {ha['away']['win_pct']:.0f}%")
        print(f"  Momentum: {mom_h['direction'] if mom_h else 'N/A'} vs {mom_a['direction'] if mom_a else 'N/A'}")
        print(f"  Ataque/Defesa: {off_def_h['gf_avg']:.2f}/{off_def_h['ga_avg']:.2f} vs {off_def_a['gf_avg']:.2f}/{off_def_a['ga_avg']:.2f}")
        if forecast:
            print(f"  Forecast: {forecast['top_3'][0]}, {forecast['top_3'][1]}, {forecast['top_3'][2]}")

if __name__ == "__main__":
    main()
