"""
Confrontos da proxima rodada -- fonte unica de verdade.

POR QUE ISSO EXISTE
-------------------
Ate a rodada 23 existiam TRES listas de confrontos no repo, todas
divergentes entre si:

  1. data/proximos_jogos.json                       (a de verdade)
  2. generate_advanced_analytics.py::matches_r22    (hardcoded, rodada errada)
  3. add_analysis_to_matches.py::matches            (hardcoded + textos fixos)

O resultado: a aba de analises do site descrevia Flamengo x Chapecoense e
Palmeiras x Corinthians enquanto a rodada real era Atletico-MG x Gremio e
Fluminense x Palmeiras. Como o gerador rodava e regravava o arquivo, o
timestamp ficava recente e o conteudo continuava errado -- o tipo de bug
que passa despercebido justamente por parecer atualizado.

Regra: qualquer script que precise saber "quais sao os jogos" chama
load_fixtures(). Nenhuma lista de confronto hardcoded em script nenhum.
"""
import json
from pathlib import Path

from .teams import canonical

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_PATH = REPO_ROOT / "data" / "proximos_jogos.json"


class FixturesError(RuntimeError):
    pass


def load_fixtures(path=None):
    """Le a rodada atual. Devolve (rodada:int, jogos:list, meta:dict).

    Cada jogo sai com 'home'/'away' JA canonicos -- se algum nome nao casar,
    canonical() levanta erro e o pipeline para. E de proposito: publicar meia
    rodada e pior do que nao publicar.
    """
    path = Path(path) if path else FIXTURES_PATH
    if not path.exists():
        raise FixturesError(f"Arquivo de confrontos nao encontrado: {path}")

    doc = json.loads(path.read_text(encoding="utf-8"))
    for campo in ("rodada", "jogos"):
        if campo not in doc:
            raise FixturesError(f"{path.name} sem o campo obrigatorio {campo!r}")

    jogos = []
    for i, j in enumerate(doc["jogos"], 1):
        try:
            home = canonical(j["home"], source=f"{path.name} jogo #{i}")
            away = canonical(j["away"], source=f"{path.name} jogo #{i}")
        except KeyError as e:
            raise FixturesError(f"{path.name} jogo #{i} sem o campo {e}") from None
        if home == away:
            raise FixturesError(f"{path.name} jogo #{i}: mandante igual a visitante ({home})")
        jogos.append({
            "home": home,
            "away": away,
            "day": j.get("day", ""),
            "time": j.get("time", ""),
        })

    if not jogos:
        raise FixturesError(f"{path.name} nao tem nenhum jogo")

    escalados = [t for j in jogos for t in (j["home"], j["away"])]
    repetidos = {t for t in escalados if escalados.count(t) > 1}
    if repetidos:
        raise FixturesError(
            f"Times em mais de um jogo na mesma rodada: {sorted(repetidos)}"
        )

    meta = {
        "data_inicio": doc.get("data_inicio", ""),
        "data_fim": doc.get("data_fim", ""),
    }
    return int(doc["rodada"]), jogos, meta


def match_key(home, away):
    """Chave estavel de um confronto, para casar registros entre arquivos."""
    return f"{canonical(home)}|{canonical(away)}"
