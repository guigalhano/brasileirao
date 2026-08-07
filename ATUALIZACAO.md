# 📊 Como Atualizar os Próximos Confrontos

## 🚀 Forma Mais Simples (SEM Terminal)

### 1. Edite o arquivo `data/proximos_jogos.json` direto no GitHub

```
github.com/guigalhano/brasileirao/blob/main/data/proximos_jogos.json
```

Clique em ✏️ para editar e atualize com os confrontos da próxima rodada:

```json
{
  "rodada": 24,
  "data_inicio": "25/08/2026",
  "data_fim": "27/08/2026",
  "jogos": [
    {"home": "Flamengo", "away": "Vasco", "day": "Dom 25/08", "time": "18:30"},
    {"home": "Palmeiras", "away": "Santos", "day": "Dom 25/08", "time": "18:30"},
    ...
  ]
}
```

### 2. Ao salvar (Commit), o GitHub Actions dispara automaticamente

- ✅ Calcula xG e probabilidades
- ✅ Atualiza o site
- ✅ Faz deploy em ~1-2 minutos

---

## ⚡ Alternativa: Disparo Manual

Se preferir forçar a atualização sem editar:

1. Acesse: https://github.com/guigalhano/brasileirao/actions
2. Clique em **"Atualizar dados do Cartola FC"**
3. Clique no botão **"Run workflow"** → **"Run workflow"**

---

## 📋 O que precisa estar no JSON

| Campo | Exemplo | Descrição |
|-------|---------|-----------|
| `rodada` | `24` | Número da rodada |
| `data_inicio` | `25/08/2026` | Primeira data dos jogos |
| `data_fim` | `27/08/2026` | Última data dos jogos |
| `home` | `Flamengo` | Time mandante (exatamente como no Cartola) |
| `away` | `Vasco` | Time visitante |
| `day` | `Dom 25/08` | Dia e data formatados |
| `time` | `18:30` | Horário do jogo |

---

## 🔍 Nomes dos Times (Exatamente Assim)

```
Flamengo, Palmeiras, Corinthians, Bahia, Gremio, Santos, Vasco, Cruzeiro,
Internacional, Botafogo, Atletico-MG, Atletico-PR, Coritiba, Bragantino,
Mirassol, Chapecoense, Fluminense, Vitoria, Remo, Sao Paulo
```

---

## 🤖 Atualização Automática (Sem Fazer Nada)

O GitHub Actions roda automaticamente:
- **Diariamente às 06:00 UTC** → Atualiza mercado do Cartola
- **Sempre que você editar `proximos_jogos.json`** → Recalcula xG e pub lica

---

## ❓ Dúvidas?

Os dados dos times têm que estar no arquivo de ratings. Se um time não existir:
1. Edite `data/team_ratings_calibrado.json`
2. Ou verifique se o nome está exatamente igual ao arquivo de ratings

