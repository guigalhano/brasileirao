"""
Leitura e escrita do array `var DATA = [...]` do index.html, com MERGE.

POR QUE ISSO EXISTE
-------------------
O update_next_matches_dynamic.py fazia isto:

    new_html = html[:inicio] + f"var DATA = {json_str};" + html[fim:]

Sobrescrita cega. Todo campo que nao fosse recalculado por aquele script
-- analysis, analysis_grid, forecast, matchup, market, odds -- era apagado.

Foi assim que a aba de analises do site morreu no commit b69d041: os 10
jogos tinham analysis e analysis_grid preenchidos, uma atualizacao de
confrontos rodou, e o index.html passou a ter so
{home, away, day, time, model, xg}. No front, `if(f.analysis_grid)` nunca
mais foi verdadeiro, entao o botao "+ VER 7 ANALISES COMPLETAS" nem chegava
a ser criado -- a aba nao ficou vazia, ela sumiu.

E como o workflow diario do GitHub Actions roda esse script, a aba era
destruida de novo a cada execucao, mesmo que alguem a reconstruisse na mao.

Regra: escrita no DATA e sempre merge por chave home|away. Quem calcula
probabilidade atualiza model/xg e nao encosta no resto.
"""
import json
import re
from pathlib import Path

from .teams import canonical

_START = "var DATA = ["
# Campos que cada produtor "possui". Quem nao esta aqui e preservado como veio.
CAMPOS_MODELO = ("model", "xg")
CAMPOS_ANALISE = ("analysis", "analysis_grid", "forecast", "matchup", "value_betting")
CAMPOS_MERCADO = ("market", "odds")


class IndexDataError(RuntimeError):
    pass


def _localizar(html):
    inicio = html.find(_START)
    if inicio == -1:
        raise IndexDataError("Nao encontrei 'var DATA = [' no index.html")
    fim = html.find("];", inicio)
    if fim == -1:
        raise IndexDataError("Nao encontrei o fechamento '];' do array DATA")
    return inicio, fim + 1


def read_data(index_path):
    """Devolve a lista de jogos do DATA atual do index.html."""
    html = Path(index_path).read_text(encoding="utf-8")
    inicio, fim = _localizar(html)
    bruto = html[inicio + len("var DATA = "):fim]
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        raise IndexDataError(f"DATA do index.html nao e JSON valido: {e}") from None


def _chave(jogo):
    return f"{canonical(jogo['home'])}|{canonical(jogo['away'])}"


def merge_data(existente, novos):
    """Funde `novos` sobre `existente`, preservando campos nao informados.

    A ordem e a dos `novos` (a rodada corrente manda). Um jogo que so existe
    no `existente` e descartado: ele e de uma rodada que ja passou.
    """
    por_chave = {}
    for jogo in existente:
        try:
            por_chave[_chave(jogo)] = dict(jogo)
        except Exception:
            continue  # registro velho com nome fora do canonico: ignora

    saida = []
    preservados = 0
    for novo in novos:
        chave = _chave(novo)
        base = por_chave.get(chave, {})
        herdados = {k: v for k, v in base.items() if k not in novo}
        if herdados:
            preservados += 1
        fundido = {**base, **novo}
        saida.append(fundido)
    return saida, preservados


def write_data(index_path, jogos, *, merge=True):
    """Grava o DATA. Com merge=True (padrao) preserva campos existentes.

    Devolve quantos jogos tiveram algum campo herdado do estado anterior.
    """
    index_path = Path(index_path)
    html = index_path.read_text(encoding="utf-8")
    inicio, fim = _localizar(html)

    if merge:
        atual = json.loads(html[inicio + len("var DATA = "):fim])
        jogos, preservados = merge_data(atual, jogos)
    else:
        preservados = 0

    novo_html = html[:inicio] + f"var DATA = {json.dumps(jogos)};" + html[fim + 1:]
    index_path.write_text(novo_html, encoding="utf-8")
    return preservados


def set_round_label(index_path, rodada):
    """Atualiza o titulo 'Proximos jogos - Rodada N' e o comentario do bloco."""
    index_path = Path(index_path)
    html = index_path.read_text(encoding="utf-8")
    html = re.sub(r"Próximos jogos.*?Rodada \d+",
                  f"Próximos jogos · Rodada {rodada}", html)
    # O comentario do JS ficou congelado em "rodada 19" por varias rodadas.
    html = re.sub(r"(// ---- Próximos jogos \(.*?\), )rodada \d+",
                  rf"\g<1>rodada {rodada}", html)
    index_path.write_text(html, encoding="utf-8")
