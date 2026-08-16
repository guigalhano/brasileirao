"""
Atualiza data/proximos_jogos.json com os confrontos da rodada atual, direto
da API do Cartola (GET /partidas).

POR QUE ISSO EXISTE
-------------------
Era a ultima peca manual do pipeline, e a que travava tudo. O
proximos_jogos.json e a fonte unica de verdade dos confrontos (ver
lib/fixtures.py), mas ninguem o atualizava sozinho: o workflow diario
recalculava probabilidades, refazia analises e publicava -- sempre para a
MESMA rodada, ate alguem editar o JSON na mao. Um site que atualiza todo dia
e fica parado na rodada 23 e pior que um site que nao atualiza, porque
parece vivo.

O /partidas devolve a rodada corrente e os 10 jogos com id de clube e data.
E a mesma API que o mercado ja usa e que sabemos responder do GitHub Actions.

CUIDADO DELIBERADO: so troca a rodada quando a nova esta COMPLETA (10 jogos,
20 times distintos, todos mapeados). Publicar meia rodada e o defeito que
lib/fixtures.py e verificar_integridade.py existem para impedir -- este
script nao vai ser a porta de entrada dele. Se algo nao fechar, o arquivo
antigo fica como esta e o script sai com erro.

Uso:
    python scripts/atualizar_confrontos_cartola.py
    python scripts/atualizar_confrontos_cartola.py --dry-run
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.teams import canonical_or_none

BASE_URL = "https://api.cartolafc.globo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DESTINO = REPO_ROOT / "data" / "proximos_jogos.json"

CLUBE_ID_TO_ABBR = {
    2305: "MIR", 262: "FLA", 263: "BOT", 264: "COR", 265: "BAH", 266: "FLU",
    267: "VAS", 275: "PAL", 276: "SAO", 277: "SAN", 280: "RBB", 282: "CAM",
    283: "CRU", 284: "GRE", 285: "INT", 287: "VIT", 293: "CAP", 294: "CFC",
    315: "CHA", 364: "REM",
}
DIAS = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]
JOGOS_POR_RODADA = 10


def buscar_partidas():
    resp = requests.get(f"{BASE_URL}/partidas", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_data(txt):
    """A API manda 'YYYY-MM-DD HH:MM:SS' (as vezes com T no lugar do espaco)."""
    if not txt:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(txt.strip()[:19], fmt)
        except ValueError:
            continue
    return None


def montar(doc):
    """Converte o /partidas no formato do proximos_jogos.json. Erros -> lista."""
    problemas = []
    rodada = doc.get("rodada")
    if not rodada:
        problemas.append("resposta sem o campo 'rodada'")
    partidas = doc.get("partidas") or []
    if len(partidas) != JOGOS_POR_RODADA:
        problemas.append(f"{len(partidas)} partidas na resposta, esperava "
                         f"{JOGOS_POR_RODADA}")

    marcados = []   # (datetime, jogo) -- pareado, pra ordenar sem perder o vinculo
    for i, p in enumerate(partidas, 1):
        casa = CLUBE_ID_TO_ABBR.get(p.get("clube_casa_id"))
        fora = CLUBE_ID_TO_ABBR.get(p.get("clube_visitante_id"))
        if casa is None or fora is None:
            problemas.append(f"jogo #{i}: clube_id nao mapeado "
                             f"({p.get('clube_casa_id')} x {p.get('clube_visitante_id')})")
            continue
        # Passa pelo canonical do repo: se um dia a abreviacao mudar, quebra
        # aqui e nao la na frente com meia rodada publicada.
        h, a = canonical_or_none(casa), canonical_or_none(fora)
        if h is None or a is None:
            problemas.append(f"jogo #{i}: abreviacao desconhecida ({casa} x {fora})")
            continue
        dt = parse_data(p.get("partida_data"))
        if dt is None:
            problemas.append(f"jogo #{i}: data invalida ({p.get('partida_data')!r})")
            continue
        marcados.append((dt, {"home": h, "away": a, "day": DIAS[dt.weekday()],
                              "time": dt.strftime("%H:%M")}))

    times = [t for _, j in marcados for t in (j["home"], j["away"])]
    if len(set(times)) != len(times):
        repetidos = sorted({t for t in times if times.count(t) > 1})
        problemas.append(f"time em mais de um jogo: {repetidos}")

    if problemas:
        return None, problemas

    marcados.sort(key=lambda par: par[0])
    return {
        "rodada": int(rodada),
        "data_inicio": marcados[0][0].strftime("%d/%m/%Y"),
        "data_fim": marcados[-1][0].strftime("%d/%m/%Y"),
        "jogos": [j for _, j in marcados],
    }, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    atual = json.loads(DESTINO.read_text(encoding="utf-8")) if DESTINO.exists() else {}
    print(f"Local: rodada {atual.get('rodada', '?')} "
          f"({len(atual.get('jogos', []))} jogos)")

    print(f"Buscando {BASE_URL}/partidas ...")
    try:
        doc = buscar_partidas()
    except Exception as e:
        print(f"ERRO ao buscar as partidas: {e}")
        return 1

    novo, problemas = montar(doc)
    if problemas:
        print("ERRO: a rodada devolvida pela API nao fecha, mantendo o arquivo atual:")
        for p in problemas:
            print(f"    - {p}")
        return 1

    if novo == atual:
        print(f"Rodada {novo['rodada']} ja esta em dia -- nada a fazer.")
        return 0

    print(f"Rodada {novo['rodada']} ({novo['data_inicio']} - {novo['data_fim']}), "
          f"{len(novo['jogos'])} jogos:")
    for j in novo["jogos"]:
        print(f"    {j['day']:8} {j['time']}  {j['home']:14} x {j['away']}")

    if args.dry_run:
        print("\n[DRY-RUN] Nada gravado.")
        return 0

    DESTINO.write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print(f"\n[OK] {DESTINO.name} atualizado para a rodada {novo['rodada']}.")
    if atual.get("rodada") and novo["rodada"] != atual["rodada"]:
        print(f"[!] A rodada mudou ({atual['rodada']} -> {novo['rodada']}): as "
              f"analises dos confrontos precisam ser refeitas na sequencia "
              f"(generate_advanced_analytics.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
