import unicodedata
import pandas as pd

CANON = {
    "america mg": "America-MG",
    "athletico-pr": "Atletico-PR",
    "atletico go": "Atletico-GO",
    "atletico-mg": "Atletico-MG",
    "avai": "Avai",
    "bahia": "Bahia",
    "botafogo rj": "Botafogo",
    "bragantino": "Bragantino",
    "csa": "CSA",
    "ceara": "Ceara",
    "chapecoense-sc": "Chapecoense",
    "corinthians": "Corinthians",
    "coritiba": "Coritiba",
    "criciuma": "Criciuma",
    "cruzeiro": "Cruzeiro",
    "cuiaba": "Cuiaba",
    "figueirense": "Figueirense",
    "flamengo rj": "Flamengo",
    "fluminense": "Fluminense",
    "fortaleza": "Fortaleza",
    "goias": "Goias",
    "gremio": "Gremio",
    "internacional": "Internacional",
    "joinville": "Joinville",
    "juventude": "Juventude",
    "mirassol": "Mirassol",
    "nautico": "Nautico",
    "palmeiras": "Palmeiras",
    "parana": "Parana",
    "ponte preta": "Ponte Preta",
    "portuguesa": "Portuguesa",
    "remo": "Remo",
    "santa cruz": "Santa Cruz",
    "santos": "Santos",
    "sao paulo": "Sao Paulo",
    "sport recife": "Sport",
    "vasco": "Vasco",
    "vitoria": "Vitoria",
}


def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def canon_team(name):
    key = strip_accents(str(name)).strip().lower()
    return CANON.get(key, str(name).strip())


df = pd.read_csv("/mnt/project/BRA.csv")

df["date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
df = df.dropna(subset=["HG", "AG"]).copy()
df["home_goals"] = df["HG"].astype(int)
df["away_goals"] = df["AG"].astype(int)
df["home_team"] = df["Home"].map(canon_team)
df["away_team"] = df["Away"].map(canon_team)
df["season"] = df["Season"].astype(int)

# Market-implied closing probabilities (from average closing odds), kept for
# later validation/comparison against the model's own probabilities.
df["avg_odds_home"] = df["AvgCH"]
df["avg_odds_draw"] = df["AvgCD"]
df["avg_odds_away"] = df["AvgCA"]

out = df[[
    "date", "season", "home_team", "away_team", "home_goals", "away_goals",
    "avg_odds_home", "avg_odds_draw", "avg_odds_away",
]].sort_values("date").reset_index(drop=True)

out.to_csv("/home/claude/brasileirao/matches_2012_2026.csv", index=False)

print("Total matches:", len(out))
print("Seasons:", out["season"].min(), "-", out["season"].max())
print("Matches per season:")
print(out.groupby("season").size())
print("\nLast 5 matches:")
print(out.tail(5).to_string(index=False))
print("\nTeams:", sorted(set(out.home_team) | set(out.away_team)))
