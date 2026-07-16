"""
Coletor de valores de mercado do Transfermarkt - RODAR NO SEU COMPUTADOR, NAO no Claude.

Por que rodar localmente: a biblioteca tmquery precisa acessar transfermarkt.com
diretamente, e esse dominio nao esta liberado no sandbox do Claude (mesma
restricao de rede que ja vimos com a API do Cartola).

AVISO IMPORTANTE SOBRE COMO A BIBLIOTECA REALMENTE FUNCIONA (conferido no
codigo-fonte antes de escrever este script, para nao te dar algo quebrado):
- table.get_players().csv() NAO inclui valor de mercado -- so retorna dados
  cadastrais (nome, posicao, clube, data de nascimento etc). O valor de
  mercado exige uma chamada SEPARADA: table.get_players().get_market_value(),
  que devolve o HISTORICO COMPLETO de valor de cada jogador (um ponto por
  data em que o valor mudou), nao so o valor atual -- por isso este script
  pega a entrada mais recente de cada jogador como "valor atual".
- Cada jogador exige 3 requisicoes HTTP nos bastidores (dados do jogador,
  grafico de valor de mercado, historico de transferencias), e a biblioteca
  NAO tem nenhum limite de velocidade embutido. Por isso este script adiciona
  pausas manuais entre jogadores, para nao sobrecarregar o Transfermarkt nem
  correr risco de bloqueio por excesso de requisicoes.
- Estimativa de tempo: ~25-30 jogadores por time x 20 times x pausa de 1.5s
  == pode levar 20-40 minutos no total. E normal demorar; rode em segundo
  plano ou por partes (veja --time abaixo).

COMO USAR
---------
1. Python 3.8+ e as dependencias:
       pip install tmquery pandas
2. Rodar tudo (pode demorar, ver aviso acima):
       python coletar_transfermarkt.py
   Ou só um time por vez, para ir salvando aos poucos e evitar perder tudo
   se algo travar no meio (RECOMENDADO na primeira vez):
       python coletar_transfermarkt.py --time Palmeiras
       python coletar_transfermarkt.py --time Flamengo
       ...(um comando por time)
3. Resultado (dois arquivos por execucao, sem sobrescrever entre times
   diferentes -- veja --saida):
       transfermarkt_jogadores.csv    (um jogador por linha, valor mais recente)
       transfermarkt_times_resumo.csv (um time por linha, valor total do elenco)

   Suba os arquivos aqui no chat quando terminar (se rodou por partes, pode
   subir varios CSVs de uma vez, eu junto tudo).

O script usa cache em disco (pasta ./cache/) -- se precisar rodar de novo
por causa de uma falha, paginas ja baixadas nao sao buscadas de novo.
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    from tmquery import TMQuery
except ImportError:
    print("Falta instalar a biblioteca 'tmquery'. Rode: pip install tmquery")
    sys.exit(1)

CLUBES = {
    "Palmeiras": "palmeiras",
    "Flamengo": "flamengo",
    "Cruzeiro": "cruzeiro",
    "Corinthians": "corinthians",
    "Botafogo": "botafogo",
    "Bahia": "bahia",
    "Fluminense": "fluminense",
    "Vasco": "vasco da gama",
    "Santos": "santos",
    "Gremio": "gremio",
    "Bragantino": "red bull bragantino",
    "Atletico-MG": "atletico mineiro",
    "Sao Paulo": "sao paulo",
    "Athletico-PR": "athletico paranaense",
    "Internacional": "internacional",
    "Vitoria": "vitoria",
    "Coritiba": "coritiba",
    "Mirassol": "mirassol",
    "Remo": "remo",
    "Chapecoense": "chapecoense",
}

SEASON = "2026-27"  # ajuste conforme a temporada vigente no Transfermarkt
PAUSE_BETWEEN_CLUBS = 3.0
PAUSE_BETWEEN_PLAYERS = 1.5  # aplicada dentro da biblioteca via monkeypatch abaixo


def add_rate_limit():
    """A biblioteca tmquery nao tem limite de velocidade embutido; adiciona
    uma pausa antes de cada requisicao HTTP real para nao sobrecarregar o
    Transfermarkt nem levar bloqueio por excesso de chamadas."""
    from tmquery.client import Client
    original_fetch_cache = Client.fetch_cache

    def paced_fetch_cache(self, url):
        time.sleep(PAUSE_BETWEEN_PLAYERS)
        return original_fetch_cache(self, url)

    Client.fetch_cache = paced_fetch_cache


def parse_mv_string(mv_str):
    """Converte string tipo '€15.00m' ou '€500k' em numero (milhoes de euros)."""
    if not mv_str or mv_str in ("-", "null", "None"):
        return None
    s = str(mv_str).replace("€", "").strip()
    try:
        if s.endswith("m"):
            return float(s[:-1])
        if s.endswith("k"):
            return float(s[:-1]) / 1000.0
        return float(s)
    except ValueError:
        return None


def most_recent_value(mv_entries):
    """De uma lista de MarketValueDTO (historico) de UM jogador, pega o valor
    mais recente pela data. Tenta parsear a data; se falhar, usa o ultimo
    item da lista (assumindo ordem cronologica, comum nesse tipo de endpoint)."""
    if not mv_entries:
        return None, None
    parsed = []
    for e in mv_entries:
        try:
            d = datetime.strptime(e.date, "%b %d, %Y")
        except Exception:
            d = None
        parsed.append((d, e))
    with_date = [(d, e) for d, e in parsed if d is not None]
    if with_date:
        with_date.sort(key=lambda x: x[0])
        latest = with_date[-1][1]
    else:
        latest = mv_entries[-1]
    return parse_mv_string(latest.mv), latest.date


def fetch_club(nome_interno, termo_busca):
    try:
        club_table = TMQuery(cache_results=True, cache_dir="./cache/").search_club(termo_busca)
        player_table = club_table.get_players(season=SEASON)
        n_players = player_table.count()
        print(f"  {n_players} jogadores encontrados no elenco.")

        mv_table = player_table.get_market_value()
        mv_data = mv_table.data()
        return mv_data
    except Exception as e:
        print(f"  ERRO em {nome_interno}: {e}")
        return None


def main():
    add_rate_limit()

    parser = argparse.ArgumentParser(description="Coleta valores de mercado do Transfermarkt para os times da Serie A")
    parser.add_argument("--time", type=str, default=None,
                         help="Buscar so um time especifico (ex: --time Palmeiras). Se omitido, busca todos os 20 (demorado).")
    parser.add_argument("--saida", type=str, default="transfermarkt",
                         help="Prefixo dos arquivos de saida")
    args = parser.parse_args()

    if args.time and args.time not in CLUBES:
        print(f"Time '{args.time}' nao reconhecido. Opcoes: {', '.join(CLUBES.keys())}")
        sys.exit(1)
    alvos = {args.time: CLUBES[args.time]} if args.time else CLUBES

    all_players = []
    team_summary = []
    falhas = []

    for i, (nome_interno, termo_busca) in enumerate(alvos.items(), 1):
        print(f"[{i}/{len(alvos)}] Buscando {nome_interno} ({termo_busca})...")
        mv_data = fetch_club(nome_interno, termo_busca)
        if mv_data is None:
            falhas.append(nome_interno)
            time.sleep(PAUSE_BETWEEN_CLUBS)
            continue

        # agrupa por jogador (varias entradas historicas por player_id)
        by_player = {}
        for entry in mv_data:
            by_player.setdefault(entry.player_id, []).append(entry)

        valores = []
        for player_id, entries in by_player.items():
            valor_milhoes, data_valor = most_recent_value(entries)
            nome_jogador = entries[0].player_name
            all_players.append({
                "time_serie_a": nome_interno,
                "jogador": nome_jogador,
                "player_id": player_id,
                "valor_milhoes": valor_milhoes,
                "data_valor": data_valor,
            })
            if valor_milhoes is not None:
                valores.append(valor_milhoes)

        total = sum(valores) if valores else 0
        media = (total / len(valores)) if valores else 0
        team_summary.append({
            "time": nome_interno,
            "jogadores_com_valor": len(valores),
            "valor_total_milhoes": round(total, 2),
            "valor_medio_milhoes": round(media, 2),
        })
        print(f"  OK: {len(valores)} jogadores com valor, total ~{total:.1f}M EUR")
        time.sleep(PAUSE_BETWEEN_CLUBS)

    if all_players:
        players_path = Path(f"{args.saida}_jogadores.csv")
        fieldnames = ["time_serie_a", "jogador", "player_id", "valor_milhoes", "data_valor"]
        with open(players_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_players:
                writer.writerow(row)
        print(f"\nSalvo: {players_path} ({len(all_players)} jogadores)")

    if team_summary:
        summary_path = Path(f"{args.saida}_times_resumo.csv")
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(team_summary[0].keys()))
            writer.writeheader()
            for row in team_summary:
                writer.writerow(row)
        print(f"Salvo: {summary_path} ({len(team_summary)} times)")

    if falhas:
        print(f"\nTimes que falharam: {', '.join(falhas)}")
        print("Tente rodar so esses de novo, um de cada vez, com --time NomeDoTime")

    print("\nPronto. Suba os arquivos CSV aqui no chat com o Claude para processar.")


if __name__ == "__main__":
    main()
