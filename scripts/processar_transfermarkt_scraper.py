"""
Coletor de valores de mercado do Transfermarkt via dcaribou/transfermarkt-scraper
RODAR NO SEU COMPUTADOR, NAO no Claude (mesmo motivo de sempre: o dominio
transfermarkt.com nao esta liberado no sandbox do Claude).

Por que essa ferramenta em vez da tmquery que tentamos antes: o crawler
`clubs` dessa biblioteca ja traz o valor de mercado do elenco JUNTO com os
dados do time, numa unica passada por clube -- nao precisa visitar a pagina
de cada jogador individualmente. Pros nossos 20 times, isso significa ~20
requisicoes em vez de ~500+, bem mais rapido e mais seguro.

PASSO 1 -- instalar
--------------------
    git clone https://github.com/dcaribou/transfermarkt-scraper
    cd transfermarkt-scraper
    poetry install
    poetry shell

(Se nao tiver o poetry: pip install poetry)

PASSO 2 -- descobrir o ID da competicao (so precisa fazer uma vez)
---------------------------------------------------------------------
    python -m tfmkt confederations > confederations.json
    cat confederations.json | python -m tfmkt competitions > competitions.json
    grep -i "campeonato-brasileiro-serie-a" competitions.json

Isso deve mostrar uma linha com "href":"/campeonato-brasileiro-serie-a/startseite/wettbewerb/BRA1"
-- o ID da competicao e "BRA1" (confirmado, e o mesmo ID que ja vimos antes
em outras fontes). Se o href vier diferente, ajuste o comando do Passo 3.

PASSO 3 -- baixar os 20 times com valor de mercado do elenco
----------------------------------------------------------------
    echo '{"type":"competition","href":"/campeonato-brasileiro-serie-a/startseite/wettbewerb/BRA1","competition_type":"first_tier"}' \\
        | python -m tfmkt clubs --season 2026 > brasileirao_clubes_2026.json

Isso gera um arquivo com uma linha JSON por time (20 linhas), cada uma com o
valor de mercado do elenco, tecnico, estadio etc.

PASSO 4 -- processar o resultado
------------------------------------
Rode este script (precisa so de Python padrao, sem tmquery):
    python processar_transfermarkt_scraper.py brasileirao_clubes_2026.json

Isso gera "transfermarkt_times_resumo.csv", pronto pra subir aqui no chat.

(Opcional) PASSO 5 -- se tambem quiser dado por jogador (mais lento, ~500+
requisicoes, so vale a pena se voce realmente precisar de detalhe individual):
    cat brasileirao_clubes_2026.json | python -m tfmkt players > jogadores.json
"""
import json
import sys
import csv
from pathlib import Path


def parse_value_to_millions(value):
    """Os valores no JSON do transfermarkt-scraper costumam vir como numero
    puro (em euros) ou como string tipo '€150.30m'. Trata os dois casos."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # numero puro em euros -> converte pra milhoes
        return round(value / 1_000_000, 2)
    s = str(value).replace("€", "").strip()
    try:
        if s.endswith("m"):
            return round(float(s[:-1]), 2)
        if s.endswith("k"):
            return round(float(s[:-1]) / 1000.0, 2)
        return round(float(s) / 1_000_000, 2)
    except ValueError:
        return None


def main():
    if len(sys.argv) < 2:
        print("Uso: python processar_transfermarkt_scraper.py brasileirao_clubes_2026.json")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Arquivo nao encontrado: {path}")
        sys.exit(1)

    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # os nomes exatos dos campos podem variar por versao da lib;
            # tenta as chaves mais prováveis para nome do time e valor de mercado
            nome = obj.get("name") or obj.get("club_name") or obj.get("pretty_name") or "?"
            valor_bruto = (
                obj.get("market_value")
                or obj.get("squad_market_value")
                or obj.get("total_market_value")
            )
            valor_milhoes = parse_value_to_millions(valor_bruto)
            rows.append({
                "time": nome,
                "valor_total_milhoes": valor_milhoes,
                "campo_bruto_usado": valor_bruto,
            })

    if not rows:
        print("Nenhum time encontrado no arquivo. Confira se o JSON tem uma linha por time.")
        sys.exit(1)

    out_path = Path("transfermarkt_times_resumo.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "valor_total_milhoes", "campo_bruto_usado"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Salvo: {out_path} ({len(rows)} times)")
    print("\nSe 'valor_total_milhoes' vier vazio para algum time, confira a coluna")
    print("'campo_bruto_usado' -- pode ser que essa versao da lib use um nome de")
    print("campo diferente (ex: 'total_market_value' em vez de 'market_value');")
    print("me mande o JSON bruto de um time e eu ajusto o parser.")


if __name__ == "__main__":
    main()
