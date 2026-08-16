#!/usr/bin/env python3
"""
Portao de integridade -- roda antes de publicar o site.

POR QUE ISSO EXISTE
-------------------
Todos os defeitos que a auditoria da rodada 23 encontrou tinham a mesma
assinatura: o pipeline terminava com codigo 0 e publicava algo errado.

  - 7 de 20 nomes de time nao casaram, o script imprimiu "[AVISO] pulando"
    e o site foi ao ar com 5 dos 10 jogos;
  - a aba de analises sumiu do index.html e nada acusou;
  - o analytics_advanced.json descrevia confrontos de outra rodada, com
    timestamp recente -- parecia atualizado.

Este script transforma cada um desses casos em falha explicita. Se ele sai
com codigo != 0, NAO publique.

Uso:
    python scripts/verificar_integridade.py --repo-dir .
"""
import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.fixtures import load_fixtures
from lib.index_data import read_data
from lib.pontuacao import (carregar_tabela_oficial, conferir_tabela,
                           recuperar_tabela)
from lib.teams import CANONICAL, check_ratings_cover_canonical

# Quantas rodadas de atraso nos resultados ainda sao toleraveis antes de
# considerar que os ratings estao velhos demais para ir ao ar.
MAX_RODADAS_ATRASO = 2


class Relatorio:
    def __init__(self):
        self.erros, self.avisos = [], []

    def erro(self, msg):
        self.erros.append(msg)

    def aviso(self, msg):
        self.avisos.append(msg)

    def ok(self):
        return not self.erros


def checar_confrontos(repo, rel):
    rodada, fixtures, meta = load_fixtures(repo / "data" / "proximos_jogos.json")
    data = read_data(repo / "index.html")

    esperados = {f"{f['home']}|{f['away']}" for f in fixtures}
    no_site = {f"{d['home']}|{d['away']}" for d in data}

    if len(data) != len(fixtures):
        rel.erro(f"index.html tem {len(data)} jogos, a rodada {rodada} tem {len(fixtures)}")

    faltando = esperados - no_site
    if faltando:
        rel.erro(f"Confrontos ausentes no index.html: {sorted(faltando)}")

    sobrando = no_site - esperados
    if sobrando:
        rel.erro(f"Confrontos no index.html que nao sao da rodada {rodada}: {sorted(sobrando)}")

    for d in data:
        rotulo = f"{d['home']} x {d['away']}"
        for campo in ("model", "xg"):
            if not d.get(campo):
                rel.erro(f"{rotulo}: sem {campo} (rode update_next_matches_dynamic.py)")
        if d.get("model") and abs(sum(d["model"]) - 1.0) > 0.01:
            rel.erro(f"{rotulo}: probabilidades somam {sum(d['model']):.3f}, deveria ser 1.0")
        if not d.get("analysis_grid"):
            rel.erro(f"{rotulo}: sem analysis_grid -- a aba de analises nao vai renderizar "
                     f"(rode generate_advanced_analytics.py)")
        if not d.get("market"):
            rel.aviso(f"{rotulo}: sem odds de mercado (coluna de edge fica vazia)")
    return rodada


def checar_analytics(repo, rodada, rel):
    caminho = repo / "data" / "analytics_advanced.json"
    if not caminho.exists():
        rel.erro("data/analytics_advanced.json nao existe")
        return
    doc = json.loads(caminho.read_text(encoding="utf-8"))
    if doc.get("rodada") != rodada:
        rel.erro(f"analytics_advanced.json e da rodada {doc.get('rodada')}, "
                 f"a atual e {rodada} -- confrontos de outra rodada no site")


def checar_frescor(repo, rodada, rel):
    """O CSV de resultados precisa acompanhar a rodada que estamos prevendo."""
    caminho = repo / "data" / "matches_2012_2026.csv"
    linhas = [r for r in csv.DictReader(caminho.open(encoding="utf-8"))
              if r["season"] == "2026" and r["home_goals"]]
    if not linhas:
        rel.erro("matches_2012_2026.csv sem resultados de 2026")
        return

    por_time = {}
    for r in linhas:
        for t in (r["home_team"], r["away_team"]):
            por_time[t] = por_time.get(t, 0) + 1
    rodadas_com_dados = min(por_time.values()) if por_time else 0
    atraso = (rodada - 1) - rodadas_com_dados

    ultima = max(r["date"] for r in linhas)
    dias = (date.today() - datetime.strptime(ultima, "%Y-%m-%d").date()).days

    if atraso > MAX_RODADAS_ATRASO:
        rel.erro(f"Resultados param na rodada {rodadas_com_dados}, mas estamos prevendo a "
                 f"{rodada} ({atraso} rodadas de atraso, ultimo jogo em {ultima}, "
                 f"{dias} dias atras). Os ratings estao cegos -- rode "
                 f"scripts/ingerir_resultados.py.")
    elif atraso > 0:
        rel.aviso(f"Resultados ate a rodada {rodadas_com_dados}; prevendo a {rodada} "
                  f"({atraso} de atraso, ultimo jogo {ultima})")


def checar_pontuacao_cartola(repo, rel):
    """A tabela que os dados mostram ainda e a tabela oficial do Cartola?

    O Cartola ja reajustou scout no meio do caminho (desarme e defesa
    subiram em temporadas passadas). Se isso acontecer de novo, tudo que
    depende de pontuacao esperada passa a somar peso velho sem reclamar --
    a escalacao continua saindo, so que errada. Aqui isso vira aviso
    explicito com o scout e os dois valores lado a lado.
    """
    caminho = repo / "data" / "cartola_historico_2026_completo.csv"
    if not caminho.exists():
        rel.aviso(f"{caminho.name} nao existe -- pontuacao do Cartola nao conferida")
        return

    hist = list(csv.DictReader(caminho.open(encoding="utf-8")))
    recuperada, diag = recuperar_tabela(hist)
    oficial, doc = carregar_tabela_oficial()

    # Com o filtro de posicao certo a recuperacao e exata. R2 caindo aqui
    # significa scout novo na tabela ou coleta corrompida -- nao passa batido.
    if diag["r2"] < 0.999:
        rel.erro(f"A pontuacao nao se explica pelos scouts (R2={diag['r2']:.4f}, "
                 f"erro medio {diag['erro_medio']:.3f}) -- scout novo na tabela "
                 f"ou historico corrompido")

    for problema in conferir_tabela(recuperada, oficial):
        rel.erro(f"Pontuacao do Cartola mudou: {problema}. Confira "
                 f"{doc['_fonte']} e atualize data/cartola_tabela_pontuacao.json "
                 f"(ultima conferencia: {doc['_conferido_em']})")


def checar_ratings(repo, rel):
    caminho = repo / "data" / "team_ratings_calibrado.json"
    if not caminho.exists():
        caminho = repo / "data" / "team_ratings_final_v2.json"
    ratings = json.loads(caminho.read_text(encoding="utf-8"))["teams"]
    check_ratings_cover_canonical(ratings)
    if len(CANONICAL) != 20:
        rel.erro(f"CANONICAL tem {len(CANONICAL)} times, a Serie A tem 20")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    repo = Path(args.repo_dir).resolve()

    rel = Relatorio()
    try:
        checar_ratings(repo, rel)
        checar_pontuacao_cartola(repo, rel)
        rodada = checar_confrontos(repo, rel)
        checar_analytics(repo, rodada, rel)
        checar_frescor(repo, rodada, rel)
    except Exception as e:
        print(f"[FALHOU] {type(e).__name__}: {e}")
        return 1

    for a in rel.avisos:
        print(f"[aviso] {a}")
    for e in rel.erros:
        print(f"[ERRO]  {e}")

    if rel.ok():
        print(f"\n[OK] Integridade conferida para a rodada {rodada}: "
              f"{len(rel.avisos)} aviso(s), nenhum erro.")
        return 0
    print(f"\n[FALHOU] {len(rel.erros)} erro(s). NAO publique.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
