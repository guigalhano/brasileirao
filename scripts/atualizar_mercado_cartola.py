"""
Atualiza o snapshot do mercado do Cartola FC (preco, media, status de cada
jogador) e re-enriquece com o historico ja salvo em data/.

Criado para rodar no GitHub Actions (tem internet irrestrita) OU localmente.
NAO funciona dentro do sandbox do Claude -- o dominio api.cartolafc.globo.com
esta bloqueado la por política de rede do proprio ambiente.

Uso:
    python scripts/atualizar_mercado_cartola.py
"""
import json
import sys
import unicodedata
from pathlib import Path

import requests
import pandas as pd

MERCADO_URL = "https://api.cartolafc.globo.com/atletas/mercado"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

CANON_MAP = {
    "Athlético-PR": "Atletico-PR", "Atlético-MG": "Atletico-MG", "Bahia": "Bahia",
    "Botafogo": "Botafogo", "Bragantino": "Bragantino", "Chapecoense": "Chapecoense",
    "Corinthians": "Corinthians", "Coritiba": "Coritiba", "Cruzeiro": "Cruzeiro",
    "Flamengo": "Flamengo", "Fluminense": "Fluminense", "Grêmio": "Gremio",
    "Internacional": "Internacional", "Mirassol": "Mirassol", "Palmeiras": "Palmeiras",
    "Remo": "Remo", "Santos": "Santos", "São Paulo": "Sao Paulo", "Vasco da Gama": "Vasco",
    "Vitória": "Vitoria",
}


def normalize(s):
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def fetch_mercado():
    resp = requests.get(MERCADO_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_current_players(mercado):
    clubes = mercado["clubes"]
    posicoes = mercado["posicoes"]
    status = mercado["status"]

    club_name = {int(cid): CANON_MAP.get(c["nome_fantasia"], c["nome_fantasia"]) for cid, c in clubes.items()}
    pos_abbr = {int(k): v["abreviacao"].upper() for k, v in posicoes.items()}
    status_name = {int(k): v["nome"] for k, v in status.items()}

    rows = []
    for a in mercado["atletas"]:
        if a["jogos_num"] < 1:
            continue
        rows.append({
            "atleta_id": a["atleta_id"],
            "name": a["apelido"],
            "pos": pos_abbr.get(a["posicao_id"], "?"),
            "team": club_name.get(a["clube_id"], "?"),
            "price": round(a["preco_num"], 2),
            "media": round(a["media_num"], 2),
            "status": status_name.get(a["status_id"], str(a["status_id"])),
        })
    return pd.DataFrame(rows)


def enrich_with_history(current_df):
    hist_path = DATA_DIR / "cartola_historico_2026_completo.csv"
    if not hist_path.exists():
        print(f"AVISO: {hist_path} nao encontrado, seguindo sem forma recente/consistencia.")
        current_df["ult5"] = current_df["media"]
        current_df["desvio"] = 0.0
        return current_df

    hist = pd.read_csv(hist_path)
    hist = hist.rename(columns={
        "atletas.atleta_id": "atleta_id",
        "atletas.pontos_num": "pontos",
        "atletas.rodada_id": "rodada",
        "atletas.entrou_em_campo": "jogou",
    })
    played = hist[hist["jogou"] == True].copy()

    summary = played.groupby("atleta_id").agg(
        media_geral=("pontos", "mean"),
        desvio=("pontos", "std"),
    ).reset_index()

    def last5(g):
        g = g.sort_values("rodada")
        return g.tail(5)["pontos"].mean()

    form = played.groupby("atleta_id").apply(last5, include_groups=False).reset_index(name="media_ult5")
    summary = summary.merge(form, on="atleta_id", how="left")

    current_df = current_df.merge(summary, on="atleta_id", how="left")
    current_df["ult5"] = current_df["media_ult5"].fillna(current_df["media"])
    current_df["desvio"] = current_df["desvio"].fillna(0.0).round(2)
    current_df = current_df.drop(columns=["media_geral", "media_ult5"], errors="ignore")
    return current_df


def main():
    print(f"Buscando {MERCADO_URL} ...")
    try:
        mercado = fetch_mercado()
    except Exception as e:
        print(f"ERRO ao buscar o mercado do Cartola: {e}")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "mercado_cartola_raw.json", "w", encoding="utf-8") as f:
        json.dump(mercado, f, ensure_ascii=False)
    print(f"Salvo: {DATA_DIR / 'mercado_cartola_raw.json'} ({len(mercado.get('atletas', []))} atletas brutos)")

    current_df = build_current_players(mercado)
    print(f"{len(current_df)} jogadores com pelo menos 1 jogo.")

    enriched_df = enrich_with_history(current_df)
    out_path = DATA_DIR / "cartola_players_enriched.csv"
    enriched_df.to_csv(out_path, index=False)
    print(f"Salvo: {out_path}")


if __name__ == "__main__":
    main()
