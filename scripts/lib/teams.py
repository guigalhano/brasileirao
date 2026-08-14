"""
Nome canonico de time -- fonte unica de verdade.

POR QUE ISSO EXISTE
-------------------
Cada fonte escreve o nome do time de um jeito: a CBF manda "Atletico (MG)",
o Cartola manda "CAM", o football-data.co.uk manda "Atletico-MG", e o
team_ratings_calibrado.json usa "Atletico-MG". Ate a rodada 23 esse
descasamento derrubou metade da rodada sem ninguem perceber: o
update_next_matches_dynamic.py imprimia "[AVISO] ... pulando" e seguia,
publicando 5 dos 10 jogos no site como se estivesse tudo certo.

A regra aqui e o contrario disso: canonical() LEVANTA ERRO em nome
desconhecido. E melhor o pipeline quebrar barulhento do que publicar
meia rodada silenciosamente.

Uso:
    from lib.teams import canonical, UnknownTeamError
    canonical("Atletico (MG)")   -> "Atletico-MG"
    canonical("CAM")             -> "Atletico-MG"
    canonical("Sao Paulo FC")    -> UnknownTeamError (adicione em ALIASES)
"""
import re
import unicodedata

# Os 20 nomes canonicos. Precisam bater EXATAMENTE com as chaves de
# data/team_ratings_calibrado.json -- e o que o modelo Poisson consulta.
CANONICAL = frozenset({
    "Atletico-MG", "Atletico-PR", "Bahia", "Botafogo", "Bragantino",
    "Chapecoense", "Corinthians", "Coritiba", "Cruzeiro", "Flamengo",
    "Fluminense", "Gremio", "Internacional", "Mirassol", "Palmeiras",
    "Remo", "Santos", "Sao Paulo", "Vasco", "Vitoria",
})

# Apelidos por fonte. A chave e o nome JA normalizado (ver _norm):
# sem acento, minusculo, sem sufixo de estado, espacos colapsados.
_ALIASES = {
    # --- Cartola FC (abreviacao oficial da API) ---
    "cam": "Atletico-MG", "cap": "Atletico-PR", "bah": "Bahia",
    "bot": "Botafogo", "rbb": "Bragantino", "cha": "Chapecoense",
    "cor": "Corinthians", "cfc": "Coritiba", "cru": "Cruzeiro",
    "fla": "Flamengo", "flu": "Fluminense", "gre": "Gremio",
    "int": "Internacional", "mir": "Mirassol", "pal": "Palmeiras",
    "rem": "Remo", "san": "Santos", "sao": "Sao Paulo",
    "vas": "Vasco", "vit": "Vitoria",

    # --- CBF / calendario / variacoes comuns ---
    "atletico mineiro": "Atletico-MG",
    "athletico paranaense": "Atletico-PR",
    "atletico paranaense": "Atletico-PR",
    "red bull bragantino": "Bragantino",
    "vasco da gama": "Vasco",
    "gremio": "Gremio", "sao paulo": "Sao Paulo", "vitoria": "Vitoria",
    "internacional": "Internacional", "chapecoense": "Chapecoense",
    "coritiba": "Coritiba", "corinthians": "Corinthians",
    "bragantino": "Bragantino", "vasco": "Vasco",
}

# Casos em que a UF NAO pode ser descartada: e ela que separa os dois times.
# A CBF escreve "Atletico (MG)" e "Athletico (PR)"; sem a UF, "atletico"
# sozinho e ambiguo e resolve-lo por chute foi o que fez a rodada 23 sair
# com Atletico-PR virando Atletico-MG.
_POR_UF = {
    ("atletico", "MG"): "Atletico-MG",
    ("atletico", "PR"): "Atletico-PR",
    ("athletico", "MG"): "Atletico-MG",
    ("athletico", "PR"): "Atletico-PR",
}

# Sufixo de unidade federativa: "Atletico (MG)", "Remo (PA)", "Vitoria-BA".
# O separador antes da UF e OBRIGATORIO. Sem isso o regex comia o final de
# siglas de 3 letras -- "CAM" (Atletico-MG) virava "C" porque termina em "AM"
# (Amazonas), e "CAP" (Atletico-PR) virava "C" por causa de "AP" (Amapa).
_UF = re.compile(r"(?:[\s\-]+|\s*[\(\[])\s*"
                 r"(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|"
                 r"PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)"
                 r"\s*[\)\]]?\s*$", re.IGNORECASE)

# Siglas oficiais do Cartola. Consultadas ANTES de qualquer normalizacao,
# para nao dependerem do strip de UF.
_SIGLAS = {
    "CAM": "Atletico-MG", "CAP": "Atletico-PR", "BAH": "Bahia",
    "BOT": "Botafogo", "RBB": "Bragantino", "CHA": "Chapecoense",
    "COR": "Corinthians", "CFC": "Coritiba", "CRU": "Cruzeiro",
    "FLA": "Flamengo", "FLU": "Fluminense", "GRE": "Gremio",
    "INT": "Internacional", "MIR": "Mirassol", "PAL": "Palmeiras",
    "REM": "Remo", "SAN": "Santos", "SAO": "Sao Paulo",
    "VAS": "Vasco", "VIT": "Vitoria",
}


class UnknownTeamError(ValueError):
    """Nome de time que nao casou com nenhum canonico nem apelido conhecido."""


def _split_uf(name):
    """Devolve (base_normalizada, uf) -- a UF e devolvida, nao descartada."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.strip()
    m = _UF.search(s)
    uf = None
    if m:
        uf = re.sub(r"[^A-Za-z]", "", m.group(0)).upper()
        s = s[:m.start()]
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower(), uf


def _norm(name):
    """So a base normalizada (sem UF). Use _split_uf quando a UF importar."""
    return _split_uf(name)[0]


# Nome canonico responde por si mesmo por match EXATO (so caixa ignorada).
# Nao da pra passar canonico pelo _norm: "Atletico-MG" e "Atletico-PR" viram
# os dois "atletico" (o strip de UF come "-MG" e "-PR"), e como CANONICAL e um
# frozenset, qual dos dois venceria mudava de execucao pra execucao.
_EXATOS = {c.lower(): c for c in CANONICAL}

# Canonicos tambem respondem pela base normalizada ("Remo (PA)" -> "remo"),
# EXCETO quando dois canonicos compartilham a mesma base: "Atletico-MG" e
# "Atletico-PR" viram os dois "atletico". Nesses casos a base e removida de
# vez, obrigando o chamador a usar a UF (_POR_UF) ou o nome exato -- resolver
# no chute foi o que trocou Atletico-PR por Atletico-MG na rodada 23.
_LOOKUP = {}
_ambiguas = set()
for _c in sorted(CANONICAL):
    _b = _norm(_c)
    if _LOOKUP.get(_b, _c) != _c:
        _ambiguas.add(_b)
    _LOOKUP[_b] = _c
for _b in _ambiguas:
    _LOOKUP.pop(_b, None)
del _ambiguas

# Apelidos normalizados, com colisao barrada no import: um mesmo texto nunca
# pode apontar pra dois times.
for _apelido, _time in _ALIASES.items():
    _chave = _norm(_apelido)
    if _LOOKUP.get(_chave, _time) != _time:
        raise ValueError(
            f"Apelido ambiguo em teams.py: {_apelido!r} -> "
            f"{_LOOKUP[_chave]} e {_time}"
        )
    if _time not in CANONICAL:
        raise ValueError(f"Apelido {_apelido!r} aponta para {_time!r}, fora de CANONICAL")
    _LOOKUP[_chave] = _time
del _apelido, _time, _chave


def canonical(name, *, source=None):
    """Devolve o nome canonico. Levanta UnknownTeamError se nao reconhecer.

    Nao ha fallback silencioso e nao ha match por substring -- foi exatamente
    o match por substring que casou o goleiro Otavio (CRU) com o xG do
    atacante "Nathan Otavio Ribeiro" no enrich do FootyStats.
    """
    bruto = str(name).strip()
    base, uf = _split_uf(bruto)
    hit = (_EXATOS.get(bruto.lower())
           or _SIGLAS.get(bruto.upper())
           or _POR_UF.get((base, uf))
           or _LOOKUP.get(base))
    if hit is None:
        ctx = f" (fonte: {source})" if source else ""
        dica = ""
        if any(b == base for b, _ in _POR_UF):
            dica = (f" O nome {base!r} e ambiguo sem a UF "
                    f"(Atletico-MG x Atletico-PR) -- informe a UF.")
        raise UnknownTeamError(
            f"Time desconhecido: {name!r}{ctx}.{dica} "
            f"Adicione um apelido em scripts/lib/teams.py::_ALIASES."
        )
    return hit


def canonical_or_none(name):
    """Versao tolerante, para relatorios de cobertura. NAO use em pipeline."""
    try:
        return canonical(name)
    except UnknownTeamError:
        return None


def check_ratings_cover_canonical(ratings):
    """Garante que o arquivo de ratings tem os 20 canonicos -- nem mais, nem menos."""
    faltando = CANONICAL - set(ratings)
    sobrando = set(ratings) - CANONICAL
    if faltando or sobrando:
        raise UnknownTeamError(
            f"Ratings fora de sincronia com CANONICAL. "
            f"Faltando: {sorted(faltando)}. Nao-canonicos: {sorted(sobrando)}."
        )
