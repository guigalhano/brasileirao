#!/usr/bin/env python3
"""
parse_whoscored_stats.py

Extrai a tabela "Team xG" (aba xG > For, em Team Statistics) de um dump de
texto do WhoScored.com salvo em arquivo, e grava em CSV estruturado.

POR QUE ISSO EXISTE EM VEZ DE UM SCRAPER DE VERDADE
-----------------------------------------------------
WhoScored carrega essas tabelas via JS/AJAX e usa protecao anti-bot (Cloudflare
+ paginas montadas em runtime), entao um scraper simples com requests/urllib
geralmente NAO funciona -- ele recebe a pagina "casca" sem os dados. A forma
confiavel de atualizar isso hoje e manual:

  1. Abra a pagina "Team Statistics > Summary > xG > For" do Brasileirao no
     WhoScored.com.
  2. Selecione TODO o texto da pagina (Ctrl+A) e copie (Ctrl+C).
  3. Cole em um arquivo de texto, ex: whoscored_raw.txt.
  4. Rode: python3 parse_whoscored_stats.py whoscored_raw.txt

Se no futuro voce tiver acesso a API interna do WhoScored (alguns planos
WhoScored+ expoem isso) ou um servico de scraping que renderize JS (Selenium/
Playwright), este script pode ser adaptado para receber o HTML renderizado
em vez do texto colado -- a funcao parse_xg_table() e a parte reutilizavel.

Uso:
    python3 parse_whoscored_stats.py caminho/para/whoscored_raw.txt [--out data/whoscored_xg_2026.csv]
"""

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

# Mesmo mapeamento usado no restante do pipeline (nomes canonicos do projeto).
WS_TO_CANON = {
    "Vasco da Gama": "Vasco",
    "Athletico Paranaense": "Atletico-PR",
    "Internacional": "Internacional",
    "Fluminense": "Fluminense",
    "Bahia": "Bahia",
    "Red Bull Bragantino": "Bragantino",
    "Cruzeiro": "Cruzeiro",
    "Flamengo": "Flamengo",
    "Chapecoense AF": "Chapecoense",
    "Atletico MG": "Atletico-MG",
    "Gremio": "Gremio",
    "Sao Paulo": "Sao Paulo",
    "Palmeiras": "Palmeiras",
    "Santos FC": "Santos",
    "Mirassol": "Mirassol",
    "Remo": "Remo",
    "Vitoria": "Vitoria",
    "Botafogo RJ": "Botafogo",
    "Corinthians": "Corinthians",
    "Coritiba": "Coritiba",
}

# Linha da tabela de xG: "9. Chapecoense AF  14.84  13  -1.84  144  0.1  6.46"
# grupos: rank, time (nome pode ter espacos), xg, goals, xgdiff, shots, xg_per_shot, rating
XG_ROW_RE = re.compile(
    r"^\s*(\d{1,2})\.\s+([A-Za-zÀ-ÿ0-9 .'\-]+?)\s+"
    r"(-?\d+\.?\d*)\s+(-?\d+)\s+(-?\d+\.?\d*)\s+(\d+)\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s*$"
)


def parse_xg_table(text):
    """Acha o bloco de tabela que tem cabecalho 'Team xG Goals* xGDiff Shots xG/Shots Rating'
    e extrai as linhas dos 20 times."""
    lines = text.splitlines()
    rows = []
    known_teams = set(WS_TO_CANON.keys())
    for line in lines:
        m = XG_ROW_RE.match(line.strip())
        if not m:
            continue
        _, team_name, xg, goals, xgdiff, shots, xg_per_shot, rating = m.groups()
        team_name = team_name.strip()
        if team_name not in known_teams:
            continue
        rows.append({
            "team_whoscored": team_name,
            "team": WS_TO_CANON[team_name],
            "xg": float(xg),
            "goals": int(goals),
            "xg_diff": float(xgdiff),
            "shots": int(shots),
            "xg_per_shot": float(xg_per_shot),
            "rating": float(rating),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_txt", help="Arquivo de texto com o dump colado da pagina do WhoScored")
    ap.add_argument("--out", default="data/whoscored_xg_2026.csv")
    args = ap.parse_args()

    text = Path(args.input_txt).read_text(encoding="utf-8")
    rows = parse_xg_table(text)

    if len(rows) != 20:
        print(f"AVISO: encontrei {len(rows)} times, esperava 20. "
              f"Confira se o texto colado inclui a tabela 'Team xG' completa "
              f"(aba Summary > xG, view 'For').")
        if not rows:
            print("Nenhuma linha reconhecida -- nada foi salvo.")
            return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "team", "team_whoscored", "xg", "goals", "xg_diff", "shots", "xg_per_shot", "rating",
        ])
        writer.writeheader()
        for r in sorted(rows, key=lambda r: -r["xg"]):
            writer.writerow(r)

    print(f"OK: {len(rows)} times salvos em {out_path}")
    print(f"Data da extracao: {date.today().isoformat()} (adicione essa data ao nome do "
          f"arquivo ou a um changelog se for guardar historico de varias coletas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
