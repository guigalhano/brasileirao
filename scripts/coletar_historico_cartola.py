"""
Coletor de historico do Cartola FC - RODAR NO SEU COMPUTADOR, NAO no Claude.

Por que rodar localmente: os endpoints da API do Cartola (api.cartolafc.globo.com
e o espelho api.kartolafc.com.br) nao estao acessiveis a partir do sandbox do
Claude (bloqueio de rede). Rodando na sua maquina, o acesso e direto e livre.

O QUE ESTE SCRIPT FAZ
----------------------
Tem dois modos:

1) --modo rodadas (padrao): baixa a pontuacao de TODOS os jogadores em CADA
   rodada ja encerrada (1 ate a rodada atual - 1), usando:
       GET https://api.cartolafc.globo.com/atletas/pontuados/{rodada}
   Gera um CSV "longo": uma linha por (jogador, rodada), com pontos e scouts.
   Mais completo, mas faz uma chamada por rodada (~18-19 chamadas hoje).

2) --modo jogadores: baixa o historico completo de uma lista especifica de
   atleta_id, usando o espelho:
       GET https://api.kartolafc.com.br/atletas/historico/{atleta_id}
   Mais rapido se voce so quer alguns jogadores (uma chamada por jogador).
   Os atleta_id ficam no mercado.json que voce ja tem (campo "atleta_id").

COMO USAR
---------
1. Precisa de Python 3.8+ instalado.
2. Instale a unica dependencia:
       pip install requests
3. Rode um dos dois modos:

   Todos os jogadores, todas as rodadas ja jogadas:
       python coletar_historico_cartola.py --modo rodadas --ate-rodada 18

   Só alguns jogadores especificos (mais rapido):
       python coletar_historico_cartola.py --modo jogadores --ids 93988,94583,98873

4. O resultado sai em "historico_cartola.csv" (e um .json bruto de backup),
   na mesma pasta do script. Suba esses arquivos aqui no chat quando terminar
   e eu processo tudo.

O script e gentil com a API: espera ~1s entre chamadas e tenta de novo (ate
3x) se alguma rodada falhar, sem travar o resto da coleta.
"""

import argparse
import csv
import json
import time
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Falta instalar a biblioteca 'requests'. Rode: pip install requests")
    sys.exit(1)

BASE_URL = "https://api.cartolafc.globo.com"
MIRROR_URL = "https://api.kartolafc.com.br"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
PAUSE_SECONDS = 1.0
MAX_RETRIES = 3


def fetch_json(url, retries=MAX_RETRIES):
    """GET a URL and parse JSON, with simple retry on failure."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
        print(f"  tentativa {attempt}/{retries} falhou ({last_err}), aguardando...")
        time.sleep(2)
    print(f"  DESISTINDO de {url}: {last_err}")
    return None


def get_atletas_master():
    """Fetch current player/club master data (names, teams, positions)."""
    print("Baixando dados mestres de jogadores/clubes (/atletas/mercado)...")
    data = fetch_json(f"{BASE_URL}/atletas/mercado")
    if not data:
        print("Nao consegui baixar dados mestres. Seguindo sem nomes/times "
              "(o CSV tera so atleta_id).")
        return {}, {}
    clubes = {int(cid): c["nome_fantasia"] for cid, c in data["clubes"].items()}
    posicoes_map = {1: "GOL", 2: "LAT", 3: "ZAG", 4: "MEI", 5: "ATA", 6: "TEC"}
    atletas = {}
    for a in data["atletas"]:
        atletas[a["atleta_id"]] = {
            "nome": a["apelido"],
            "clube": clubes.get(a["clube_id"], "?"),
            "posicao": posicoes_map.get(a["posicao_id"], "?"),
        }
    return atletas, clubes


def coletar_por_rodadas(ate_rodada, desde_rodada=1):
    """Mode 1: loop over rounds, fetch all players' scores per round."""
    atletas_master, _ = get_atletas_master()

    rows = []
    raw_backup = {}

    for rodada in range(desde_rodada, ate_rodada + 1):
        print(f"Rodada {rodada}/{ate_rodada}...")
        url = f"{BASE_URL}/atletas/pontuados/{rodada}"
        data = fetch_json(url)
        time.sleep(PAUSE_SECONDS)
        if not data:
            continue
        raw_backup[rodada] = data

        atletas = data.get("atletas", {})
        for atleta_id_str, info in atletas.items():
            atleta_id = int(atleta_id_str)
            master = atletas_master.get(atleta_id, {})
            row = {
                "atleta_id": atleta_id,
                "nome": master.get("nome", info.get("apelido", "?")),
                "clube": master.get("clube", "?"),
                "posicao": master.get("posicao", "?"),
                "rodada": rodada,
                "pontos": info.get("pontuacao", info.get("pontos_num", "")),
            }
            scout = info.get("scout") or {}
            for k, v in scout.items():
                row[f"scout_{k}"] = v
            rows.append(row)

    return rows, raw_backup


def coletar_por_jogadores(ids):
    """Mode 2: fetch full history for a specific list of player IDs via mirror."""
    rows = []
    raw_backup = {}

    for i, atleta_id in enumerate(ids, 1):
        print(f"Jogador {i}/{len(ids)} (id={atleta_id})...")
        url = f"{MIRROR_URL}/atletas/historico/{atleta_id}"
        data = fetch_json(url)
        time.sleep(PAUSE_SECONDS)
        if not data:
            continue
        raw_backup[atleta_id] = data

        # The mirror's exact shape can vary; handle a couple of likely formats.
        historico = data.get("historico") or data.get("rodadas") or data
        if isinstance(historico, dict):
            historico = list(historico.values())
        if not isinstance(historico, list):
            print(f"  formato inesperado para id {atleta_id}, salvando so o bruto.")
            continue

        nome = data.get("apelido") or data.get("nome") or str(atleta_id)
        for entry in historico:
            if not isinstance(entry, dict):
                continue
            row = {
                "atleta_id": atleta_id,
                "nome": nome,
                "rodada": entry.get("rodada_id", entry.get("rodada", "")),
                "pontos": entry.get("pontos", entry.get("pontuacao", "")),
                "preco": entry.get("preco", ""),
                "media": entry.get("media", ""),
            }
            scout = entry.get("scout") or {}
            for k, v in scout.items():
                row[f"scout_{k}"] = v
            rows.append(row)

    return rows, raw_backup


def save_csv(rows, path):
    if not rows:
        print("Nada para salvar (nenhuma linha coletada).")
        return
    # union of all fieldnames across rows, keeping a sensible order first
    priority = ["atleta_id", "nome", "clube", "posicao", "rodada", "pontos", "preco", "media"]
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    fieldnames = [k for k in priority if k in all_keys] + sorted(all_keys - set(priority))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Salvo: {path} ({len(rows)} linhas)")


def save_json_backup(raw_backup, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw_backup, f, ensure_ascii=False)
    print(f"Backup bruto salvo: {path}")


def main():
    parser = argparse.ArgumentParser(description="Coleta historico de pontuacoes do Cartola FC")
    parser.add_argument("--modo", choices=["rodadas", "jogadores"], default="rodadas",
                         help="'rodadas' = todos os jogadores em cada rodada; "
                              "'jogadores' = historico completo de IDs especificos")
    parser.add_argument("--ate-rodada", type=int, default=18,
                         help="Ultima rodada ja encerrada a coletar (modo 'rodadas')")
    parser.add_argument("--desde-rodada", type=int, default=1,
                         help="Primeira rodada a coletar (modo 'rodadas')")
    parser.add_argument("--ids", type=str, default="",
                         help="Lista de atleta_id separados por virgula (modo 'jogadores')")
    parser.add_argument("--saida", type=str, default="historico_cartola",
                         help="Prefixo dos arquivos de saida")
    args = parser.parse_args()

    if args.modo == "rodadas":
        rows, raw = coletar_por_rodadas(args.ate_rodada, args.desde_rodada)
    else:
        if not args.ids:
            print("Modo 'jogadores' precisa de --ids, ex: --ids 93988,94583,98873")
            sys.exit(1)
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        rows, raw = coletar_por_jogadores(ids)

    csv_path = Path(f"{args.saida}.csv")
    json_path = Path(f"{args.saida}_bruto.json")
    save_csv(rows, csv_path)
    save_json_backup(raw, json_path)

    print("\nPronto. Suba esses dois arquivos no chat com o Claude para eu processar.")


if __name__ == "__main__":
    main()
