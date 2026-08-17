"""
Sincroniza os blocos do index.html que estavam congelados na mao.

POR QUE ISSO EXISTE
-------------------
O index.html tem varios blocos de dados embutidos. Alguns ja tinham gerador
(PLAYERS pelo build_index.py, DATA pelo update_next_matches_dynamic.py,
MEU_TIME_HIST pelo build_meu_time_tab.py). Tres NAO tinham gerador nenhum e
foram ficando para tras sem que nada acusasse:

  1. var RATINGS -- os ratings do Dixon-Coles que a aba PREDITOR usa. Este era
     o grave. Enquanto a aba "Proximos Jogos" lia team_ratings_calibrado.json
     atualizado a cada rodada, o Preditor rodava um blob congelado: o ataque do
     Atletico-MG diferia em +0,47 na escala log (cerca de 1,6x), o do Flamengo
     em -0,24. As duas abas do mesmo site respondiam coisas diferentes sobre o
     mesmo jogo, e a aba errada era a que abre primeiro.

  2. var SNAPSHOT -- os tres primeiros colocados no cabecalho. Comentario no
     codigo: "as of 2026-07-27, pos-rodada 20". Ficou ali enquanto o site
     publicava a rodada 23.

  3. O rotulo "RODADA N" do cabecalho. O set_round_label() do lib/index_data.py
     so trocava o titulo "Proximos jogos - Rodada N" e um comentario de JS; o
     cabecalho principal nao era tocado por ninguem.

Todos os tres sao derivaveis de arquivos que o pipeline ja mantem em dia. Este
script deriva e grava, e o verificar_integridade.py passou a conferir se o que
esta no HTML bate com os dados -- para nao congelar de novo em silencio.

Uso:
    python scripts/sincronizar_index.py --repo-dir .
    python scripts/sincronizar_index.py --repo-dir . --dry-run
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.fixtures import load_fixtures
from lib.teams import canonical_or_none

VITORIA, EMPATE = 3, 1


class SincronizacaoError(RuntimeError):
    pass


def classificacao(repo, season="2026"):
    """Tabela da temporada a partir dos resultados ja ingeridos."""
    caminho = repo / "data" / "matches_2012_2026.csv"
    tab = defaultdict(lambda: {"pts": 0, "j": 0, "sg": 0, "gp": 0})
    with caminho.open(encoding="utf-8") as f:
        for m in csv.DictReader(f):
            if m["season"] != season or not m["home_goals"]:
                continue
            casa, fora = canonical_or_none(m["home_team"]), canonical_or_none(m["away_team"])
            if casa is None or fora is None:
                continue
            gc, gf = int(m["home_goals"]), int(m["away_goals"])
            for time, pro, contra in ((casa, gc, gf), (fora, gf, gc)):
                t = tab[time]
                t["j"] += 1
                t["gp"] += pro
                t["sg"] += pro - contra
                t["pts"] += VITORIA if pro > contra else (EMPATE if pro == contra else 0)
    # Criterio da CBF: pontos, vitorias, saldo, gols pro. Vitorias nao estao
    # somadas aqui, entao usamos pontos > saldo > gols pro -- suficiente para
    # o top 3 do cabecalho e explicito sobre o que faz.
    return sorted(tab.items(), key=lambda kv: (-kv[1]["pts"], -kv[1]["sg"], -kv[1]["gp"]))


def bloco_ratings(repo):
    caminho = repo / "data" / "team_ratings_calibrado.json"
    if not caminho.exists():
        caminho = repo / "data" / "team_ratings_final_v2.json"
    doc = json.loads(caminho.read_text(encoding="utf-8"))
    return json.dumps({"home_advantage_log": doc["home_advantage_log"],
                       "teams": doc["teams"]}, ensure_ascii=False), caminho.name


def bloco_elo(repo):
    """O elo_odds_final.json guarda o modelo num formato proprio; converte."""
    caminho = repo / "data" / "elo_odds_final.json"
    if not caminho.exists():
        return None, None
    d = json.loads(caminho.read_text(encoding="utf-8"))
    return json.dumps({
        "omega": d["omega_home_advantage"],
        "classes": d["logit_classes"],
        "coef": d["logit_coef"],
        "intercept": d["logit_intercept"],
        "ratings": d["team_ratings"],
    }, ensure_ascii=False), caminho.name


def _substituir(html, padrao, novo, rotulo):
    novo_html, n = re.subn(padrao, lambda _: novo, html, count=1, flags=re.DOTALL)
    if n != 1:
        raise SincronizacaoError(
            f"nao encontrei o bloco {rotulo} no index.html -- o arquivo mudou de "
            f"forma? Nada foi gravado.")
    return novo_html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo_dir).resolve()
    index_path = repo / "index.html"
    html = index_path.read_text(encoding="utf-8")

    rodada, _, _ = load_fixtures(repo / "data" / "proximos_jogos.json")

    # 1. Ratings do Dixon-Coles usados pela aba Preditor
    ratings_js, fonte_ratings = bloco_ratings(repo)
    html = _substituir(html, r"var RATINGS = \{.*?\};",
                       f"var RATINGS = {ratings_js};", "var RATINGS")
    print(f"RATINGS  <- data/{fonte_ratings}")

    # 2. Elo-Odds
    elo_js, fonte_elo = bloco_elo(repo)
    if elo_js:
        html = _substituir(html, r"var ELO = \{.*?\};",
                           f"var ELO = {elo_js};", "var ELO")
        print(f"ELO      <- data/{fonte_elo}")

    # 3. Top 3 do cabecalho
    tabela = classificacao(repo)
    top3 = tabela[:3]
    linhas = ",\n".join(
        '    {pos:%d, team:"%s", pts:%d}' % (i, t, d["pts"])
        for i, (t, d) in enumerate(top3, 1))
    jogos = top3[0][1]["j"] if top3 else 0
    # Substitui SO o array, nunca o comentario acima dele. A primeira versao
    # engolia o comentario junto e o reescrevia -- o que fazia o regex nao casar
    # na execucao seguinte e o script morrer com "nao encontrei o bloco". Um
    # gerador que so funciona uma vez e pior que nao ter gerador.
    html = _substituir(html, r"var SNAPSHOT = \[.*?\n  \];",
                       f"var SNAPSHOT = [\n{linhas}\n  ];", "var SNAPSHOT")
    print("SNAPSHOT <- data/matches_2012_2026.csv: "
          + ", ".join(f"{i}o {t} {d['pts']}pts" for i, (t, d) in enumerate(top3, 1))
          + f" ({jogos} jogos)")

    # 4. Rotulo da rodada no cabecalho
    html, n = re.subn(r"(<div class=\"bh-sub\">[^<]*?&middot; RODADA )\d+",
                      rf"\g<1>{rodada}", html, count=1)
    if n != 1:
        raise SincronizacaoError("nao encontrei o rotulo 'RODADA N' no cabecalho")
    print(f"Cabecalho <- rodada {rodada}")

    if args.dry_run:
        print("\n[DRY-RUN] Nada gravado.")
        return 0
    index_path.write_text(html, encoding="utf-8")
    print(f"\n[OK] index.html sincronizado (rodada {rodada}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SincronizacaoError as e:
        print(f"[ERRO] {e}")
        sys.exit(1)
