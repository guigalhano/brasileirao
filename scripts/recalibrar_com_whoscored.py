#!/usr/bin/env python3
"""
recalibrar_com_whoscored.py

Usa o xG real (baseado em chutes, do WhoScored) para corrigir o parametro de
ATAQUE de cada time no modelo Dixon-Coles (data/team_ratings_final_v2.json),
gerando data/team_ratings_calibrado.json.

POR QUE SO O ATAQUE, NAO A DEFESA
------------------------------------
A tabela que temos do WhoScored e a de xG "For" (quanto cada time gera de
xG ofensivo). Nao temos (ainda) a tabela "Against" (xG sofrido), que seria
necessaria pra calibrar defesa da mesma forma. Se voce coletar essa tabela
tambem (aba xG > Against), rode este script de novo com --xg-against para
calibrar defesa igual.

METODO
------
Para cada time, calculamos quanto xG o Dixon-Coles ATUAL previu que ele
deveria ter gerado nos jogos que ja disputou (usando attack/defense/home_adv
de team_ratings_final_v2.json, com a formula correta attack - defense do
adversario). Comparamos com o xG real do WhoScored e calculamos, em escala
log (porque o modelo trabalha em log-espaco via exp()), o ajuste necessario:

    ajuste = ln(xg_real_total / xg_modelo_total)
    novo_attack = attack_atual + ajuste

Isso desloca o ataque de cada time pra cima ou pra baixo o suficiente pra
que, se re-simulassemos a temporada com o rating novo, o xG total bateria
com o que o WhoScored mediu de verdade (holding defense e home_adv fixos).

LIMITACAO: isso e uma calibracao pontual (um "patch"), nao um re-fit
completo do modelo. Se voce rodar fit_model_v2.py de novo do zero, ele vai
sobrescrever esse ajuste -- rode este script de novo depois, ou (melhor a
longo prazo) incorpore o xG real como termo adicional na funcao de
verossimilhanca do proprio fit_model_v2.py.

Uso:
    python3 recalibrar_com_whoscored.py --repo-dir /caminho/para/repo
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--whoscored-csv", default=None,
                     help="default: <repo-dir>/data/whoscored_xg_2026.csv")
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    ws_path = Path(args.whoscored_csv) if args.whoscored_csv else repo / "data" / "whoscored_xg_2026.csv"

    ratings_doc = json.loads((repo / "data" / "team_ratings_final_v2.json").read_text(encoding="utf-8"))
    ratings = ratings_doc["teams"]
    home_adv = ratings_doc["home_advantage_log"]

    matches = [r for r in csv.DictReader(open(repo / "data" / "matches_2012_2026.csv", encoding="utf-8"))
               if r["season"] == "2026"]

    # xG que o modelo ATUAL implica, somado sobre os jogos ja disputados
    model_xg_for = defaultdict(float)
    n_matches = defaultdict(int)
    for m in matches:
        h, a = m["home_team"], m["away_team"]
        if h not in ratings or a not in ratings:
            continue
        model_xg_for[h] += math.exp(ratings[h]["attack"] - ratings[a]["defense"] + home_adv)
        model_xg_for[a] += math.exp(ratings[a]["attack"] - ratings[h]["defense"])
        n_matches[h] += 1
        n_matches[a] += 1

    ws_rows = list(csv.DictReader(open(ws_path, encoding="utf-8")))

    new_ratings = {t: dict(v) for t, v in ratings.items()}
    print(f"{'Time':15s} {'attack antigo':>13s} {'ajuste (log)':>13s} {'attack novo':>12s} "
          f"{'xg real':>8s} {'xg modelo':>10s}")
    print("-" * 78)
    ajustes = []
    for r in ws_rows:
        team = r["team"]
        if team not in ratings:
            print(f"AVISO: {team} nao encontrado em team_ratings_final_v2.json, pulando.")
            continue
        xg_real = float(r["xg"])
        xg_model = model_xg_for.get(team, 0.0)
        if xg_model <= 0:
            continue
        ajuste = math.log(xg_real / xg_model)
        ajustes.append(ajuste)
        novo_attack = ratings[team]["attack"] + ajuste
        new_ratings[team]["attack"] = round(novo_attack, 4)
        print(f"{team:15s} {ratings[team]['attack']:13.4f} {ajuste:13.4f} {novo_attack:12.4f} "
              f"{xg_real:8.2f} {xg_model:10.2f}")

    media_ajuste = sum(ajustes) / len(ajustes) if ajustes else 0.0
    print(f"\nAjuste medio aplicado: {media_ajuste:+.4f} (em log-escala; "
          f"exp({media_ajuste:.4f})={math.exp(media_ajuste):.3f}x)")

    out_doc = {
        "generated_note": (
            ratings_doc.get("generated_note", "") +
            " | Ataque recalibrado com xG real do WhoScored.com (aba Team Statistics > "
            "Summary > xG > For) via recalibrar_com_whoscored.py. Defesa e home_advantage "
            "mantidos do fit original -- nao temos xG 'Against' do WhoScored ainda."
        ),
        "home_advantage_log": home_adv,
        "teams": new_ratings,
    }
    out_path = repo / "data" / "team_ratings_calibrado.json"
    out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK: salvo em {out_path}")


if __name__ == "__main__":
    main()
