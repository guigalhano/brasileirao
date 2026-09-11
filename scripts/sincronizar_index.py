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

  3. JOGOS_ATUAIS_APROX -- quantas rodadas a temporada atual ja tem, usado
     pelo mediaAjustada() para decidir quanto peso a media de 2025 ainda
     merece (peso = K/(K+jogos), K=10). O proprio comentario no codigo dizia
     "precisa ser atualizado manualmente a cada nova temporada/rodada", e
     ninguem atualizava: ficou em 18 ate a rodada 26, dando 35,7% de peso a
     2025 quando o certo era 27,8%. Constante que envelhece sozinha e bug com
     data marcada; agora sai do proprio historico.

  4. O rotulo "RODADA N" do cabecalho. O set_round_label() do lib/index_data.py
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
from lib.index_data import read_data
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


def rodadas_jogadas(repo):
    """Quantas rodadas a temporada atual ja tem no historico de scouts."""
    caminho = repo / "data" / "cartola_historico_2026_completo.csv"
    if not caminho.exists():
        return None
    with caminho.open(encoding="utf-8") as f:
        rodadas = {int(r["rodada"]) for r in csv.DictReader(f) if r["rodada"]}
    return max(rodadas) if rodadas else None


def descricao_proximos_jogos(repo, rodada, meta):
    """Texto do painel "Proximos Jogos", derivado do estado real.

    Estava escrito a mao e congelou: descrevia "os 10 jogos da rodada 21
    (29-30/07)" e afirmava que "6 dos 10 ja tem odds reais de mercado",
    listando Botafogo x Gremio e mais tres como pendentes -- enquanto o site
    publicava a rodada 27 e nenhum jogo tinha odds. Numero em prosa envelhece
    igual a numero em constante; a diferenca e que ninguem confere prosa.
    """
    jogos = read_data(repo / "index.html")
    com_odds = [j for j in jogos if j.get("market")]
    periodo = meta.get("data_inicio", "")
    if meta.get("data_fim") and meta["data_fim"] != periodo:
        periodo = f"{periodo} a {meta['data_fim']}"

    texto = (f"Previs&otilde;es do nosso modelo de partidas (Dixon-Coles "
             f"calibrado) pros {len(jogos)} jogos da rodada {rodada}")
    if periodo:
        texto += f" ({periodo})"
    texto += ". "

    if not com_odds:
        texto += ("Nenhum jogo desta rodada tem odds de mercado coletadas ainda, "
                  "ent&atilde;o a coluna de diverg&ecirc;ncia modelo-vs-mercado "
                  "fica vazia &mdash; ela depende do secret ODDS_API_KEY estar "
                  "configurado (veja scripts/atualizar_odds_mercado.py). ")
    elif len(com_odds) == len(jogos):
        texto += ("Todos t&ecirc;m odds reais de mercado, ent&atilde;o mostramos "
                  "tamb&eacute;m a diverg&ecirc;ncia modelo-vs-mercado. ")
    else:
        faltando = [f"{j['home']} x {j['away']}" for j in jogos if not j.get("market")]
        texto += (f"<b>{len(com_odds)} dos {len(jogos)} jogos t&ecirc;m odds reais "
                  f"de mercado</b> &mdash; nesses, mostramos tamb&eacute;m a "
                  f"diverg&ecirc;ncia modelo-vs-mercado. Os outros "
                  f"({', '.join(faltando)}) ainda n&atilde;o tiveram odds abertas "
                  f"pelas casas. ")

    texto += ("Isso n&atilde;o &eacute; recomenda&ccedil;&atilde;o de aposta: como "
              "vimos na aba anterior, diverg&ecirc;ncia grande entre modelo e "
              "mercado tende a refletir erro do modelo mais do que edge real.")
    return texto


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

    rodada, _, meta = load_fixtures(repo / "data" / "proximos_jogos.json")

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

    # 4. Descricao do painel "Proximos Jogos"
    index_path.write_text(html, encoding="utf-8")   # read_data le do disco
    desc = descricao_proximos_jogos(repo, rodada, meta)
    html = index_path.read_text(encoding="utf-8")
    inicio = html.find('id="nextMatchesPanel"')
    if inicio == -1:
        raise SincronizacaoError("nao encontrei o painel nextMatchesPanel")
    ini_desc = html.find('<div class="panel-desc">', inicio)
    fim_desc = html.find("</div>", ini_desc)
    if ini_desc == -1 or fim_desc == -1:
        raise SincronizacaoError("nao encontrei a descricao do painel de proximos jogos")
    html = (html[:ini_desc] + '<div class="panel-desc">' + desc + html[fim_desc:])
    print(f"Descricao do painel <- rodada {rodada}, "
          f"{len([j for j in read_data(index_path) if j.get('market')])} com odds")

    # 5. Peso do historico da temporada anterior (mediaAjustada)
    jogos = rodadas_jogadas(repo)
    if jogos:
        html, n = re.subn(r"(var JOGOS_ATUAIS_APROX = )\d+", rf"\g<1>{jogos}",
                          html, count=1)
        if n != 1:
            raise SincronizacaoError("nao encontrei JOGOS_ATUAIS_APROX no index.html")
        print(f"JOGOS_ATUAIS_APROX <- {jogos} rodadas jogadas "
              f"(peso da temporada 2025: {100 * 10 / (10 + jogos):.0f}%)")

    # 6. Numeros soltos em prosa que descrevem o estado atual. Sao poucos e
    # tem formato fixo, entao da pra derivar em vez de deixar envelhecer:
    # o rotulo do criterio "media" dizia "18 rodadas" na rodada 26, e o texto
    # da base citava "rodada 19" e "569 jogadores" (hoje sao outros numeros).
    n_jogadores = len(re.findall(r"\{name:", html))
    # Contagem de jogos da aba Value Betting, derivada do proprio array dela.
    # Estava escrita a mao ("5508 jogos", "199 jogos de 2026") e envelheceu
    # junto com o array, que so foi estendido em setembro/2026.
    i_vb = html.find('id="panel-valuebet"')
    n_vb = n_vb_2026 = None
    if i_vb != -1:
        m_vb = re.search(r"const DATA = \[", html[i_vb:])
        if m_vb:
            ini_vb = i_vb + m_vb.start()
            datas_vb = re.findall(r'"(20\d\d-\d\d-\d\d)"',
                                  html[ini_vb:html.find("];", ini_vb)])
            n_vb, n_vb_2026 = len(datas_vb), sum(1 for d in datas_vb if d[:4] == "2026")
    substituicoes = [
        (r"(Media da temporada \()\d+( rodadas\))", rf"\g<1>{jogos}\g<2>"),
        (r"(mercado\.json, rodada )\d+", rf"\g<1>{rodada}"),
        (r"(historico completo das )\d+( rodadas ja jogadas)", rf"\g<1>{jogos}\g<2>"),
        (r"(— )\d+( jogadores com pelo menos 1 jogo)", rf"\g<1>{n_jogadores}\g<2>"),
    ]
    if n_vb:
        substituicoes += [
            (r"\d+ jogos(?= &middot; 2012)", f"{n_vb} jogos"),
            (r"(cobrem os )\d+( jogos de 2026)", rf"\g<1>{n_vb_2026}\g<2>"),
        ]
    for padrao, troca in substituicoes:
        html = re.sub(padrao, troca, html)
    print(f"Prosa <- rodada {rodada}, {jogos} rodadas jogadas, "
          f"{n_jogadores} jogadores"
          + (f", Value Betting {n_vb} jogos ({n_vb_2026} de 2026)" if n_vb else ""))

    # 7. Rotulo da rodada no cabecalho
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
