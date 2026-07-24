"""
Busca odds reais de mercado (The Odds API) pros confrontos ja listados em
`var DATA` no index.html (Proximos Jogos) e preenche odds/mercado/horario.

NAO inventa jogos novos -- so preenche odds pros confrontos que ja estao no
array DATA (mesma limitacao do build_fixtures.py). Pra trocar os confrontos
em si (ex: nova rodada), edite `var DATA` primeiro (times/dia) e rode
build_fixtures.py, depois este script pra trazer odds reais.

IMPORTANTE -- CHAVE DE API: nunca hardcode a chave aqui nem em nenhum
arquivo commitado. Passe via variavel de ambiente:

    set ODDS_API_KEY=sua_chave_aqui        (Windows cmd)
    $env:ODDS_API_KEY="sua_chave_aqui"      (PowerShell)
    export ODDS_API_KEY=sua_chave_aqui      (bash)

A The Odds API tem cota gratuita limitada (checar https://the-odds-api.com/) --
cada chamada deste script consome 1 requisicao.

Uso:
    python scripts/atualizar_odds_mercado.py --repo-dir D:\\brasileirao
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SPORT_KEY = "soccer_brazil_campeonato"
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]

# Nomes como aparecem na The Odds API -> nomes canonicos usados no projeto
NAME_MAP = {
    "Atletico Paranaense": "Atletico-PR", "Internacional": "Internacional", "Santos": "Santos",
    "Chapecoense": "Chapecoense", "Vasco da Gama": "Vasco", "Mirassol": "Mirassol", "Bahia": "Bahia",
    "Corinthians": "Corinthians", "Cruzeiro": "Cruzeiro", "Botafogo": "Botafogo",
    "Bragantino-SP": "Bragantino", "Coritiba": "Coritiba", "Flamengo": "Flamengo", "Sao Paulo": "Sao Paulo",
    "Grêmio": "Gremio", "Palmeiras": "Palmeiras", "Atletico Mineiro": "Atletico-MG",
    "Remo": "Remo", "Vitoria": "Vitoria", "Fluminense": "Fluminense",
}


def fetch_odds(api_key):
    url = (f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
           f"?regions=uk,eu&markets=h2h&apiKey={api_key}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining")
    if remaining:
        print(f"Requisicoes restantes na cota da API: {remaining}")
    return resp.json()


def process_event(ev):
    home, away = ev["home_team"], ev["away_team"]
    prices = {"H": [], "D": [], "A": []}
    for bk in ev["bookmakers"]:
        h2h = next((m for m in bk["markets"] if m["key"] == "h2h"), None)
        if not h2h:
            continue
        outcome = {}
        for o in h2h["outcomes"]:
            if o["name"] == home:
                outcome["H"] = o["price"]
            elif o["name"] == away:
                outcome["A"] = o["price"]
            elif o["name"].lower() == "draw":
                outcome["D"] = o["price"]
        if len(outcome) == 3:
            for k, v in outcome.items():
                prices[k].append(v)
    if not prices["H"]:
        return None
    avg = {k: sum(v) / len(v) for k, v in prices.items()}
    return {"home": home, "away": away, "commence_time": ev["commence_time"], "avg": avg, "n_books": len(prices["H"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    args = ap.parse_args()
    repo = Path(args.repo_dir)

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERRO: defina a variavel de ambiente ODDS_API_KEY antes de rodar (veja o topo deste arquivo).")
        sys.exit(1)

    raw = fetch_odds(api_key)
    events = [process_event(ev) for ev in raw]
    events = [e for e in events if e]
    print(f"{len(events)} confrontos com odds encontrados na API.")

    by_pair = {}
    for e in events:
        h = NAME_MAP.get(e["home"], e["home"])
        a = NAME_MAP.get(e["away"], e["away"])
        by_pair[(h, a)] = e

    index_path = repo / "index.html"
    content = index_path.read_text(encoding="utf-8")
    m = re.search(r"var DATA = (\[.*?\]);", content, re.DOTALL)
    if not m:
        print("ERRO: nao encontrei 'var DATA = [...]' no index.html")
        sys.exit(1)
    fixtures = json.loads(m.group(1))

    updated = 0
    for fx in fixtures:
        key = (fx["home"], fx["away"])
        if key not in by_pair:
            print(f"  sem odds pra {key}")
            continue
        e = by_pair[key]
        avg = e["avg"]
        inv = {k: 1 / v for k, v in avg.items()}
        overround = sum(inv.values())
        fx["odds"] = [round(avg["H"], 3), round(avg["D"], 3), round(avg["A"], 3)]
        fx["market"] = [round(inv[k] / overround, 4) for k in ("H", "D", "A")]

        dt_utc = datetime.strptime(e["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_br = dt_utc - timedelta(hours=3)
        fx["day"] = DIAS[dt_br.weekday()] + " " + dt_br.strftime("%d/%m")
        fx["time"] = dt_br.strftime("%H:%M")
        updated += 1
        print(f"  atualizado {key}: odds={fx['odds']} {fx['day']} {fx['time']}")

    new_data_js = "var DATA = " + json.dumps(fixtures, ensure_ascii=False) + ";"
    new_content = re.sub(r"var DATA = \[.*?\];", lambda mo: new_data_js, content, count=1, flags=re.DOTALL)
    index_path.write_text(new_content, encoding="utf-8")
    print(f"\nOK: {updated}/{len(fixtures)} confrontos atualizados com odds reais.")


if __name__ == "__main__":
    main()
