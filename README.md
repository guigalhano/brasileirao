# Brasileirão Analytics

Modelo preditivo do Campeonato Brasileiro Série A 2026 + ferramenta de escalação do Cartola FC,
construído junto com o Claude ao longo de várias sessões. Este README é o mapa de tudo que existe
no repositório e como cada peça se encaixa.

**Página ao vivo** (depois de ativar o GitHub Pages, veja a seção "Publicar no GitHub Pages" abaixo):
`https://SEU-USUARIO.github.io/NOME-DO-REPO/`

## Estrutura do repositório

```
.
├── index.html              # a ferramenta principal (abas: Preditor, Próximos Jogos, Calendário, Cartola FC)
├── data/                   # dados processados, prontos pra uso (CSV/JSON)
├── scripts/                # scripts Python/bat que geram os dados em data/
├── docs/                   # versões standalone de widgets específicos (predictor sozinho, etc.)
└── .github/workflows/      # automação do GitHub Actions (atualização a cada 3 dias)
```

## O modelo, em resumo

Duas partes que se complementam:

1. **Elo-Odds** (resultado da partida: vitória/empate/derrota) — rating Elo atualizado pelas
   odds de fechamento do mercado em vez do placar (metodologia de Wunderlich & Memmert, 2018).
   Validado fora da amostra: log-loss 1.024 contra 1.001 do próprio mercado — o melhor modelo
   não-mercado testado, superando Dixon-Coles puro, Elo-Resultado, Elo-Gols e um Performance
   Rating à la soccerstats.
2. **Dixon-Coles Poisson** (gols esperados e placar) — ajustado com decaimento temporal
   (meia-vida de 450 dias, testamos várias e essa é próxima do ótimo) e um ajuste seletivo de
   peso extra (6x) para jogos disputados sob um técnico confirmado como novo, para os times que
   trocaram de comando em 2026 (Atlético-MG, Vasco, São Paulo, Flamengo, Cruzeiro, Santos,
   Botafogo, Corinthians, Chapecoense).

Achados relevantes ao longo do processo (todos com validação estatística, não só opinião):
- Nenhuma estratégia de aposta simples nem o modelo batem o mercado de forma consistente
  (o mercado brasileiro é bem calibrado).
- Encurtar a meia-vida do Dixon-Coles piora a calibração geral, mesmo resolvendo casos
  pontuais (ex: Chapecoense) — por isso o ajuste de técnico é seletivo, não global.
- Valor de mercado (Transfermarkt) não melhora a previsão de partidas nesse ponto da temporada
  (18 rodadas de dados reais já dominam qualquer prior financeiro), e tem uma relação estatisticamente
  significativa mas **negativa** com a pontuação no Cartola (controlando pelo preço) — reflete
  reputação/potencial, não desempenho fantasy entregue.

## Fontes de dados

| Fonte | O que fornece | Como é obtida |
|---|---|---|
| football-data.co.uk (BRA.csv) | Resultados + odds 1X2, 2012-2026 | Upload manual (ver `data/matches_2012_2026.csv`) |
| Cartola FC (API oficial) | Preço, média, status, scouts por jogador | `scripts/coletar_historico_cartola.py` (rodar local ou via Actions) |
| Transfermarkt (transfermarkt-scraper + endpoint de valor de mercado) | Valor de mercado e desempenho por jogador | `scripts/coletar_transfermarkt.py` + `scripts/coletar_valores_jogadores.py` (rodar local, ver aviso abaixo) |
| CBF / ESPN | Calendário completo da temporada | Coletado manualmente via busca, embutido no `index.html` |

**Aviso importante sobre as APIs do Cartola e do Transfermarkt**: esses domínios são bloqueados
no sandbox do Claude (restrição de rede do próprio ambiente), então os scripts de coleta
precisam rodar localmente (no seu computador) ou no GitHub Actions (que tem internet irrestrita).
Veja a seção de automação abaixo.

## Rodando os scripts localmente

```bash
pip install requests pandas scipy numpy scikit-learn statsmodels

# historico de pontuacoes do Cartola (todas as rodadas ja jogadas)
python scripts/coletar_historico_cartola.py --modo rodadas --ate-rodada 18

# valor de mercado + desempenho por jogador (Transfermarkt) -- demorado, ver docstring do script
python scripts/coletar_valores_jogadores.py caminho/para/jogadores.json
```

No Windows, `scripts/coletar_tudo.bat` roda o pipeline completo do Transfermarkt de uma vez
(clona a ferramenta, instala dependências, baixa e processa tudo).

## Publicar no GitHub Pages

1. No GitHub, vá em **Settings → Pages**.
2. Em "Source", escolha **Deploy from a branch**, branch `main`, pasta `/ (root)`.
3. Salve. Em alguns minutos a ferramenta fica disponível em
   `https://SEU-USUARIO.github.io/NOME-DO-REPO/`.

## Automação (atualização a cada 3 dias)

O arquivo `.github/workflows/atualizar_dados.yml` roda automaticamente a cada 3 dias (e também
pode ser disparado manualmente na aba Actions do GitHub). Ele:
1. Baixa o snapshot mais recente do mercado do Cartola FC (preço, média, status de cada jogador).
2. Reprocessa a base enriquecida (histórico + forma recente + consistência).
3. Faz commit automático dos arquivos atualizados em `data/`.

Isso funciona porque o GitHub Actions roda numa máquina com acesso normal à internet — diferente
do ambiente do Claude, que tem alguns domínios bloqueados por política de rede.

**Ressalva importante**: o workflow atualiza os dados do Cartola FC (que mudam de verdade a cada
poucos dias, dentro da mesma temporada). Já a raspagem completa do Transfermarkt (valor de mercado
por jogador) é mais pesada (~1000+ requisições) e não está automatizada por padrão, pra não gerar
carga desnecessária num site de terceiros a cada 3 dias sem necessidade real — esses dados mudam
bem mais devagar (semanas/meses). Rode `scripts/coletar_valores_jogadores.py` manualmente quando
quiser atualizar essa parte.

## Histórico do projeto

Este projeto foi construído incrementalmente numa conversa longa com o Claude, passando por:
modelo de partidas (Dixon-Coles → Elo-Odds híbrido) → backtest de estratégias de aposta →
cruzamento com dados oficiais do Cartola FC → ferramenta de escalação → integração de valor de
mercado do Transfermarkt → automação. Os scripts em `scripts/` refletem essa evolução e têm
comentários explicando o raciocínio e as validações feitas em cada etapa.
