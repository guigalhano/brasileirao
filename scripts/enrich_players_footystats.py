#!/usr/bin/env python3
"""
enrich_players_footystats.py

Casa a lista "Players with the Most xG" do FootyStats (xG individual real,
baseado em chutes+pressao ofensiva) com o elenco do Cartola FC, e grava um
mapeamento atleta_id -> xg90 em data/player_xg90_footystats.csv.

build_index.py le esse arquivo (se existir) e inclui o campo `xg90` no
array PLAYERS do index.html, para uso nos criterios de escolha (ameaca
real de gol/criacao de chances), alem do que ja vem de media/forma/matchup.

COBERTURA: o FootyStats so lista os top ~25 jogadores em xG da liga inteira
(nao os 570 do Cartola), entao a maioria dos jogadores fica sem esse dado --
isso e esperado. O uso no index.html deve tratar xg90 ausente como neutro
(nao penalizar nem beneficiar quem nao esta na lista).

Uso:
    python3 enrich_players_footystats.py --repo-dir /caminho/para/repo
"""

import argparse
import csv
import difflib
import re
import unicodedata
from pathlib import Path


def normalize_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_token_frequency(candidates):
    """Conta em quantos jogadores do elenco cada token de nome aparece.
    Um token raro (ex: 'viveros', so 1 jogador) e' confiavel mesmo sozinho;
    um token comum (ex: 'gabriel', 15+ jogadores) precisa de reforco de
    outro token pra nao dar falso positivo."""
    from collections import Counter
    freq = Counter()
    for norm, _ in candidates:
        for tok in set(norm.split()):
            freq[tok] += 1
    return freq


def match_player(fs_norm, candidates, token_freq, rare_threshold=3):
    """candidates: list of (norm_name, row). Retorna (row, tipo) ou (None, 'sem_match')."""
    for norm, row in candidates:
        if norm == fs_norm:
            return row, "exato"

    fs_tokens = set(fs_norm.split())

    contains_hits = []
    for norm, row in candidates:
        if not fs_norm:
            continue
        cand_tokens = set(norm.split())
        overlap = fs_tokens & cand_tokens
        if not overlap or not (fs_norm in norm or norm in fs_norm):
            continue
        # Confia em overlap de 1 token SO se esse token for raro no elenco
        # inteiro (poucos jogadores o compartilham). Token comum (nome
        # generico tipo "gabriel") exige bater em 2+ tokens.
        min_token_freq = min(token_freq.get(t, 99) for t in overlap)
        needs = 1 if min_token_freq <= rare_threshold else 2
        if len(overlap) >= needs:
            contains_hits.append((row, norm))
    if len(contains_hits) == 1:
        return contains_hits[0][0], "contains"
    if len(contains_hits) > 1:
        best = max(contains_hits, key=lambda h: len(fs_tokens & set(h[1].split())))
        return best[0], "contains"

    best_row, best_score = None, 0.0
    for norm, row in candidates:
        score = difflib.SequenceMatcher(None, fs_norm, norm).ratio()
        if score > best_score:
            best_score, best_row = score, row
    if best_score >= 0.75:
        return best_row, "fuzzy"
    return None, "sem_match"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--footystats-csv", default=None,
                     help="default: <repo-dir>/data/footystats_player_xg.csv")
    args = ap.parse_args()

    repo = Path(args.repo_dir)
    fs_path = Path(args.footystats_csv) if args.footystats_csv else repo / "data" / "footystats_player_xg.csv"

    cartola_rows = list(csv.DictReader(open(repo / "data" / "cartola_players_enriched.csv", encoding="utf-8")))
    candidates = [(normalize_name(r["name"]), r) for r in cartola_rows]
    token_freq = build_token_frequency(candidates)

    fs_rows = list(csv.DictReader(open(fs_path, encoding="utf-8")))

    results = []
    print(f"{'Jogador FootyStats':32s} {'xG/90':>6s}  {'Match Cartola':30s} {'Time':15s} {'Tipo':10s}")
    print("-" * 100)
    n_matched = 0
    for r in fs_rows:
        fs_norm = normalize_name(r["name"])
        match_row, tipo = match_player(fs_norm, candidates, token_freq)
        if match_row:
            n_matched += 1
            results.append({
                "atleta_id": match_row["atleta_id"],
                "name_cartola": match_row["name"],
                "team": match_row["team"],
                "xg90": r["xg90"],
                "match_tipo": tipo,
            })
            print(f"{r['name']:32s} {r['xg90']:>6s}  {match_row['name']:30s} {match_row['team']:15s} {tipo:10s}")
        else:
            print(f"{r['name']:32s} {r['xg90']:>6s}  {'(sem match)':30s} {'':15s} {'sem_match':10s}")

    print(f"\n{n_matched}/{len(fs_rows)} jogadores casados com o elenco do Cartola.")

    # Deteccao de colisao: se dois jogadores DIFERENTES do FootyStats bateram
    # no MESMO atleta_id do Cartola, pelo menos um dos dois esta errado (o
    # match "contains" so pegou o primeiro nome em comum). Descarta os dois
    # em vez de adivinhar qual esta certo.
    from collections import Counter
    counts = Counter(r["atleta_id"] for r in results)
    colisoes = {aid for aid, c in counts.items() if c > 1}
    if colisoes:
        print(f"\nAVISO: {len(colisoes)} colisao(oes) detectada(s) -- descartando (match ambiguo):")
        for r in results:
            if r["atleta_id"] in colisoes:
                print(f"  - {r['name_cartola']} ({r['team']}) recebeu match de mais de um jogador FootyStats")
        results = [r for r in results if r["atleta_id"] not in colisoes]

    out_path = repo / "data" / "player_xg90_footystats.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["atleta_id", "name_cartola", "team", "xg90", "match_tipo"])
        w.writeheader()
        w.writerows(results)
    print(f"Salvo em {out_path}")


if __name__ == "__main__":
    main()
