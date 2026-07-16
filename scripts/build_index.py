"""
Regenera o array PLAYERS embutido no index.html a partir de
data/cartola_players_enriched.csv (gerado por atualizar_mercado_cartola.py).

Uso:
    python scripts/build_index.py
"""
import json
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "index.html"
DATA_PATH = REPO_ROOT / "data" / "cartola_players_enriched.csv"
XG90_PATH = REPO_ROOT / "data" / "player_xg90_footystats.csv"


def main():
    if not DATA_PATH.exists():
        print(f"ERRO: {DATA_PATH} nao encontrado. Rode atualizar_mercado_cartola.py primeiro.")
        return 1

    df = pd.read_csv(DATA_PATH)

    xg90_by_id = {}
    if XG90_PATH.exists():
        xg_df = pd.read_csv(XG90_PATH)
        xg90_by_id = dict(zip(xg_df["atleta_id"].astype(str), xg_df["xg90"]))
        print(f"Usando xG individual do FootyStats para {len(xg90_by_id)} jogadores "
              f"(rode scripts/enrich_players_footystats.py para atualizar essa lista).")
    else:
        print("AVISO: data/player_xg90_footystats.csv nao encontrado -- PLAYERS vai sem xg90 "
              "(rode scripts/enrich_players_footystats.py primeiro se quiser esse dado).")

    lines = []
    for _, p in df.iterrows():
        name = str(p["name"]).replace('"', '\\"')
        xg90 = xg90_by_id.get(str(p["atleta_id"]))
        xg90_field = (", xg90:%s" % xg90) if xg90 is not None else ""
        lines.append(
            '    {name:"%s", pos:"%s", team:"%s", price:%s, media:%s, status:"%s", ult5:%s, desvio:%s%s}'
            % (name, p["pos"], p["team"], p["price"], p["media"], p["status"], p["ult5"], p["desvio"], xg90_field)
        )
    js_array = "var PLAYERS = [\n" + ",\n".join(lines) + "\n  ];"

    content = INDEX_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"var PLAYERS = \[.*?\n  \];", re.DOTALL)
    if not pattern.search(content):
        print("ERRO: nao encontrei 'var PLAYERS = [...]' no index.html. Nada foi alterado.")
        return 1

    new_content = pattern.sub(lambda m: js_array, content, count=1)
    INDEX_PATH.write_text(new_content, encoding="utf-8")
    print(f"OK: index.html atualizado com {len(df)} jogadores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
