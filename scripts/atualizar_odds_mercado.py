"""
Busca odds de mercado PRE-JOGO (The Odds API) para os confrontos da rodada e
preenche os campos odds/market do `var DATA` no index.html.

O QUE ESTE SCRIPT COBRE, E O QUE JA E AUTOMATICO SEM ELE
---------------------------------------------------------
Odds de FECHAMENTO dos jogos ja disputados chegam de graca pelo
scripts/ingerir_resultados.py, junto com o placar (colunas AvgC* do
football-data.co.uk): 216 de 216 jogos de 2026, sem chave nenhuma. E delas que
vivem o modelo Elo-Odds e a aba Value Betting.

O que o football-data NAO da e odds de jogo que ainda nao aconteceu -- o
BRA.csv so publica a partida depois de disputada (conferido: zero linhas sem
placar). E por isso que a coluna de "edge" da aba Proximos Jogos fica vazia e o
verificar_integridade.py avisa 10 vezes por rodada. Preencher isso exige uma
fonte de odds ao vivo, que e o que este script faz.

CHAVE DE API: nunca hardcode a chave aqui nem em nenhum arquivo commitado.
Passe via variavel de ambiente:

    export ODDS_API_KEY=sua_chave        (bash)
    $env:ODDS_API_KEY="sua_chave"        (PowerShell)

No GitHub Actions, cadastre como secret ODDS_API_KEY (Settings > Secrets and
variables > Actions). Sem a chave o script SAI COM CODIGO 0 e nao faz nada:
odds pre-jogo sao um enriquecimento, nao um requisito, e derrubar a atualizacao
inteira do site por falta de uma chave opcional seria desproporcional.

A The Odds API tem cota gratuita (500 requisicoes/mes no plano free); cada
execucao consome 1. A 3 execucoes por dia da ~90 por mes, bem dentro da cota.

DUAS CORRECOES (agosto/2026)
-----------------------------
1. Escrevia o `var DATA` com re.sub no array inteiro, por fora do
   lib/index_data.py. Esse modulo existe exatamente para impedir isso -- foi
   sobrescrita cega de DATA que matou a aba de analises no commit b69d041.
   Agora usa write_data(merge=True), que preserva analysis/analysis_grid/
   forecast/matchup e so encosta em odds/market.

2. Sobrescrevia day/time com o horario da The Odds API. Desde que os confrontos
   passaram a vir do /partidas do Cartola (atualizar_confrontos_cartola.py),
   quem manda no calendario e o Cartola; deixar duas fontes disputando o mesmo
   campo faz o dia do jogo oscilar a cada execucao. Este script nao toca mais
   em day/time.

Uso:
    python scripts/atualizar_odds_mercado.py --repo-dir .
    python scripts/atualizar_odds_mercado.py --repo-dir . --dry-run
"""
import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.index_data import read_data, write_data
from lib.teams import canonical_or_none

SPORT_KEY = "soccer_brazil_campeonato"
API_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"


def fetch_odds(api_key):
    resp = requests.get(API_URL, params={"regions": "uk,eu", "markets": "h2h",
                                         "apiKey": api_key}, timeout=30)
    resp.raise_for_status()
    restantes = resp.headers.get("x-requests-remaining")
    if restantes:
        print(f"Cota da API: {restantes} requisicoes restantes")
    return resp.json()


def media_do_evento(ev):
    """Media das cotas entre as casas que cotaram os tres resultados."""
    precos = {"H": [], "D": [], "A": []}
    for casa in ev.get("bookmakers", []):
        h2h = next((m for m in casa.get("markets", []) if m["key"] == "h2h"), None)
        if not h2h:
            continue
        cotas = {}
        for o in h2h["outcomes"]:
            if o["name"] == ev["home_team"]:
                cotas["H"] = o["price"]
            elif o["name"] == ev["away_team"]:
                cotas["A"] = o["price"]
            elif o["name"].lower() == "draw":
                cotas["D"] = o["price"]
        # So aproveita a casa que cotou os tres -- media de 1X2 incompleto
        # desalinha o overround e contamina a probabilidade implicita.
        if len(cotas) == 3:
            for k, v in cotas.items():
                precos[k].append(v)
    if not precos["H"]:
        return None
    return {k: sum(v) / len(v) for k, v in precos.items()}, len(precos["H"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo_dir).resolve()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ODDS_API_KEY nao definida -- pulando odds pre-jogo. "
              "A coluna de edge da aba Proximos Jogos fica vazia; o resto do "
              "site nao depende disso. Veja o cabecalho deste arquivo.")
        return 0

    try:
        bruto = fetch_odds(api_key)
    except Exception as e:
        print(f"ERRO ao buscar odds: {e}")
        return 1

    por_confronto = {}
    nao_mapeados = set()
    for ev in bruto:
        resultado = media_do_evento(ev)
        if not resultado:
            continue
        media, n_casas = resultado
        casa = canonical_or_none(ev["home_team"])
        fora = canonical_or_none(ev["away_team"])
        if casa is None or fora is None:
            nao_mapeados.add(f"{ev['home_team']} x {ev['away_team']}")
            continue
        por_confronto[(casa, fora)] = (media, n_casas)
    print(f"{len(por_confronto)} confronto(s) com odds na API")
    if nao_mapeados:
        # Nome novo da API e problema de mapeamento, nao motivo pra parar:
        # o jogo simplesmente fica sem edge. Mas tem que aparecer.
        print(f"[aviso] {len(nao_mapeados)} confronto(s) com nome fora do "
              f"lib/teams.py: {sorted(nao_mapeados)[:3]}")

    jogos = read_data(repo / "index.html")
    atualizados, sem_odds = [], []
    for jogo in jogos:
        chave = (jogo["home"], jogo["away"])
        if chave not in por_confronto:
            sem_odds.append(f"{jogo['home']} x {jogo['away']}")
            continue
        media, n_casas = por_confronto[chave]
        inv = {k: 1 / v for k, v in media.items()}
        overround = sum(inv.values())
        jogo["odds"] = [round(media[k], 3) for k in ("H", "D", "A")]
        # Probabilidade implicita ja sem a margem da casa (de-vig proporcional),
        # mesma convencao usada no resto do projeto.
        jogo["market"] = [round(inv[k] / overround, 4) for k in ("H", "D", "A")]
        atualizados.append(
            f"  {jogo['home']:14} x {jogo['away']:14} "
            f"{jogo['odds'][0]:>6.2f} {jogo['odds'][1]:>6.2f} {jogo['odds'][2]:>6.2f} "
            f"({n_casas} casas, margem {100 * (overround - 1):.1f}%)")

    for linha in atualizados:
        print(linha)
    if sem_odds:
        print(f"  sem odds ainda: {', '.join(sem_odds)}")

    if args.dry_run:
        print(f"\n[DRY-RUN] {len(atualizados)}/{len(jogos)} teriam odds. Nada gravado.")
        return 0
    if not atualizados:
        print("\nNenhum confronto da rodada tem odds publicadas ainda. "
              "index.html nao foi alterado.")
        return 0

    preservados = write_data(repo / "index.html", jogos, merge=True)
    print(f"\n[OK] {len(atualizados)}/{len(jogos)} confrontos com odds de mercado.")
    print(f"[MERGE] {preservados} jogo(s) mantiveram os campos de analise.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
