#!/usr/bin/env python3
"""
recalibrar_com_whoscored.py

Usa o xG real (baseado em chutes, do WhoScored) para corrigir ATAQUE e
DEFESA de cada time no modelo Dixon-Coles (data/team_ratings_final_v2.json),
gerando data/team_ratings_calibrado.json.

MUDANCA (24/07/2026): normaliza por jogo, nao por total acumulado
--------------------------------------------------------------------
Versao anterior comparava xg_real_total contra xg_modelo_total (soma sobre
TODOS os jogos de matches_2012_2026.csv). Isso quebra se o WhoScored e o
matches_2012_2026.csv nao cobrirem exatamente o mesmo numero de jogos --
foi exatamente o que aconteceu quando adicionamos resultados novos ao CSV
sem re-coletar o WhoScored no mesmo instante: o "xg_modelo" cresceu (mais
jogos somados) enquanto "xg_real" ficou parado, gerando um ajuste de quase
-0.86 em log-escala (quase METADE do ataque de todo time) que nao refletia
recalibracao real nenhuma, so a defasagem entre os dois totais.

Agora comparamos TAXA POR JOGO (xg / numero de jogos) dos dois lados, cada
um usando o proprio numero de jogos (games do WhoScored, n_matches do
modelo) -- se os dois totais cobrirem o mesmo periodo isso da no mesmo
resultado de antes, mas fica protegido caso um dia fiquem dessincronizados
de novo.

AGORA TAMBEM CALIBRA DEFESA
----------------------------
Antes so tinhamos a tabela "For" do WhoScored. Com a tabela "Against"
(xG sofrido) tambem coletada, calibramos defesa do mesmo jeito (em log-
escala, mas com o sinal invertido -- ver METODO abaixo).

METODO
------
Para cada time, calculamos a taxa de xG que o Dixon-Coles ATUAL preve por
jogo (usando attack/defense/home_adv de team_ratings_final_v2.json, formula
attack - defense do adversario) e comparamos com a taxa real do WhoScored:

    ajuste_attack = ln( (xg_for_real/games_real) / (xg_for_modelo/n_jogos_modelo) )
    novo_attack = attack_atual + ajuste_attack

    ajuste_defense = ln( (xg_against_modelo/n_jogos_modelo) / (xg_against_real/games_real) )
    novo_defense = defense_atual + ajuste_defense

(o sinal de defesa e invertido porque no modelo lambda ~ exp(attack - defense
do adversario) -- aumentar "defense" DIMINUI o xG que o adversario marca, entao
se o time sofre mais gols do que o modelo preve, "defense" tem que DIMINUIR.)

LIMITACAO: isso e uma calibracao pontual (um "patch"), nao um re-fit
completo do modelo. Se voce rodar fit_model_v2.py de novo do zero, ele vai
sobrescrever esse ajuste -- rode este script de novo depois.

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
    model_xg_against = defaultdict(float)
    n_matches = defaultdict(int)
    for m in matches:
        h, a = m["home_team"], m["away_team"]
        if h not in ratings or a not in ratings:
            continue
        lam_home = math.exp(ratings[h]["attack"] - ratings[a]["defense"] + home_adv)
        lam_away = math.exp(ratings[a]["attack"] - ratings[h]["defense"])
        model_xg_for[h] += lam_home
        model_xg_for[a] += lam_away
        model_xg_against[h] += lam_away  # o que o adversario marcou CONTRA o time h
        model_xg_against[a] += lam_home
        n_matches[h] += 1
        n_matches[a] += 1

    ws_rows = list(csv.DictReader(open(ws_path, encoding="utf-8")))

    new_ratings = {t: dict(v) for t, v in ratings.items()}
    print(f"{'Time':15s} {'attack novo':>11s} {'defense novo':>13s} "
          f"{'xg_for r/m':>13s} {'xg_ag r/m':>13s}")
    print("-" * 70)
    ajustes_attack = []
    ajustes_defense = []
    for r in ws_rows:
        team = r["team"]
        if team not in ratings:
            print(f"AVISO: {team} nao encontrado em team_ratings_final_v2.json, pulando.")
            continue
        games_real = float(r.get("games") or 0)
        n_modelo = n_matches.get(team, 0)
        if games_real <= 0 or n_modelo <= 0:
            print(f"AVISO: {team} sem jogos suficientes (real={games_real}, modelo={n_modelo}), pulando.")
            continue
        if abs(games_real - n_modelo) > 1:
            print(f"AVISO: {team} tem {games_real:.0f} jogos no WhoScored mas {n_modelo} em "
                  f"matches_2012_2026.csv -- fontes desincronizadas, confira antes de confiar no ajuste.")

        xg_for_real = float(r["xg_for"])
        xg_for_modelo = model_xg_for.get(team, 0.0)
        rate_for_real = xg_for_real / games_real
        rate_for_modelo = xg_for_modelo / n_modelo
        ajuste_attack = math.log(rate_for_real / rate_for_modelo)
        novo_attack = ratings[team]["attack"] + ajuste_attack
        new_ratings[team]["attack"] = round(novo_attack, 4)
        ajustes_attack.append(ajuste_attack)

        novo_defense = ratings[team]["defense"]
        xg_against_str = r.get("xg_against")
        if xg_against_str:
            xg_against_real = float(xg_against_str)
            xg_against_modelo = model_xg_against.get(team, 0.0)
            rate_ag_real = xg_against_real / games_real
            rate_ag_modelo = xg_against_modelo / n_modelo
            ajuste_defense = math.log(rate_ag_modelo / rate_ag_real)
            novo_defense = ratings[team]["defense"] + ajuste_defense
            new_ratings[team]["defense"] = round(novo_defense, 4)
            ajustes_defense.append(ajuste_defense)

        print(f"{team:15s} {novo_attack:11.4f} {novo_defense:13.4f} "
              f"{rate_for_real:6.2f}/{rate_for_modelo:<6.2f} "
              f"{(rate_ag_real if xg_against_str else 0):6.2f}/{(rate_ag_modelo if xg_against_str else 0):<6.2f}")

    media_ajuste_a = sum(ajustes_attack) / len(ajustes_attack) if ajustes_attack else 0.0
    media_ajuste_d = sum(ajustes_defense) / len(ajustes_defense) if ajustes_defense else 0.0
    print(f"\nAjuste medio ATAQUE: {media_ajuste_a:+.4f} (exp={math.exp(media_ajuste_a):.3f}x)")
    if ajustes_defense:
        print(f"Ajuste medio DEFESA: {media_ajuste_d:+.4f} (exp={math.exp(media_ajuste_d):.3f}x)")

    out_doc = {
        "generated_note": (
            ratings_doc.get("generated_note", "") +
            " | Ataque e defesa recalibrados com xG real do WhoScored.com (Team Statistics > "
            "xG > For/Against) via recalibrar_com_whoscored.py, normalizado por jogo."
        ),
        "home_advantage_log": home_adv,
        "teams": new_ratings,
    }
    out_path = repo / "data" / "team_ratings_calibrado.json"
    out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK: salvo em {out_path}")


if __name__ == "__main__":
    main()
