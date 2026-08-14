#!/usr/bin/env python3
"""
Ingere resultados novos do football-data.co.uk em data/matches_2012_2026.csv.

POR QUE ISSO EXISTE
-------------------
Ate a rodada 23 este CSV era upload manual, e ninguem percebia quando ficava
para tras. Na auditoria ele estava parado em 26/07 (rodada 19 completa)
enquanto o site publicava previsoes da rodada 23: todos os ratings, xG e
rankings estavam cegos para 4 rodadas de resultados reais. O site nao dava
nenhum sinal disso -- e o que verificar_integridade.py agora bloqueia.

O CSV do football-data.co.uk traz odds de fechamento (AvgC*), que sao a
entrada do modelo Elo-Odds. Onde a linha nao tem odds, os campos ficam
vazios (a partida entra pelo placar).

Uso:
    python scripts/ingerir_resultados.py                 # aplica
    python scripts/ingerir_resultados.py --dry-run       # so mostra
"""
import argparse
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.teams import canonical, UnknownTeamError

FONTE = "https://www.football-data.co.uk/new/BRA.csv"
REPO = Path(__file__).resolve().parent.parent
DESTINO = REPO / "data" / "matches_2012_2026.csv"
COLUNAS = ["date", "season", "home_team", "away_team", "home_goals", "away_goals",
           "avg_odds_home", "avg_odds_draw", "avg_odds_away"]


def _data_iso(txt):
    """A fonte usa DD/MM/YYYY (e as vezes DD/MM/YY)."""
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(txt.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Data em formato inesperado: {txt!r}")


def _num(v):
    v = (v or "").strip()
    return v if v and v.upper() not in {"NA", "N/A"} else ""


def baixar():
    r = requests.get(FONTE, timeout=60)
    r.raise_for_status()
    texto = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(texto)))


def normalizar(linhas, season):
    """Converte para o schema local. Placar vazio = jogo ainda nao disputado.

    Filtra a temporada ANTES de canonicalizar: o arquivo da fonte cobre
    2012-2026 e traz times que ja estiveram na Serie A mas nao estao mais
    (Portuguesa, Figueirense, Ponte Preta, Atletico GO...). Canonicalizar
    tudo faria a ingestao falhar por causa de linhas de 2014.
    """
    saida, ignoradas = [], []
    for ln in linhas:
        if ln.get("Season", "").strip() != season:
            continue
        if not _num(ln.get("HG")) or not _num(ln.get("AG")):
            continue  # sem placar: partida futura
        try:
            home = canonical(ln["Home"], source="football-data.co.uk")
            away = canonical(ln["Away"], source="football-data.co.uk")
        except UnknownTeamError as e:
            ignoradas.append(str(e))
            continue
        saida.append({
            "date": _data_iso(ln["Date"]),
            "season": ln["Season"].strip(),
            "home_team": home,
            "away_team": away,
            "home_goals": _num(ln["HG"]),
            "away_goals": _num(ln["AG"]),
            "avg_odds_home": _num(ln.get("AvgCH")),
            "avg_odds_draw": _num(ln.get("AvgCD")),
            "avg_odds_away": _num(ln.get("AvgCA")),
        })
    return saida, ignoradas


def chave(r):
    return (r["date"], r["home_team"], r["away_team"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--season", default="2026", help="temporada a ingerir")
    args = ap.parse_args()

    existentes = list(csv.DictReader(DESTINO.open(encoding="utf-8")))
    ja_tem = {chave(r) for r in existentes}
    print(f"Local: {len(existentes)} jogos "
          f"(2026: {sum(1 for r in existentes if r['season'] == '2026')})")

    print(f"Baixando {FONTE} ...")
    remotos, ignoradas = normalizar(baixar(), args.season)
    if ignoradas:
        print(f"[ERRO] {len(ignoradas)} linha(s) da temporada {args.season} "
              f"com time desconhecido:")
        for m in ignoradas[:5]:
            print(f"   {m}")
        return 1

    novos = [r for r in remotos if chave(r) not in ja_tem]
    novos.sort(key=lambda r: (r["date"], r["home_team"]))

    if not novos:
        print("Nada novo -- o CSV local ja esta em dia.")
        return 0

    print(f"\n{len(novos)} jogo(s) novo(s) da temporada {args.season}:\n")
    for r in novos:
        odds = (f"{r['avg_odds_home']}/{r['avg_odds_draw']}/{r['avg_odds_away']}"
                if r["avg_odds_home"] else "sem odds")
        print(f"  {r['date']}  {r['home_team']:14} {r['home_goals']} x "
              f"{r['away_goals']}  {r['away_team']:14} [{odds}]")

    if args.dry_run:
        print("\n[DRY-RUN] Nada gravado.")
        return 0

    # Ordena SO por data, e o sort do Python e estavel: as linhas que ja
    # estavam no arquivo mantem a ordem relativa original e as novas caem no
    # fim do seu dia. Ordenar tambem por home_team reembaralharia as 5.5k
    # linhas historicas e produziria um diff de ~2000 linhas para 17 jogos
    # novos -- ruido que torna a revisao impossivel.
    combinado = existentes + novos
    combinado.sort(key=lambda r: r["date"])
    with DESTINO.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(combinado)

    print(f"\n[OK] {DESTINO.name}: {len(existentes)} -> {len(combinado)} jogos")
    print("[!] Os ratings ainda refletem os dados antigos. Reajuste o modelo:")
    print("    python scripts/fit_model_v2.py")
    print("    python scripts/refit_with_coach_boost.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
