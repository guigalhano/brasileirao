#!/usr/bin/env python3
"""
Adiciona análises aos dados dos próximos jogos (DATA array) no index.html.
"""

import json
import re

# Análises para cada jogo
ANALYSIS = {
    "Flamengo|Chapecoense": "Forte favorito. Flamengo com 81.2% de chance de vitória. xG significativamente superior (2.99 vs 0.80). Aposta mais segura da rodada.",
    "Palmeiras|Corinthians": "Confronto clássico. Palmeiras tem leve favoritismo (50.7%). Empate com 30.7% de chance. Jogo equilibrado no geral.",
    "Bahia|Fluminense": "Duelo equilibrado (45.3% Bahia). Fluminense com 31.7% de chance de surpreender. xG similar (1.77 vs 1.45). Incerteza moderada.",
    "Gremio|Coritiba": "Casa com 48.9% de vantagem. Equilíbrio relativo, com 25% de chance de empate. Visitante tem 26.2% de chance.",
    "Atletico-PR|Botafogo": "Segundo jogo mais previsível (68.7% Atlético-PR). xG favorável para o mandante (2.38 vs 0.97). Visitante enfrenta dificuldade.",
    "Santos|Vitoria": "Levemente favorável ao Santos (52.8%). Vitória com 23.7% de chance. Jogo com incerteza moderada-alta.",
    "Vasco|Atletico-MG": "Vasco tem 58% de chance em casa. Jogo bem definido mas com margem de erro. xG: 2.13 vs 1.23.",
    "Cruzeiro|Mirassol": "Cruzeiro favorito com 56.7%. Mirassol com 20.1% de derrota esperada. Confronto moderadamente vantajoso para casa.",
    "Bragantino|Internacional": "Equilíbrio relativo (54.1% Bragantino). Internacional com 24.1% de chance. Jogo com bom potencial para apostas.",
    "Remo|Sao Paulo": "JOGO MAIS EQUILIBRADO da rodada (38% vs 36.9% vs 25%). Praticamente uma moeda ao ar. Alto grau de incerteza.",
}

matches = [
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

# Adicionar análises aos matches
for m in matches:
    key = f"{m['home']}|{m['away']}"
    m['analysis'] = ANALYSIS.get(key, "Análise disponível em breve.")

# Gerar JSON
json_str = json.dumps(matches)
print(json_str)
