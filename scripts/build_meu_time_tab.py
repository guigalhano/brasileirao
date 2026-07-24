"""
Regenera o array MEU_TIME_HIST embutido no index.html a partir de
data/meu_time_historico.csv (gerado por comparar_historico_time.py).

Uso:
    python scripts/build_meu_time_tab.py
"""
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "index.html"
DATA_PATH = REPO_ROOT / "data" / "meu_time_historico.csv"


def main():
    if not DATA_PATH.exists():
        print(f"ERRO: {DATA_PATH} nao encontrado. Rode scripts/comparar_historico_time.py primeiro.")
        return 1

    df = pd.read_csv(DATA_PATH)

    lines = []
    for _, r in df.iterrows():
        lines.append(
            '    {rodada:%s, meus:%s, medio:%s, diff:%s, bateu:%s}'
            % (int(r["rodada"]), r["meus_pontos"], r["time_medio_12"], r["diferenca"],
               "true" if bool(r["bateu_mercado"]) else "false")
        )
    js_array = "var MEU_TIME_HIST = [\n" + ",\n".join(lines) + "\n  ];"

    content = INDEX_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"var MEU_TIME_HIST = \[.*?\n  \];", re.DOTALL)
    if not pattern.search(content):
        print("ERRO: nao encontrei 'var MEU_TIME_HIST = [...]' no index.html. Nada foi alterado.")
        return 1

    new_content = pattern.sub(lambda m: js_array, content, count=1)
    INDEX_PATH.write_text(new_content, encoding="utf-8")
    print(f"OK: index.html atualizado com {len(df)} rodadas de historico do seu time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
