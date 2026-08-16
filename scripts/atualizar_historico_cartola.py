"""
Atualiza data/cartola_historico_2026_completo.csv com as rodadas novas ja
encerradas, incrementalmente (nao refaz o arquivo inteiro do zero).

Criado para rodar no GitHub Actions (tem internet irrestrita) OU localmente.
NAO funciona dentro do sandbox do Claude -- o dominio api.cartolafc.globo.com
esta bloqueado la por politica de rede do proprio ambiente. Confirmado que
funciona no Actions: o /atletas/mercado responde normal de la.

O SCHEMA MUDOU E ESTE SCRIPT NAO TINHA ACOMPANHADO (agosto/2026)
----------------------------------------------------------------
O CSV nasceu do dataset publico henriquepgomide/caRtola, com colunas
"atletas.apelido", "atletas.rodada_id", scouts em letra solta ("A", "DS").
Em algum ponto ele foi reescrito para um schema limpo -- atleta_id, nome,
clube, posicao, rodada, pontos, scout_A, scout_DS ... -- e este script
continuou lendo e escrevendo o schema velho.

Resultado: ele quebrava na PRIMEIRA linha util, com
KeyError: 'atletas.rodada_id', antes mesmo de tocar a rede. E como o
workflow diario o chamava com continue-on-error, o GitHub Actions ficava
VERDE todo dia enquanto o historico de scouts congelava na rodada 21.
Tudo que depende de scout -- desarme, media por jogador, pontuacao esperada,
os sinais de defesa -- parou junto, sem nenhum sinal de que tinha parado.

Agora o script le e escreve o schema real do arquivo, e confere isso na
entrada: se as colunas nao forem as esperadas, ele para com erro em vez de
adivinhar.

Uso:
    python scripts/atualizar_historico_cartola.py
    python scripts/atualizar_historico_cartola.py --dry-run
"""
import argparse
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
POSICAO_ID_TO_POS = {1: "GOL", 2: "LAT", 3: "ZAG", 4: "MEI", 5: "ATA", 6: "TEC"}

SCOUTS = ["A", "CA", "CV", "DE", "DP", "DS", "FC", "FD", "FF", "FS", "FT",
          "G", "GC", "GS", "I", "PC", "PP", "PS", "SG", "V"]
COLUNAS = ["atleta_id", "nome", "clube", "posicao", "rodada", "pontos"] + \
          [f"scout_{s}" for s in SCOUTS]


def fetch_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except Exception as e:
        return None, str(e)


def linha_do_atleta(atleta_id, info, rodada):
    """Converte um atleta do /atletas/pontuados/{rodada} para o schema local."""
    scout = info.get("scout") or {}
    linha = {
        "atleta_id": atleta_id,
        "nome": info.get("apelido", ""),
        "clube": CLUBE_ID_TO_ABBR.get(info.get("clube_id"), "?"),
        "posicao": POSICAO_ID_TO_POS.get(info.get("posicao_id"), "?"),
        "rodada": rodada,
        # A API chama de "pontuacao" aqui e de "pontos_num" no /mercado.
        "pontos": info.get("pontuacao", info.get("pontos_num", 0)),
    }
    for s in SCOUTS:
        # Scout ausente = nao aconteceu. O CSV guarda vazio, nao zero, pro
        # arquivo nao triplicar de tamanho -- todo leitor ja trata "" como 0.
        v = scout.get(s)
        linha[f"scout_{s}"] = "" if v in (None, 0) else v
    return linha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="busca e mostra, sem gravar")
    args = ap.parse_args()

    if not HISTORICO_CSV.exists():
        print(f"ERRO: {HISTORICO_CSV} nao encontrado.")
        return 1

    with HISTORICO_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        colunas = reader.fieldnames
        linhas = list(reader)

    # Trava de schema: e exatamente o que faltava antes. Se o arquivo mudar
    # de formato de novo, para aqui com a diferenca na tela, em vez de
    # quebrar com um KeyError obscuro (ou pior, gravar lixo).
    if colunas != COLUNAS:
        print("ERRO: o schema de "
              f"{HISTORICO_CSV.name} nao e o esperado.")
        print(f"  faltando: {sorted(set(COLUNAS) - set(colunas or []))}")
        print(f"  sobrando: {sorted(set(colunas or []) - set(COLUNAS))}")
        return 1

    rodadas = [int(r["rodada"]) for r in linhas if r["rodada"]]
    if not rodadas:
        print(f"ERRO: {HISTORICO_CSV.name} sem nenhuma rodada.")
        return 1
    max_rodada = max(rodadas)
    print(f"Historico local: {len(linhas)} linhas, rodada mais recente {max_rodada}")

    novas = []
    for rodada in range(max_rodada + 1, max_rodada + 1 + MAX_RODADAS_A_FRENTE):
        url = f"{BASE_URL}/atletas/pontuados/{rodada}"
        print(f"Tentando rodada {rodada}: {url}")
        data, err = fetch_json(url)
        time.sleep(PAUSE_SECONDS)
        if err or not data or not data.get("atletas"):
            print(f"  rodada {rodada} indisponivel "
                  f"({err or 'sem atletas, ainda nao encerrada'}) -- parando aqui.")
            break
        atletas = data["atletas"]
        for atleta_id, info in atletas.items():
            novas.append(linha_do_atleta(int(atleta_id), info, rodada))
        print(f"  rodada {rodada}: {len(atletas)} jogadores coletados.")

    if not novas:
        print("\nNenhuma rodada nova encerrada. Nada para adicionar.")
        return 0

    desconhecidos = {(l["clube"], l["posicao"]) for l in novas
                     if l["clube"] == "?" or l["posicao"] == "?"}
    if desconhecidos:
        print(f"[aviso] {len(desconhecidos)} combinacao(oes) de clube/posicao "
              f"nao mapeada(s) -- clube_id ou posicao_id novos na API?")

    rodadas_novas = sorted({l["rodada"] for l in novas})
    if args.dry_run:
        print(f"\n[DRY-RUN] {len(novas)} linhas novas (rodadas {rodadas_novas}). "
              f"Nada gravado.")
        return 0

    with HISTORICO_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
        w.writerows(novas)

    print(f"\n[OK] {len(novas)} linhas novas adicionadas "
          f"(rodadas {rodadas_novas}). Total: {len(linhas) + len(novas)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
