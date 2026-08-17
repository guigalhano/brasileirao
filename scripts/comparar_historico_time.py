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
1. Precisa de Python 3.8+ e da biblioteca requests (pip install requests).
2. Rode (sem --ate-rodada ele vai ate a ultima rodada ja pontuada no historico):
       python comparar_historico_time.py --time-id 199236 --saida data/meu_time_historico.csv
3. Depois rode scripts/build_meu_time_tab.py pra embutir no index.html.

Isto roda no GitHub Actions junto com o resto do pipeline -- o endpoint
/time/id/{id}/{rodada} e publico e nao pede autenticacao.
"""

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("Falta instalar a biblioteca 'requests'. Rode: pip install requests")
    sys.exit(1)

BASE_URL = "https://api.cartolafc.globo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
PAUSE_SECONDS = 1.0
HISTORICO_CSV = Path(__file__).resolve().parent.parent / "data" / "cartola_historico_2026_completo.csv"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.pontuacao import jogou, scouts_do_historico


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
    e o "time medio" estimado (essa media vezes TAMANHO_TIME).

    SCHEMA (corrigido em agosto/2026): este script lia "atletas.rodada_id",
    "atletas.pontos_num" e "atletas.entrou_em_campo" -- o schema antigo do
    dataset caRtola. O CSV foi reescrito para rodada/pontos/scout_X e o script
    passou a morrer no sys.exit(1) do "colunas esperadas nao encontradas".
    Foi por isso que a aba "Meu Time" parou na rodada 20: mesma causa raiz que
    congelou o atualizar_historico_cartola.py.

    A coluna entrou_em_campo tambem sumiu, entao "jogou" agora e deduzido do
    proprio scout (lib.pontuacao.jogou), igual ao resto do pipeline.
    """
    if not HISTORICO_CSV.exists():
        print(f"ERRO: {HISTORICO_CSV} nao encontrado. Rode a partir da raiz do repo.")
        sys.exit(1)

    linhas = list(csv.DictReader(HISTORICO_CSV.open(encoding="utf-8")))
    if not linhas:
        print(f"ERRO: {HISTORICO_CSV.name} vazio.")
        sys.exit(1)
    faltando = {"rodada", "pontos"} - set(linhas[0])
    if faltando:
        print(f"ERRO: {HISTORICO_CSV.name} sem as colunas {sorted(faltando)}. "
              f"Colunas encontradas: {sorted(linhas[0])[:8]}...")
        sys.exit(1)

    scouts = scouts_do_historico(linhas)
    por_rodada = defaultdict(list)
    for r in linhas:
        if jogou(r, scouts):
            por_rodada[int(r["rodada"])].append(float(r["pontos"] or 0))

    agg = {rod: {"mean": sum(v) / len(v), "count": len(v),
                 "time_medio": (sum(v) / len(v)) * TAMANHO_TIME}
           for rod, v in por_rodada.items() if v}
    return agg


def main():
    parser = argparse.ArgumentParser(
        description="Compara o historico do seu time do Cartola FC contra a media do mercado, rodada a rodada")
    parser.add_argument("--time-id", type=int, required=True,
                         help="ID numerico do seu time (da URL cartola.globo.com/#!/time/ID)")
    parser.add_argument("--desde-rodada", type=int, default=1, help="Primeira rodada a comparar")
    parser.add_argument("--ate-rodada", type=int, default=None,
                        help="Ultima rodada a comparar (padrao: a ultima ja "
                             "pontuada no historico)")
    parser.add_argument("--saida", type=str, default="historico_meu_time.csv", help="Caminho do CSV de saida")
    args = parser.parse_args()

    medias = carregar_medias_por_rodada()
    # Sem --ate-rodada, vai ate onde o historico de scouts alcanca. Assim o
    # pipeline nao precisa saber a rodada: ela sai do proprio dado.
    ate = args.ate_rodada if args.ate_rodada else max(medias)

    linhas = []
    print(f"Buscando seu time (id={args.time_id}) da rodada {args.desde_rodada} a {ate}...")
    for rodada in range(args.desde_rodada, ate + 1):
        print(f"Rodada {rodada}/{ate}...")
        meus_pontos = buscar_meu_time_na_rodada(args.time_id, rodada)
        time.sleep(PAUSE_SECONDS)

        if rodada not in medias:
            print(f"  rodada {rodada}: sem dado de mercado no nosso historico, pulando.")
            continue
        time_medio = medias[rodada]["time_medio"]

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
