"""
Coleta o xG individual de todos os jogadores do Brasileirao no WhoScored e
guarda um snapshot datado pela rodada, montando um historico rodada a rodada.

POR QUE ISSO EXISTE
-------------------
Testamos (rodada 20) se o xG individual do WhoScored melhora a selecao do
Cartola. Cru, ele correlaciona (r~0.37 pra ATA+MEI), mas controlando pelos
gols reais a correlacao parcial fica NEGATIVA -- ou seja, o xG so re-codifica
gol, que a `media` ja captura. Conclusao: nao entra no criterio... POR ENQUANTO.

O unico teste que poderia mudar isso e um backtest WALK-FORWARD: o xG
acumulado ate a rodada N-1 preve os pontos da rodada N melhor que os gols ja
feitos ate N-1? Pra isso precisamos do xG COMO ESTAVA em cada rodada passada
-- e o WhoScored so da a foto cumulativa atual. Entao a unica forma de ter
esse historico e salvar um snapshot a cada rodada, daqui pra frente. Este
script faz isso.

RODAR LOCALMENTE (nao no GitHub Actions)
----------------------------------------
O WhoScored bloqueia IPs de datacenter (o Actions cairia na protecao anti-bot,
HTTP 406 / pagina "verify"). Da sua maquina (IP residencial), com os
cabeçalhos certos (User-Agent de navegador + X-Requested-With + Referer),
a chamada passa. Por isso este script roda local, como o coletar_valores_jogadores.py.

QUANDO RODAR: depois de cada rodada terminar (com o mercado do Cartola ja
aberto pra proxima). O script detecta a rodada encerrada sozinho via a API do
Cartola (rodada_atual - 1), ou use --rodada N pra forcar.

Uso:
    python scripts/coletar_whoscored_players.py
    python scripts/coletar_whoscored_players.py --rodada 20
"""
import argparse
import csv
import sys
from pathlib import Path

import requests

STAGE_ID = 25039  # Brasileirao 2026 no WhoScored
TOURNAMENT = 95
PLAYER_XG_URL = (
    "https://www.whoscored.com/statisticsfeed/1/getplayerstatistics"
    "?category=xg-stats&subcategory=summary&statsAccumulationType=0&isCurrent=true"
    f"&stageId={STAGE_ID}&tournamentOptions={TOURNAMENT}&sortBy=Rating&field=Overall"
    "&isMinApp=true&page=1&numberOfPlayersToPick=600&incPens=true"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
    "Referer": ("https://www.whoscored.com/regions/31/tournaments/95/seasons/10980/"
                "stages/25039/playerstatistics/brazil-brasileir%C3%A3o-2026"),
}
CARTOLA_STATUS = "https://api.cartolafc.globo.com/mercado/status"

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
HIST_PATH = DATA_DIR / "whoscored_player_xg_history.csv"

FIELDS = ["rodada", "name", "team", "apps", "mins", "xG", "xg90", "goal", "shots"]


def detectar_rodada_encerrada():
    try:
        r = requests.get(CARTOLA_STATUS, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
        r.raise_for_status()
        return int(r.json()["rodada_atual"]) - 1
    except Exception as e:
        print(f"Nao consegui detectar a rodada via Cartola ({e}). Use --rodada N.")
        return None


def fetch_players():
    r = requests.get(PLAYER_XG_URL, headers=HEADERS, timeout=30)
    if r.status_code != 200 or "playerTableStats" not in r.text:
        raise RuntimeError(f"Resposta inesperada do WhoScored (HTTP {r.status_code}). "
                           f"Provavelmente protecao anti-bot -- rode de um IP residencial.")
    return r.json()["playerTableStats"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rodada", type=int, default=None,
                     help="Rodada encerrada a que o snapshot corresponde. Se omitido, detecta via Cartola.")
    args = ap.parse_args()

    rodada = args.rodada if args.rodada is not None else detectar_rodada_encerrada()
    if rodada is None:
        sys.exit(1)
    print(f"Coletando snapshot de xG do WhoScored para a rodada {rodada}...")

    players = fetch_players()
    rows = []
    for p in players:
        rows.append({
            "rodada": rodada,
            "name": p["name"],
            "team": p["teamName"],
            "apps": p["apps"],
            "mins": p["minsPlayed"],
            "xG": round(p["xG"], 3),
            "xg90": round(p["xGPerNinety"], 4),
            "goal": p["goal"],
            "shots": p["totalShots"],
        })
    print(f"{len(rows)} jogadores coletados.")

    # snapshot datado pela rodada
    snap_path = DATA_DIR / f"whoscored_player_xg_2026_r{rodada}.csv"
    with open(snap_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Snapshot salvo: {snap_path}")

    # historico acumulado (dedup por rodada+jogador+time), pro backtest futuro
    existing = []
    if HIST_PATH.exists():
        with open(HIST_PATH, encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f)]
    key = lambda r: (str(r["rodada"]), r["name"], r["team"])
    novas = {key(r): r for r in rows}
    combinado = {key(r): r for r in existing}
    combinado.update(novas)  # sobrescreve se ja tinha essa (rodada, jogador)
    ordenado = sorted(combinado.values(), key=lambda r: (int(r["rodada"]), str(r["name"])))
    with open(HIST_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ordenado)
    rodadas_no_hist = sorted(set(int(r["rodada"]) for r in ordenado))
    print(f"Historico atualizado: {HIST_PATH} ({len(ordenado)} linhas, rodadas {rodadas_no_hist})")
    if len(rodadas_no_hist) >= 4:
        print("\nJa da pra rodar um backtest walk-forward do xG individual (>=4 rodadas de historico).")
    else:
        print(f"\nFaltam {4 - len(rodadas_no_hist)} rodada(s) de historico pra ter base de backtest walk-forward.")


if __name__ == "__main__":
    main()
