# Brasileirão Analytics

Modelo preditivo do Campeonato Brasileiro Série A 2026 + ferramenta de escalação do Cartola FC,
construído junto com o Claude ao longo de várias sessões. Este README é o mapa de tudo que existe
no repositório e como cada peça se encaixa.

**Página ao vivo** (depois de ativar o GitHub Pages, veja a seção "Publicar no GitHub Pages" abaixo):
`https://SEU-USUARIO.github.io/NOME-DO-REPO/`

## Estrutura do repositório

```
.
├── index.html              # a ferramenta principal (abas: Preditor, Próximos Jogos, Cartola FC, Meu Time)
├── data/                   # dados processados, prontos pra uso (CSV/JSON)
├── scripts/                # scripts Python/bat que geram os dados em data/
├── docs/                   # versões standalone de widgets específicos (predictor sozinho, etc.)
└── .github/workflows/      # automação do GitHub Actions (atualização diária)
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

## Pontuação do Cartola e o desarme

A tabela oficial (cartola.globo.com → "Entenda Mais") está transcrita em
`data/cartola_tabela_pontuacao.json`. Ela não é usada direto: `scripts/lib/pontuacao.py`
**recupera** a tabela regredindo a pontuação real contra os scouts e cruza o resultado com
o arquivo. Restrita às cinco posições de linha, a recuperação é exata — R²=1,0000, erro
0,0000, os 19 scouts batendo na casa decimal. Se o Cartola reajustar algum scout (já
aconteceu com desarme e defesa), os dados divergem do arquivo e `verificar_integridade.py`
barra a publicação em vez de deixar o site somar peso velho.

O **desarme** é o scout que mais decide a pontuação de defensor: 1,5 ponto, 1,31 por jogo
de lateral e 1,04 de zagueiro — rende mais que o SG na média. E é o mais repetível de
todos (autocorrelação de rodada para rodada 0,231, contra 0,090 do gol e 0,055 da
assistência). Desarme é hábito, gol é evento.

Mas ele **não entra como bônus somado** — isso foi testado e não passa (t=0,07 contra a
média, para ZAG/LAT), e um XI montado só por desarme faz 48,4 pontos por rodada contra
57,4 da média simples. O que funciona é usá-lo por dentro de uma pontuação esperada
montada scout a scout, com encolhimento de Bayes empírico **medido por scout**: o ganho
vem de encolher o resto. Gol de zagueiro não tem variância entre jogadores que sobreviva
à estimativa, então vai todo para a média da posição, e o desarme decide o ranking.
Backtest walk-forward (rodadas 8-21, encolhimento reestimado a cada rodada só com o
passado, `scripts/backtest_escalacao.py` reproduz):

| ZAG+LAT, correlação com a rodada seguinte | |
|---|---|
| média histórica | 0,120 |
| E[pts], encolhimento uniforme K=5 | 0,151 |
| E[pts], encolhimento por scout | **0,177** (t=+2,51 vs uniforme) |

Em MEI e ATA a diferença fica em \|t\|<0,4 — ruído nos dois sentidos. Por isso o sinal
entra só em ZAG/LAT no site, que é onde foi validado.

Sobre confronto: a correlação crua entre desarmes do time e gols sofridos é **negativa**
(-0,37), mas isso é confusão com qualidade do time — time bom desarma mais e sofre menos.
Comparando o mesmo jogador contra adversários diferentes, o sinal inverte: +0,31 desarme
por gol/jogo de ataque adversário (t=+2,39) em ZAG/LAT, contra t=-0,05 em ATA.

Achados relevantes ao longo do processo (todos com validação estatística, não só opinião):
- Nenhuma estratégia de aposta simples nem o modelo batem o mercado de forma consistente
  (o mercado brasileiro é bem calibrado).
- Encurtar a meia-vida do Dixon-Coles piora a calibração geral, mesmo resolvendo casos
  pontuais (ex: Chapecoense) — por isso o ajuste de técnico é seletivo, não global.
- Três falhas silenciosas encontradas em agosto/2026 no `compute_advanced_signals.py`, todas
  corrigidas: (a) o script vinha morrendo com `KeyError` desde 29/07 e o site servia um arquivo
  congelado com cara de atual; (b) a leitura de scout procurava a coluna `G` quando o CSV tem
  `scout_G`, devolvia vazio e convertia em 0,0 — `goalShare` e `playmaking` estavam zerados no
  site desde sempre; (c) o código diferenciava scouts consecutivos achando que vinham
  cumulativos, o que é falso (em 24% dos pares o scout diminui, e a regressão dá R²=1,0 exato
  com os valores crus) — a "correção" é que corrompia o dado.
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

## Automação (atualização diária)

O arquivo `.github/workflows/atualizar_dados.yml` roda sozinho **3x por dia** (06h, 12h e 18h
BRT) e também pode ser disparado na aba Actions. O ciclo é fechado — nada precisa ser rodado
localmente para o site continuar em dia:

1. **Coleta**: resultados novos (football-data.co.uk), confrontos da rodada atual (API do
   Cartola), rodadas novas do histórico de scouts, e o mercado (preço/média/status).
2. **Modelo**: reajusta o Dixon-Coles e recalibra ataque/defesa — **só se entrou resultado
   novo** (o otimizador não é determinístico no 4º decimal, então refitar à toa geraria um diff
   de 140 linhas a cada execução).
3. **Sinais por jogador**: desarme, pontuação esperada por scout, forma ajustada.
4. **Montagem**: regenera o `index.html` (jogadores, probabilidades, análises).
5. **Portão**: `verificar_integridade.py` — se sair != 0, **não publica**.
6. Commit + push, e o GitHub Pages publica sozinho.

A ordem importa em dois pontos: `compute_advanced_signals.py` **antes** do `build_index.py`
(senão o site publica os sinais da execução anterior), e `update_next_matches_dynamic.py`
**antes** do `generate_advanced_analytics.py` (senão a aba de análises some).

**Nenhuma etapa de coleta usa `continue-on-error`** — e isso é deliberado. Era exatamente o que
mantinha o workflow verde enquanto o `atualizar_historico_cartola.py` quebrava todo dia com
`KeyError` e o histórico de scouts congelava na rodada 21. Falha de coleta agora derruba o job;
o site fica com o dado de ontem, que é o comportamento certo.

### O que ainda não é automático

| Fonte | Por quê | Se envelhecer |
|---|---|---|
| xG do WhoScored (`data/whoscored_xg_2026.csv`) | o site bloqueia scraping automatizado | a âncora de xG perde atualidade aos poucos; o pipeline **não** quebra — o `recalibrar_com_whoscored.py` normaliza por jogo justamente pra tolerar isso |
| Valor de mercado (Transfermarkt) | ~1000+ requisições, e o dado muda em escala de meses | nada quebra; rode `scripts/coletar_valores_jogadores.py` quando quiser |
| Odds de fechamento | vêm junto com os resultados; jogos futuros não têm | só a coluna de edge fica vazia (já é um aviso, não erro) |

## Histórico do projeto

Este projeto foi construído incrementalmente numa conversa longa com o Claude, passando por:
modelo de partidas (Dixon-Coles → Elo-Odds híbrido) → backtest de estratégias de aposta →
cruzamento com dados oficiais do Cartola FC → ferramenta de escalação → integração de valor de
mercado do Transfermarkt → automação. Os scripts em `scripts/` refletem essa evolução e têm
comentários explicando o raciocínio e as validações feitas em cada etapa.
