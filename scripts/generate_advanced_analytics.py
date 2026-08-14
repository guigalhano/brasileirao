#!/usr/bin/env python3
"""
FEATURE #6 + #8 + #11 + #12: Forecast expandido, Value Betting, Rankings, Matchup

Implementa:
  [6] Forecast expandido (top 10 + >2.5/<2.5)
  [8] Value betting automático
  [11] Rankings de ataque/defesa/criatividade
  [12] Matchup específico (força vs fraqueza)
"""

import argparse
import json
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.fixtures import load_fixtures
from lib.index_data import read_data, write_data
from lib.teams import check_ratings_cover_canonical

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def generate_forecast_top10(ratings, home_adv, home_team, away_team):
    """[FEATURE #6] Forecast com top 10 placares + over/under"""
    if home_team not in ratings or away_team not in ratings:
        return None

    h = ratings[home_team]
    a = ratings[away_team]
    lam_home = math.exp(h["attack"] - a["defense"] + home_adv)
    lam_away = math.exp(a["attack"] - h["defense"])

    # Calcular todos os placares possíveis
    scorelines = []
    for i in range(8):
        for j in range(8):
            pi = poisson_pmf(i, lam_home)
            pj = poisson_pmf(j, lam_away)
            prob = pi * pj
            scorelines.append({
                'score': f"{i}-{j}",
                'prob': round(100 * prob, 1)
            })

    # Top 10
    top10 = sorted(scorelines, key=lambda x: x['prob'], reverse=True)[:10]

    # Over/Under
    over25 = sum(s['prob'] for s in scorelines if int(s['score'].split('-')[0]) + int(s['score'].split('-')[1]) > 2.5)
    over15 = sum(s['prob'] for s in scorelines if int(s['score'].split('-')[0]) + int(s['score'].split('-')[1]) > 1.5)
    btts = sum(s['prob'] for s in scorelines if int(s['score'].split('-')[0]) > 0 and int(s['score'].split('-')[1]) > 0)

    return {
        'top_10': [f"{s['score']} ({s['prob']:.1f}%)" for s in top10],
        'combined_top10': round(sum(s['prob'] for s in top10), 1),
        'over_2_5': round(over25, 1),
        'under_2_5': round(100 - over25, 1),
        'over_1_5': round(over15, 1),
        'btts': round(btts, 1),
        'xg': [round(lam_home, 2), round(lam_away, 2)]
    }

def calculate_team_stats(matches, team, is_attacking=True):
    """Calcula estatísticas de um time para rankings"""
    games = [m for m in matches if m['home_team'] == team or m['away_team'] == team]
    if not games:
        return None

    gols_marcados = sum(m['home_goals'] if m['home_team'] == team else m['away_goals'] for m in games)
    gols_sofridos = sum(m['away_goals'] if m['home_team'] == team else m['home_goals'] for m in games)
    clean_sheets = sum(1 for m in games if (m['home_team'] == team and m['away_goals'] == 0) or (m['away_team'] == team and m['home_goals'] == 0))

    return {
        'games': len(games),
        'goals_for': round(gols_marcados / len(games), 2),
        'goals_against': round(gols_sofridos / len(games), 2),
        'clean_sheets_pct': round(100 * clean_sheets / len(games), 0),
        'goal_diff': round((gols_marcados - gols_sofridos) / len(games), 2)
    }

def generate_rankings(matches, ratings):
    """[FEATURE #11] Rankings de ataque, defesa, criatividade"""
    teams = list(set(ratings.keys()))

    # Calcular stats
    team_stats = {}
    for team in teams:
        team_stats[team] = calculate_team_stats(matches, team)

    # Remover times sem dados
    team_stats = {t: s for t, s in team_stats.items() if s is not None}

    # Top 5 e Bottom 5 por métrica
    rankings = {
        'attack': {
            'top5': sorted([(t, s['goals_for']) for t, s in team_stats.items()], key=lambda x: x[1], reverse=True)[:5],
            'bottom5': sorted([(t, s['goals_for']) for t, s in team_stats.items()], key=lambda x: x[1])[:5]
        },
        'defense': {
            'top5': sorted([(t, s['goals_against']) for t, s in team_stats.items()], key=lambda x: x[1])[:5],
            'bottom5': sorted([(t, s['goals_against']) for t, s in team_stats.items()], key=lambda x: x[1], reverse=True)[:5]
        },
        'clean_sheets': {
            'top5': sorted([(t, s['clean_sheets_pct']) for t, s in team_stats.items()], key=lambda x: x[1], reverse=True)[:5],
            'bottom5': sorted([(t, s['clean_sheets_pct']) for t, s in team_stats.items()], key=lambda x: x[1])[:5]
        }
    }

    return rankings, team_stats

def generate_matchup_analysis(team_stats, home_team, away_team):
    """[FEATURE #12] Análise de matchup (força vs fraqueza)"""
    h_att = team_stats.get(home_team, {}).get('goals_for', 0)
    a_def = team_stats.get(away_team, {}).get('goals_against', 0)
    a_att = team_stats.get(away_team, {}).get('goals_for', 0)
    h_def = team_stats.get(home_team, {}).get('goals_against', 0)

    avg_att = 1.5  # Média de gols/jogo no Brasileirão
    avg_def = 1.5

    # Multiplicadores
    home_mult = (h_att / avg_att) * (1 - a_def / (2 * avg_def))
    away_mult = (a_att / avg_att) * (1 - h_def / (2 * avg_def))

    # Qualidade do matchup
    if h_att > avg_att and a_def > avg_def:
        h_matchup = "Ataque forte vs Defesa fraca"
        h_advantage = "ALTA"
    elif h_att < avg_att and a_def < avg_def:
        h_matchup = "Ataque fraco vs Defesa forte"
        h_advantage = "BAIXA"
    else:
        h_matchup = "Matchup equilibrado"
        h_advantage = "MEDIA"

    return {
        'home_matchup': h_matchup,
        'away_matchup': f"Visitante: {['Desfavoravel', 'Equilibrado', 'Favoravel'][['ALTA', 'MEDIA', 'BAIXA'].index(h_advantage)]}",
        'home_advantage': h_advantage,
        'home_multiplier': round(home_mult, 2),
        'away_multiplier': round(away_mult, 2)
    }

def generate_value_betting(model_probs, market_data=None):
    """[FEATURE #8] Value betting - edge automático"""
    if not market_data:
        return None

    # Para os 10 jogos, precisamos de odds reais
    # Por enquanto, retorna template
    edges = []
    for i, (model_val, market_val) in enumerate(zip(model_probs, [market_data] * 3)):
        if market_val:
            edge = (model_val - market_val) * 100
            if abs(edge) > 5:  # Edge significativo
                edges.append({
                    'type': ['CASA', 'EMPATE', 'FORA'][i],
                    'edge_pp': round(edge, 1),
                    'alert': 'STRONG' if abs(edge) > 10 else 'WEAK'
                })

    return edges if edges else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parent.parent),
                    help="raiz do repo (padrao: deduzida deste arquivo)")
    args = ap.parse_args()
    repo = Path(args.repo_dir).resolve()

    # Carregar dados
    matches = list(csv.DictReader(open(repo / "data" / "matches_2012_2026.csv", encoding="utf-8")))
    matches_2026 = [m for m in matches if m['season'] == '2026']

    for m in matches_2026:
        m['home_goals'] = int(m['home_goals']) if m['home_goals'] else 0
        m['away_goals'] = int(m['away_goals']) if m['away_goals'] else 0

    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"
    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    check_ratings_cover_canonical(ratings)

    # Gerar rankings (usado por todos)
    print("Gerando rankings...")
    rankings, team_stats = generate_rankings(matches_2026, ratings)

    # Confrontos: fonte unica em data/proximos_jogos.json.
    # Antes esta lista era hardcoded aqui e ficou congelada numa rodada antiga,
    # entao a aba de analises do site descrevia jogos que nao aconteceriam --
    # e como o arquivo era regravado, o timestamp parecia sempre atual.
    rodada, fixtures, meta = load_fixtures(repo / "data" / "proximos_jogos.json")
    print(f"Rodada {rodada} ({meta['data_inicio']} - {meta['data_fim']}), "
          f"{len(fixtures)} jogos")

    analytics = {
        'rodada': rodada,
        'rankings': rankings,
        'matches': []
    }

    print("Gerando analytics para cada jogo...")
    for match in fixtures:
        home, away = match['home'], match['away']

        # #6 - Forecast expandido
        forecast = generate_forecast_top10(ratings, home_adv, home, away)

        # #12 - Matchup analysis
        matchup = generate_matchup_analysis(team_stats, home, away)

        # #8 - Value betting (template por enquanto)
        if forecast:
            value_betting = generate_value_betting(forecast['xg'], None)
        else:
            value_betting = None

        print(f"\n{home:20} vs {away:20}")
        if forecast:
            print(f"  Forecast top 3: {forecast['top_10'][0]} | {forecast['top_10'][1]} | {forecast['top_10'][2]}")
            print(f"  Over 2.5: {forecast['over_2_5']}% | BTTS: {forecast['btts']}%")
        if matchup:
            print(f"  Matchup: {matchup['home_matchup']} ({matchup['home_advantage']})")

        analytics['matches'].append({
            'home': home,
            'away': away,
            'forecast': forecast,
            'matchup': matchup,
            'value_betting': value_betting
        })

    # Salvar o JSON de analytics
    with open(repo / "data" / "analytics_advanced.json", "w", encoding="utf-8") as f:
        json.dump(analytics, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] analytics_advanced.json: {len(analytics['matches'])} jogos "
          f"da rodada {rodada}")

    # Injetar no DATA do index.html -- e o que faz a aba de analises aparecer.
    # O front so cria o botao "+ VER ANALISES COMPLETAS" quando f.analysis_grid
    # existe; sem esta etapa o JSON acima fica orfao e a aba nao renderiza.
    index_path = repo / "index.html"
    por_confronto = {f"{m['home']}|{m['away']}": m for m in analytics['matches']}
    atualizados = []
    for jogo in read_data(index_path):
        a = por_confronto.get(f"{jogo['home']}|{jogo['away']}")
        if not a:
            atualizados.append(jogo)
            continue
        mt, fc = a['matchup'], a['forecast']
        jogo['analysis_grid'] = {
            'h2h': f"{a['home']} x {a['away']} - rodada {rodada}",
            'form': f"Ataque casa: {mt['home_multiplier']}x | visitante: {mt['away_multiplier']}x",
            'home_away': f"Mando de campo: {mt['home_advantage']}",
            'defense': mt['home_matchup'],
            'clean_sheets': f"Ambos marcam: {fc['btts']}%" if fc else "-",
            'forecast': " | ".join(fc['top_10'][:3]) if fc else "-",
        }
        if fc:
            jogo['analysis'] = (
                f"Placar mais provavel {fc['top_10'][0]}. "
                f"xG {fc['xg'][0]:.2f}-{fc['xg'][1]:.2f}. "
                f"Over 2.5: {fc['over_2_5']}% | Ambos marcam: {fc['btts']}%. "
                f"{mt['home_matchup']} ({mt['home_advantage']})."
            )
        jogo['forecast'] = fc
        jogo['matchup'] = mt
        jogo['value_betting'] = a['value_betting']
        atualizados.append(jogo)

    write_data(index_path, atualizados, merge=True)
    com_analise = sum(1 for j in atualizados if j.get('analysis_grid'))
    print(f"[OK] index.html: {com_analise}/{len(atualizados)} jogos com analise")

if __name__ == "__main__":
    main()
