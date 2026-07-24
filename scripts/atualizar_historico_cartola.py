"""
Atualiza data/cartola_historico_2026_completo.csv com as rodadas novas ja
encerradas, incrementalmente (nao refaz o arquivo inteiro do zero).

Criado para rodar no GitHub Actions (tem internet irrestrita) OU localmente.
NAO funciona dentro do sandbox do Claude -- o dominio api.cartolafc.globo.com
esta bloqueado la por politica de rede do proprio ambiente.

COMO FUNCIONA
-------------
1. Le o CSV existente e acha a maior rodada ja presente (coluna
   "atletas.rodada_id").
2. Tenta buscar GET /atletas/pontuados/{rodada} para as proximas rodadas
   (max+1, max+2, ...), parando assim que uma rodada falhar ou vier vazia
   (sinal de que ainda nao foi encerrada -- as rodadas sao sequenciais, entao
   nao faz sentido tentar pular uma que falhou e testar a seguinte).
3. Faz append das linhas novas no MESMO formato de coluna do arquivo (o
   schema "atletas.X" + colunas de scout por letra vem do dataset publico
   henriquepgomide/caRtola, que e a fonte original deste CSV).

Uso:
    python scripts/atualizar_historico_cartola.py
"""
import csv
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.cartolafc.globo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
PAUSE_SECONDS = 1.0
MAX_RODADAS_A_FRENTE = 5  # tenta no maximo essas rodadas novas por execucao

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORICO_CSV = REPO_ROOT / "data" / "cartola_historico_2026_completo.csv"

CLUBE_ID_TO_ABBR = {
    2305: "MIR", 262: "FLA", 263: "BOT", 264: "COR", 265: "BAH", 266: "FLU",
    267: "VAS", 275: "PAL", 276: "SAO", 277: "SAN", 280: "RBB", 282: "CAM",
    283: "CRU", 284: "GRE", 285: "INT", 287: "VIT", 293: "CAP", 294: "CFC",
    315: "CHA", 364: "REM",
}

SCOUT_COLS = ["A", "CA", "CV", "DE", "DS", "FC", "FD", "FF", "FS", "FT",
              "G", "GC", "GS", "I", "PC", "PS", "SG", "V", "DP", "PP"]


def fetch_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except Exception as e:
        return None, str(e)


def linha_do_atleta(atleta_id, info, rodada):
    row = {
        "atletas.apelido": info.get("apelido", ""),
        "atletas.apelido_abreviado": info.get("apelido_abreviado", info.get("apelido", "")),
        "atletas.atleta_id": atleta_id,
        "atletas.clube.id.full.name": CLUBE_ID_TO_ABBR.get(info.get("clube_id"), ""),
        "atletas.clube_id": info.get("clube_id", ""),
        "atletas.entrou_em_campo": info.get("entrou_em_campo", ""),
        "atletas.foto": info.get("foto", ""),
        "atletas.jogos_num": info.get("jogos_num", ""),
        "atletas.media_num": info.get("media_num", ""),
        "atletas.nome": info.get("nome", info.get("apelido", "")),
        "atletas.pontos_num": info.get("pontuacao", info.get("pontos_num", "")),
        "atletas.posicao_id": info.get("posicao_id", ""),
        "atletas.preco_num": info.get("preco_num", ""),
        "atletas.rodada_id": rodada,
        "atletas.slug": info.get("slug", ""),
        "atletas.status_id": info.get("status_id", ""),
        "atletas.variacao_num": info.get("variacao_num", ""),
        "atletas.craque": info.get("craque", ""),
    }
    scout = info.get("scout") or {}
    for col in SCOUT_COLS:
        row[col] = scout.get(col, "")
    return row


def main():
    if not HISTORICO_CSV.exists():
        print(f"ERRO: {HISTORICO_CSV} nao encontrado.")
        sys.exit(1)

    with open(HISTORICO_CSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    max_rodada = max(int(r["atletas.rodada_id"]) for r in rows if r["atletas.rodada_id"])
    print(f"Rodada mais recente no historico: {max_rodada}")

    novas_rows = []
    for rodada in range(max_rodada + 1, max_rodada + 1 + MAX_RODADAS_A_FRENTE):
        url = f"{BASE_URL}/atletas/pontuados/{rodada}"
        print(f"Tentando rodada {rodada}: {url}")
        data, err = fetch_json(url)
        time.sleep(PAUSE_SECONDS)
        if err or not data or not data.get("atletas"):
            print(f"  rodada {rodada} indisponivel ({err or 'sem atletas, ainda nao encerrada'}) -- parando aqui.")
            break
        atletas = data["atletas"]
        for atleta_id_str, info in atletas.items():
            novas_rows.append(linha_do_atleta(int(atleta_id_str), info, rodada))
        print(f"  rodada {rodada}: {len(atletas)} jogadores coletados.")

    if not novas_rows:
        print("\nNenhuma rodada nova encontrada. Nada para adicionar.")
        return

    with open(HISTORICO_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerows(novas_rows)

    rodadas_novas = sorted(set(r["atletas.rodada_id"] for r in novas_rows))
    print(f"\nOK: {len(novas_rows)} linhas novas adicionadas (rodadas {rodadas_novas}).")


if __name__ == "__main__":
    main()
