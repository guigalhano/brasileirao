"""
Compara o HISTORICO do seu time do Cartola FC contra o mercado, rodada a rodada -
RODAR NO SEU COMPUTADOR, NAO no Claude.

Por que rodar localmente: api.cartolafc.globo.com nao e acessivel a partir do
sandbox do Claude (bloqueio de rede, mesma razao dos outros scripts de coleta).

O QUE ESTE SCRIPT FAZ
----------------------
Para cada rodada ja encerrada no intervalo pedido:

1. Busca a pontuacao real do SEU time naquela rodada:
       GET https://api.cartolafc.globo.com/time/id/{time_id}/{rodada}
   (endpoint documentado e confiavel)

2. Calcula um "time medio" de referencia usando o nosso proprio historico ja
   coletado (data/cartola_historico_2026_completo.csv): media de pontos so
   dos jogadores que ENTRARAM EM CAMPO naquela rodada (filtra reservas que
   nem jogaram, que dominam a base e derrubariam a media pra quase zero),
   vezes 12 (11 titulares + 1 capitao, que pontua em dobro). Essa e a
   referencia de "mercado" que usamos, ja que a API publica NAO tem um
   endpoint documentado e confiavel para "time mais escalado" (ja tentamos:
   api.cartola.globo.com e gatomestre.ge.globo.com estao fora do alcance do
   Claude; se voce achar o dado real de "mais escalados" em algum lugar, me
   manda que eu incorporo).

3. No final, monta um CSV com uma linha por rodada (seus pontos, media do
   mercado, diferenca, se bateu ou nao) e imprime um resumo da temporada:
   quantas rodadas voce bateu a media, saldo total de pontos acima/abaixo
   do mercado, etc.

COMO USAR
---------
1. Precisa de Python 3.8+ e das bibliotecas requests e pandas
   (pip install requests pandas).
2. Rode (rodadas 1 a 18, por exemplo):
       python comparar_historico_time.py --time-id 199236 --desde-rodada 1 --ate-rodada 18
3. Suba aqui no chat o CSV gerado (e o que ele imprimir) pra eu analisar junto
   com voce (ex: em que tipo de rodada voce mais perde pro mercado).
"""

import argparse
import csv
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
PAUSE_SECONDS = 1.0
HISTORICO_CSV = Path(__file__).resolve().parent.parent / "data" / "cartola_historico_2026_completo.csv"


def fetch_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except Exception as e:
        return None, str(e)


def buscar_meu_time_na_rodada(time_id, rodada):
    url = f"{BASE_URL}/time/id/{time_id}/{rodada}"
    data, err = fetch_json(url)
    if err:
        print(f"  rodada {rodada}: FALHOU ao buscar seu time ({err})")
        return None
    pontos = data.get("pontos")
    if pontos is None:
        print(f"  rodada {rodada}: time respondeu mas sem 'pontos' (rodada pode nao ter sido pontuada ainda)")
        return None
    return pontos


TAMANHO_TIME = 12  # 11 titulares + 1 capitao (pontua em dobro, ~equivalente a mais 1 titular medio)


def carregar_medias_por_rodada():
    """Para cada rodada, media de pontos SO dos jogadores que entraram em campo
    (nosso historico ja coletado, sempre disponivel, nao depende da API),
    e o "time medio" estimado (essa media vezes TAMANHO_TIME)."""
    if not HISTORICO_CSV.exists():
        print(f"ERRO: {HISTORICO_CSV} nao encontrado. Rode a partir da raiz do repo.")
        sys.exit(1)
    df = pd.read_csv(HISTORICO_CSV)
    col_rodada = "atletas.rodada_id"
    col_pontos = "atletas.pontos_num"
    col_jogou = "atletas.entrou_em_campo"
    if col_rodada not in df.columns or col_pontos not in df.columns or col_jogou not in df.columns:
        print("ERRO: colunas esperadas nao encontradas no historico.")
        sys.exit(1)
    titulares = df[df[col_jogou] == True]  # noqa: E712
    agg = titulares.groupby(col_rodada)[col_pontos].agg(["mean", "median", "count"])
    agg["time_medio"] = agg["mean"] * TAMANHO_TIME
    return agg


def main():
    parser = argparse.ArgumentParser(
        description="Compara o historico do seu time do Cartola FC contra a media do mercado, rodada a rodada")
    parser.add_argument("--time-id", type=int, required=True,
                         help="ID numerico do seu time (da URL cartola.globo.com/#!/time/ID)")
    parser.add_argument("--desde-rodada", type=int, default=1, help="Primeira rodada a comparar")
    parser.add_argument("--ate-rodada", type=int, default=18, help="Ultima rodada ja encerrada a comparar")
    parser.add_argument("--saida", type=str, default="historico_meu_time.csv", help="Caminho do CSV de saida")
    args = parser.parse_args()

    medias = carregar_medias_por_rodada()

    linhas = []
    print(f"Buscando seu time (id={args.time_id}) da rodada {args.desde_rodada} a {args.ate_rodada}...")
    for rodada in range(args.desde_rodada, args.ate_rodada + 1):
        print(f"Rodada {rodada}/{args.ate_rodada}...")
        meus_pontos = buscar_meu_time_na_rodada(args.time_id, rodada)
        time.sleep(PAUSE_SECONDS)

        if rodada not in medias.index:
            print(f"  rodada {rodada}: sem dado de mercado no nosso historico, pulando.")
            continue
        time_medio = medias.loc[rodada, "time_medio"]

        linha = {
            "rodada": rodada,
            "meus_pontos": meus_pontos,
            "time_medio_12": round(time_medio, 2),
        }
        if meus_pontos is not None:
            linha["diferenca"] = round(meus_pontos - time_medio, 2)
            linha["bateu_mercado"] = meus_pontos > time_medio
        else:
            linha["diferenca"] = ""
            linha["bateu_mercado"] = ""
        linhas.append(linha)

    if not linhas:
        print("\nNenhuma rodada comparada com sucesso. Nada para salvar.")
        return

    out_path = Path(args.saida)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rodada", "meus_pontos", "time_medio_12",
                                                "diferenca", "bateu_mercado"])
        writer.writeheader()
        for linha in linhas:
            writer.writerow(linha)
    print(f"\nSalvo: {out_path} ({len(linhas)} rodadas)")

    validas = [l for l in linhas if l["meus_pontos"] is not None]
    if validas:
        n = len(validas)
        vitorias = sum(1 for l in validas if l["bateu_mercado"])
        saldo_total = sum(l["diferenca"] for l in validas)
        meus_pontos_total = sum(l["meus_pontos"] for l in validas)
        mercado_total = sum(l["time_medio_12"] for l in validas)

        print(f"\n=== Resumo da temporada ({n} rodadas com dado) ===")
        print(f"Voce bateu o time medio em {vitorias}/{n} rodadas ({100*vitorias/n:.0f}%)")
        print(f"Seus pontos totais:         {meus_pontos_total:.1f}")
        print(f"Time medio (soma):          {mercado_total:.1f}")
        print(f"Saldo total (voce - medio): {'+' if saldo_total >= 0 else ''}{saldo_total:.1f}")
        print(f"Diferenca media por rodada:   {'+' if saldo_total/n >= 0 else ''}{saldo_total/n:.2f}")

    print("\n(Lembrete: 'time_medio_12' e a media de pontos dos jogadores que "
          "ENTRARAM EM CAMPO naquela rodada, vezes 12 (11 titulares + capitao) --"
          " nao a media real de times inteiros de outros cartoleiros, que a API "
          "publica nao expoe. E a referencia mais solida que da pra calcular sem "
          "esse dado.)")

    print("\nPronto. Suba o CSV aqui no chat pra eu analisar junto com voce.")


if __name__ == "__main__":
    main()
