"""
Compara o seu time do Cartola FC com a rodada - RODAR NO SEU COMPUTADOR, NAO no Claude.

Por que rodar localmente: api.cartolafc.globo.com nao e acessivel a partir do
sandbox do Claude (bloqueio de rede, mesma razao dos outros scripts de coleta).

O QUE ESTE SCRIPT FAZ
----------------------
1. Busca o SEU time numa rodada ja encerrada:
       GET https://api.cartolafc.globo.com/time/id/{time_id}/{rodada}
   Isso e um endpoint documentado e confiavel: retorna sua escalacao daquela
   rodada e a pontuacao total que ela fez.

2. Calcula a media de pontos de TODOS os jogadores naquela rodada, usando o
   nosso proprio historico ja coletado (data/cartola_historico_2026_completo.csv).
   Isso sempre funciona, independente da API.

3. TENTA (sem garantia) alguns endpoints candidatos que a comunidade associa a
   "media geral da rodada" / destaques, ja que a API publica do Cartola NAO tem
   um endpoint documentado oficialmente para "time mais escalado". Se algum
   desses responder, o script salva o JSON bruto pra gente inspecionar junto
   e decidir se da pra extrair algo util (ex: media real de todos os times,
   nao so de jogadores individuais).

COMO USAR
---------
1. Precisa de Python 3.8+ e da biblioteca requests (pip install requests).
2. Rode:
       python comparar_meu_time.py --time-id 199236 --rodada 18
3. Suba aqui no chat o que ele imprimir (e os arquivos *_bruto.json gerados)
   pra eu terminar a analise.
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Falta instalar a biblioteca 'requests'. Rode: pip install requests")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("Falta instalar a biblioteca 'pandas'. Rode: pip install pandas")
    sys.exit(1)

BASE_URL = "https://api.cartolafc.globo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

# Candidatos "pode ser que exista" para dado agregado da rodada (nao documentados
# oficialmente). Tentamos e mostramos o que vier, sem assumir o formato.
ENDPOINTS_CANDIDATOS_RODADA = [
    "/post/rodada/{rodada}/destaques",
    "/mercado/destaques",
    "/rodada/{rodada}/destaques",
]

HISTORICO_CSV = Path(__file__).resolve().parent.parent / "data" / "cartola_historico_2026_completo.csv"


def fetch_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except Exception as e:
        return None, str(e)


def buscar_meu_time(time_id, rodada):
    url = f"{BASE_URL}/time/id/{time_id}/{rodada}"
    print(f"Buscando seu time na rodada {rodada}: {url}")
    data, err = fetch_json(url)
    if err:
        print(f"  FALHOU: {err}")
        return None
    return data


TAMANHO_TIME = 12  # 11 titulares + 1 capitao (pontua em dobro, ~equivalente a mais 1 titular medio)


def media_da_rodada_no_historico(rodada):
    """Stats de pontos dos jogadores que ENTRARAM EM CAMPO na rodada (filtra
    reservas que nem jogaram, que dominam a base e derrubam a media pra quase
    zero), usando o historico que ja coletamos (sempre disponivel, nao depende
    da API). 'time_medio' = essa media vezes TAMANHO_TIME, como referencia de
    um time inteiro."""
    if not HISTORICO_CSV.exists():
        print(f"Aviso: {HISTORICO_CSV} nao encontrado, pulando comparacao com historico.")
        return None
    df = pd.read_csv(HISTORICO_CSV)
    col_rodada = "atletas.rodada_id"
    col_pontos = "atletas.pontos_num"
    col_jogou = "atletas.entrou_em_campo"
    if col_rodada not in df.columns or col_pontos not in df.columns or col_jogou not in df.columns:
        print("Aviso: colunas esperadas nao encontradas no historico.")
        return None
    sub = df[(df[col_rodada] == rodada) & (df[col_jogou] == True)]  # noqa: E712
    if sub.empty:
        print(f"Aviso: rodada {rodada} nao encontrada no historico.")
        return None
    media_pontos = sub[col_pontos].mean()
    return {
        "n_jogadores": len(sub),
        "media_pontos": media_pontos,
        "mediana_pontos": sub[col_pontos].median(),
        "top10_media": sub.sort_values(col_pontos, ascending=False).head(10)[col_pontos].mean(),
        "time_medio": media_pontos * TAMANHO_TIME,
    }


def tentar_destaques_rodada(rodada, saida_prefixo):
    print("\nTentando endpoints candidatos para dado agregado da rodada "
          "(NAO documentados oficialmente, resultado incerto)...")
    encontrados = {}
    for template in ENDPOINTS_CANDIDATOS_RODADA:
        path = template.format(rodada=rodada)
        url = f"{BASE_URL}{path}"
        data, err = fetch_json(url)
        if err:
            print(f"  {path}: falhou ({err})")
            continue
        print(f"  {path}: respondeu! Salvando bruto para inspecao.")
        encontrados[path] = data
        time.sleep(0.5)

    if encontrados:
        out_path = Path(f"{saida_prefixo}_destaques_bruto.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(encontrados, f, ensure_ascii=False, indent=2)
        print(f"Salvo: {out_path} -- suba esse arquivo no chat pra eu ver o formato real.")
    else:
        print("  Nenhum candidato respondeu. A API publica realmente nao expoe "
              "esse dado -- vamos seguir so com a comparacao via historico.")
    return encontrados


def main():
    parser = argparse.ArgumentParser(description="Compara seu time do Cartola FC com a rodada")
    parser.add_argument("--time-id", type=int, required=True, help="ID numerico do seu time (da URL cartola.globo.com/#!/time/ID)")
    parser.add_argument("--rodada", type=int, required=True, help="Rodada ja encerrada para comparar")
    parser.add_argument("--saida", type=str, default="meu_time", help="Prefixo dos arquivos de saida")
    args = parser.parse_args()

    meu_time = buscar_meu_time(args.time_id, args.rodada)
    if meu_time:
        nome_time = meu_time.get("time", {}).get("nome", "?") if isinstance(meu_time.get("time"), dict) else meu_time.get("nome", "?")
        pontos = meu_time.get("pontos")
        print(f"\nSeu time: {nome_time}")
        print(f"Pontos na rodada {args.rodada}: {pontos}")
        out_path = Path(f"{args.saida}_bruto.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(meu_time, f, ensure_ascii=False, indent=2)
        print(f"Salvo bruto: {out_path}")

    stats = media_da_rodada_no_historico(args.rodada)
    if stats:
        print(f"\nJogadores que entraram em campo na rodada {args.rodada} "
              f"(nosso historico, {stats['n_jogadores']} jogadores):")
        print(f"  media:            {stats['media_pontos']:.2f}")
        print(f"  mediana:          {stats['mediana_pontos']:.2f}")
        print(f"  media do top 10:  {stats['top10_media']:.2f}")
        print(f"  time medio ({TAMANHO_TIME}x a media): {stats['time_medio']:.2f}")
        if meu_time and pontos is not None:
            diff = pontos - stats["time_medio"]
            print(f"\nSeu time ({pontos} pts) vs time medio estimado: "
                  f"{'+' if diff >= 0 else ''}{diff:.2f} pts")
            print("(time medio = media dos jogadores que jogaram, vezes 12 (11 "
                  "titulares + capitao) -- referencia aproximada, ja que a API "
                  "publica nao expoe a media real de times inteiros de outros "
                  "cartoleiros.)")

    tentar_destaques_rodada(args.rodada, args.saida)

    print("\nPronto. Suba os arquivos *_bruto.json aqui no chat para eu processar "
          "e te dar a analise completa.")


if __name__ == "__main__":
    main()
