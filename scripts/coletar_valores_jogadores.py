"""
Coletor de valor de mercado E ESTATISTICAS DE DESEMPENHO por jogador
RODAR NO SEU COMPUTADOR, NAO no Claude.

Isso complementa o processar_transfermarkt_scraper.py (que ja pega o valor
total do elenco por time). Aqui vamos ate o nivel de jogador individual,
com dois dados por jogador: valor de mercado (historico, usamos o mais
recente) e estatisticas de desempenho (endpoint extra, adicionado a partir
de uma dica de um tutorial em video -- ver nota abaixo).

POR QUE PRECISA DE DOIS PASSOS DIFERENTES
------------------------------------------
O transfermarkt-scraper (dcaribou) NAO tem um crawler pronto que ja traga o
valor de mercado de cada jogador -- confirmei isso olhando o projeto irmao
transfermarkt-datasets, que documenta o modelo de dados: valor de mercado
individual mora numa tabela separada (`player_valuations`), alimentada por
uma chamada extra num endpoint dedicado do Transfermarkt (o mesmo que a
tmquery usava: /ceapi/marketValueDevelopment/graph/{id}).

Entao o fluxo completo e:
  1. transfermarkt-scraper: clubs -> players   (perfil de cada jogador, SEM valor)
  2. Este script aqui: le o players.json e busca, PARA CADA JOGADOR:
     - valor de mercado, no mesmo endpoint de sempre
     - estatisticas de desempenho, num endpoint novo: /ceapi/player/{id}/performance
       (confirmado num tutorial em video de scraping do Transfermarkt --
       a estrutura exata da resposta ainda nao foi validada por nos; o
       script tenta extrair os totais mais comuns e, se nao conseguir,
       guarda o JSON bruto na coluna 'performance_raw' pra eu ajustar o
       parser depois, sem voce precisar rodar tudo de novo).

Isso dobra o numero de chamadas por jogador (~1000+ no total pros 20 times),
     pode levar 15-25 minutos e precisa ser educado com o servidor).

PASSO 1 -- gerar o players.json (precisa do transfermarkt-scraper instalado,
ver coletar_transfermarkt.py / processar_transfermarkt_scraper.py de antes)
--------------------------------------------------------------------------
    echo '{"type":"competition","href":"/campeonato-brasileiro-serie-a/startseite/wettbewerb/BRA1","competition_type":"first_tier"}' \\
        | python -m tfmkt clubs --season 2026 \\
        | python -m tfmkt players > brasileirao_jogadores_2026.json

PASSO 2 -- rodar este script (so precisa de 'requests', sem tmquery nem tfmkt)
--------------------------------------------------------------------------
    pip install requests
    python coletar_valores_jogadores.py brasileirao_jogadores_2026.json

Gera "valores_por_jogador.csv", pronto pra subir aqui no chat.
"""

import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("Falta instalar a biblioteca 'requests'. Rode: pip install requests")
    sys.exit(1)

BASE_URL = "https://www.transfermarkt.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
PAUSE_SECONDS = 1.5
MAX_RETRIES = 3


def extract_player_id(href_or_id):
    """O href de um jogador termina em .../profil/spieler/123456 -- extrai o
    numero. Se ja vier so o numero, devolve como esta."""
    if href_or_id is None:
        return None
    s = str(href_or_id)
    match = re.search(r"(\d+)\s*$", s)
    return match.group(1) if match else None


def parse_mv_string(mv_str):
    """Converte '€15.00m' / '€500k' / numero puro em milhoes de euros."""
    if mv_str is None:
        return None
    if isinstance(mv_str, (int, float)):
        return round(mv_str / 1_000_000, 2) if mv_str > 10000 else round(mv_str, 2)
    s = str(mv_str).replace("€", "").strip()
    try:
        if s.endswith("m"):
            return round(float(s[:-1]), 2)
        if s.endswith("k"):
            return round(float(s[:-1]) / 1000.0, 2)
        return round(float(s), 2)
    except ValueError:
        return None


def fetch_market_value_history(player_id):
    """Busca o historico de valor de mercado de um jogador. Retorna a
    entrada MAIS RECENTE (data mais alta) como o valor 'atual'."""
    url = f"{BASE_URL}/ceapi/marketValueDevelopment/graph/{player_id}"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                entries = data.get("list", [])
                if not entries:
                    return None, None
                # tenta ordenar por data; se falhar, usa a ultima da lista
                parsed = []
                for e in entries:
                    try:
                        d = datetime.strptime(e["datum_mw"], "%b %d, %Y")
                    except Exception:
                        d = None
                    parsed.append((d, e))
                with_date = [(d, e) for d, e in parsed if d is not None]
                if with_date:
                    with_date.sort(key=lambda x: x[0])
                    latest = with_date[-1][1]
                else:
                    latest = entries[-1]
                return parse_mv_string(latest.get("mw")), latest.get("datum_mw")
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(2)
    print(f"    falhou (id={player_id}): {last_err}")
    return None, None


# guarda se ja imprimimos um exemplo de estrutura bruta (so uma vez, pra
# nao poluir a saida com centenas de prints iguais)
_performance_sample_printed = {"done": False}


def fetch_performance(player_id):
    """Busca estatisticas de desempenho de um jogador no endpoint
    /ceapi/player/{id}/performance. Estrutura CONFIRMADA (recebida de uma
    execucao real): uma LISTA de objetos, um por competicao/temporada, com
    campos como 'nameSeason', 'gamesPlayed', 'goalsScored', 'assists',
    'possibleGames', 'yellowCards', 'redCards' etc.

    Calculamos dois agregados:
    - temporada atual (nameSeason mais recente presente), somado entre
      todas as competicoes daquela temporada (Serie A, Copa do Brasil etc)
    - carreira (soma de tudo, todas as temporadas e competicoes)."""
    url = f"{BASE_URL}/ceapi/player/{player_id}/performance"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()

                if not _performance_sample_printed["done"]:
                    print("\n  --- Exemplo bruto do endpoint de desempenho (so uma vez) ---")
                    print("  " + json.dumps(data)[:500])
                    print("  --- fim do exemplo ---\n")
                    _performance_sample_printed["done"] = True

                def to_num(v):
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        return 0

                # formato real: lista direta de entradas por competicao/temporada
                if isinstance(data, list) and data:
                    entries = data
                elif isinstance(data, dict):
                    entries = data.get("list") or data.get("data") or []
                else:
                    entries = []

                if not entries:
                    return None, None, None, None, None, None, (json.dumps(data)[:500] if not isinstance(data, list) else None)

                jogos_carreira = sum(to_num(x.get("gamesPlayed")) for x in entries)
                gols_carreira = sum(to_num(x.get("goalsScored")) for x in entries)
                assist_carreira = sum(to_num(x.get("assists")) for x in entries)

                temporadas = [x.get("nameSeason") for x in entries if x.get("nameSeason")]
                temporada_atual = max(temporadas, key=lambda s: str(s)) if temporadas else None
                atual = [x for x in entries if x.get("nameSeason") == temporada_atual] if temporada_atual else []
                jogos_temp = sum(to_num(x.get("gamesPlayed")) for x in atual) if atual else None
                gols_temp = sum(to_num(x.get("goalsScored")) for x in atual) if atual else None
                assist_temp = sum(to_num(x.get("assists")) for x in atual) if atual else None

                return jogos_temp, gols_temp, assist_temp, jogos_carreira, gols_carreira, assist_carreira, None

            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(2)
    print(f"    performance falhou (id={player_id}): {last_err}")
    return None, None, None, None, None, None, None


def slug_to_name(href):
    """Deriva um nome legivel a partir do slug do href, ex:
    '/ayoze-perez/profil/spieler/246968' -> 'Ayoze Perez' (fallback quando
    nao ha campo de nome explicito no JSON)."""
    if not href:
        return "?"
    parts = str(href).strip("/").split("/")
    if not parts:
        return "?"
    return parts[0].replace("-", " ").title()


def load_players(path):
    """Le o players.json (uma linha JSON por jogador, formato do
    transfermarkt-scraper). Campos confirmados direto no repositorio oficial
    (samples/players.json): 'type', 'href', 'name_in_home_country',
    'position', 'current_club' (um dict com 'href', nao uma string)."""
    players = []
    total_lines = 0
    tipo_counts = {}
    primeiras_linhas_brutas = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            if len(primeiras_linhas_brutas) < 3:
                primeiras_linhas_brutas.append(line)
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            tipo = obj.get("type", "SEM_TIPO")
            tipo_counts[tipo] = tipo_counts.get(tipo, 0) + 1
            if tipo != "player":
                continue

            href = obj.get("href") or obj.get("id") or obj.get("player_id")
            nome = (
                obj.get("name")
                or obj.get("name_in_home_country")
                or obj.get("player_name")
                or obj.get("pretty_name")
                or slug_to_name(href)
            )
            current_club = obj.get("current_club")
            if isinstance(current_club, dict):
                clube = current_club.get("name") or current_club.get("href") or "?"
            else:
                clube = current_club or obj.get("club_name") or obj.get("club") or "?"
            posicao = obj.get("position") or obj.get("main_position") or "?"

            player_id = extract_player_id(href)
            if player_id:
                players.append({"nome": nome, "clube": clube, "posicao": posicao, "player_id": player_id})

    if not players:
        print("\n--- DIAGNOSTICO (nenhum jogador valido encontrado) ---")
        print(f"Total de linhas nao-vazias no arquivo: {total_lines}")
        print(f"Contagem por 'type': {tipo_counts if tipo_counts else '(nenhum objeto JSON valido foi lido)'}")
        if primeiras_linhas_brutas:
            print("Primeiras linhas brutas do arquivo (pra conferir o formato):")
            for i, l in enumerate(primeiras_linhas_brutas, 1):
                print(f"  linha {i}: {l[:300]}")
        else:
            print("O arquivo esta vazio.")
        print("--- FIM DO DIAGNOSTICO ---\n")
        print("Me manda esse diagnostico (ou o proprio arquivo .json) que eu ajusto o parser certinho.")

    return players


def main():
    if len(sys.argv) < 2:
        print("Uso: python coletar_valores_jogadores.py brasileirao_jogadores_2026.json")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Arquivo nao encontrado: {path}")
        sys.exit(1)

    players = load_players(path)
    print(f"{len(players)} jogadores encontrados no arquivo.")
    if not players:
        print("Nenhum jogador valido (confira se o JSON tem campo de href/id por jogador).")
        sys.exit(1)

    print(f"Estimativa de tempo: ~{len(players) * PAUSE_SECONDS * 2 / 60:.0f} minutos "
          f"(2 chamadas por jogador agora: valor de mercado + desempenho).\n")

    results = []
    falhas = []
    for i, p in enumerate(players, 1):
        print(f"[{i}/{len(players)}] {p['nome']} ({p['clube']})...")
        valor, data_valor = fetch_market_value_history(p["player_id"])
        time.sleep(0.5)
        (jogos_temp, gols_temp, assist_temp,
         jogos_carreira, gols_carreira, assist_carreira,
         performance_raw) = fetch_performance(p["player_id"])
        if valor is None:
            falhas.append(p["nome"])
        results.append({
            "nome": p["nome"],
            "clube": p["clube"],
            "posicao": p["posicao"],
            "player_id": p["player_id"],
            "valor_milhoes": valor,
            "data_valor": data_valor,
            "jogos_temporada": jogos_temp,
            "gols_temporada": gols_temp,
            "assistencias_temporada": assist_temp,
            "jogos_carreira": jogos_carreira,
            "gols_carreira": gols_carreira,
            "assistencias_carreira": assist_carreira,
            "performance_raw": performance_raw,
        })
        time.sleep(PAUSE_SECONDS)

    import csv
    out_path = Path("valores_por_jogador.csv")
    fieldnames = ["nome", "clube", "posicao", "player_id", "valor_milhoes", "data_valor",
                  "jogos_temporada", "gols_temporada", "assistencias_temporada",
                  "jogos_carreira", "gols_carreira", "assistencias_carreira", "performance_raw"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"\nSalvo: {out_path} ({len(results)} jogadores, {len(falhas)} falhas)")
    if falhas:
        print(f"Falharam: {', '.join(falhas[:20])}" + (" ..." if len(falhas) > 20 else ""))
    print("\nPronto. Suba o CSV aqui no chat com o Claude para eu processar.")


if __name__ == "__main__":
    main()
