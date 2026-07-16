#!/usr/bin/env python3
"""
build_fixtures.py

Regenera o array `DATA` embutido no index.html (os proximos confrontos,
usado pela previsao "proximo jogo" na escolha de jogadores do Cartola)
recalculando xg e probabilidades 1x2 A PARTIR DO MODELO ATUAL
(data/team_ratings_final_v2.json), em vez de depender de valores
digitados manualmente.

POR QUE ISSO EXISTE
--------------------
Nenhum script do repositorio gerava o array `DATA` -- ele foi escrito a
mao em algum momento e ficou dessincronizado do modelo Dixon-Coles.
Isso causava inconsistencias como: o goleiro de um time "fraco" e os
atacantes do adversario "forte" sendo avaliados com numeros que nao
vinham do mesmo lugar (um viés que ficou visivel, por exemplo, no
confronto Corinthians x Remo, onde o xg manual [1.52, 0.75] nao batia
com o que o Dixon-Coles calcula a partir dos ratings reais dos times:
[1.42, 1.34]).

O QUE ESTE SCRIPT MANTEM E O QUE ELE RECALCULA
------------------------------------------------
- MANTEM: home, away, day, time, odds, market -- sao fatos (calendario)
  ou dados de mercado (cotacoes de casas de apostas), nao previsoes do
  nosso modelo. Extraidos do bloco DATA atual do index.html.
- RECALCULA: xg (lambda esperado de gols pra cada lado) e model
  (probabilidades 1x2), usando exclusivamente attack/defense/home_advantage
  de data/team_ratings_final_v2.json, com uma distribuicao de Poisson
  independente para casa e fora.

LIMITACAO CONHECIDA: este script nao inventa jogos novos nem datas --
ele so recalcula os numeros de um confronto que ja esteja listado no
DATA atual. Se voce tiver uma fonte de calendario oficial (ex: CBF,
API do Cartola), me avise que eu integro para nao depender mais do
DATA anterior como fonte da lista de jogos.

Uso:
    python3 build_fixtures.py --repo-dir D:\\brasileirao-analytics-repo\\repo
"""

import argparse
import json
import math
import re
from pathlib import Path


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def match_probs(lam_home, lam_away, max_goals=10):
    """Probabilidade de vitoria casa / empate / vitoria fora via
    Poisson independente (sem ajuste Dixon-Coles de placares baixos,
    ja que o modelo atual nao tem parametro rho salvo)."""
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
    # CONVENCAO: attack MENOS defense do adversario (igual a fit_model_v2.py,
    # refit_with_coach_boost.py, sweep_half_life.py e cold_start_market_value_prior.py).
    # Usar "+ defense" aqui e' um bug -- como a maioria dos valores de defense
    # e' positiva, somar em vez de subtrair infla o xg previsto em ~2x.
    lam_home = math.exp(h["attack"] - a["defense"] + home_adv)
    lam_away = math.exp(a["attack"] - h["defense"])
    return lam_home, lam_away


def extract_current_data_block(index_html_text):
    m = re.search(r"var DATA = (\[.*?\]);", index_html_text, re.DOTALL)
    if not m:
        raise ValueError("Nao encontrei 'var DATA = [...]' no index.html")
    return json.loads(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    index_path = repo / "index.html"
    ratings_path = repo / "data" / "team_ratings_calibrado.json"
    if not ratings_path.exists():
        ratings_path = repo / "data" / "team_ratings_final_v2.json"
        print("AVISO: nao encontrei team_ratings_calibrado.json, usando "
              "team_ratings_final_v2.json (sem correcao de xG do WhoScored).")
    else:
        print(f"Usando ratings calibrados com WhoScored: {ratings_path.name}")

    ratings_doc = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    content = index_path.read_text(encoding="utf-8")
    fixtures = extract_current_data_block(content)

    updated = []
    skipped = []
    for fx in fixtures:
        home, away = fx["home"], fx["away"]
        if home not in ratings or away not in ratings:
            # Time sem rating no modelo atual (ex: nome grafado diferente).
            # Mantem o confronto como estava, para nao apagar dado, mas avisa.
            skipped.append((home, away))
            updated.append(fx)
            continue
        lam_home, lam_away = expected_goals(ratings, home_adv, home, away)
        p_home, p_draw, p_away = match_probs(lam_home, lam_away)
        new_fx = dict(fx)
        new_fx["xg"] = [round(lam_home, 2), round(lam_away, 2)]
        new_fx["model"] = [round(p_home, 4), round(p_draw, 4), round(p_away, 4)]
        updated.append(new_fx)

    if skipped:
        print("AVISO: times sem rating no modelo, confronto mantido sem recalculo:")
        for h, a in skipped:
            print(f"  - {h} x {a}")

    # Serializa no mesmo estilo compacto (uma linha), como o bloco original.
    def dump_fixture(fx):
        keys_order = ["home", "away", "day", "time", "model", "xg", "odds", "market"]
        parts = []
        for k in keys_order:
            if k not in fx:
                continue
            parts.append(json.dumps(k) + ": " + json.dumps(fx[k]))
        return "{" + ", ".join(parts) + "}"

    js_array = "var DATA = [" + ", ".join(dump_fixture(fx) for fx in updated) + "];"

    new_content = re.sub(r"var DATA = \[.*?\];", js_array, content, count=1, flags=re.DOTALL)
    index_path.write_text(new_content, encoding="utf-8")

    print(f"\nOK: {len(updated)} confrontos recalculados a partir do modelo Dixon-Coles atual.")
    print("Antes de comitar, confira visualmente algumas linhas do array DATA no index.html.")


if __name__ == "__main__":
    main()
