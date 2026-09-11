# Brasileirão Analytics

Modelo preditivo do Campeonato Brasileiro Série A 2026 + ferramenta de escalação do Cartola FC,
construído junto com o Claude ao longo de várias sessões. Este README é o mapa de tudo que existe
no repositório e como cada peça se encaixa.

**Página ao vivo**: https://guigalhano.github.io/brasileirao/ — publicada sozinha a cada push
(GitHub Pages a partir do `main`), e o pipeline dá push 3x por dia.

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
   Reajustado automaticamente a cada rodada nova (`scripts/elo_odds_model.py`); até setembro/2026
   o `data/elo_odds_final.json` era gerado à mão e ficou parado em 24/07, com o Flamengo 40 pontos
   de Elo defasado — numa escala em que o mando de campo inteiro vale 60.
   Validado fora da amostra: log-loss 1.024 contra 1.001 do próprio mercado — o melhor modelo
   não-mercado testado, superando Dixon-Coles puro, Elo-Resultado, Elo-Gols e um Performance
   Rating à la soccerstats.
2. **Dixon-Coles Poisson** (gols esperados e placar) — ajustado com decaimento temporal
   (meia-vida de 450 dias, testamos várias e essa é próxima do ótimo).

   **Correção de setembro/2026**: este README dizia que o modelo também aplicava um "ajuste
   seletivo de peso extra (6x) para jogos sob técnico novo" em 9 times. Duas coisas estavam
   erradas. Primeiro, o `refit_with_coach_boost.py` escreve um arquivo que **nenhum script lê** —
   a cadeia que chega ao site é `fit_model_v2` → `final_v2` → `recalibrar_com_whoscored` →
   `calibrado`. Segundo, e ainda bem: medido fora da amostra em 8 cortes de abril a agosto
   (`scripts/validar_coach_boost.py` reproduz), o boost **piora** a previsão em todos eles, por
   0,03 a 0,09 de log-loss — enorme num contexto onde a distância entre o nosso melhor modelo e o
   próprio mercado é de 0,02. O motivo: as trocas foram de fevereiro a abril, então na rodada 27
   quase todo jogo de 2026 desses times já é pós-troca, e o 6x deixou de destacar um período novo
   para simplesmente inflar a temporada inteira de 9 times. O ajuste não entra no modelo.

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
  pontuais (ex: Chapecoense). A tentativa de contornar isso com um peso extra por troca de
  técnico também não funciona — ver a correção na seção "O modelo, em resumo" acima.
- Três falhas silenciosas encontradas em agosto/2026 no `compute_advanced_signals.py`, todas
  corrigidas: (a) o script vinha morrendo com `KeyError` desde 29/07 e o site servia um arquivo
  congelado com cara de atual; (b) a leitura de scout procurava a coluna `G` quando o CSV tem
  `scout_G`, devolvia vazio e convertia em 0,0 — `goalShare` e `playmaking` estavam zerados no
  site desde sempre; (c) o código diferenciava scouts consecutivos achando que vinham
  cumulativos, o que é falso (em 24% dos pares o scout diminui, e a regressão dá R²=1,0 exato
  com os valores crus) — a "correção" é que corrompia o dado.
- **xG individual do WhoScored não entra no critério de escalação** — testado duas vezes, por
  caminhos diferentes, com o mesmo resultado. O teste decisivo (walk-forward, 3 transições,
  snapshots das rodadas 20/21/22, 358 observações de ATA/MEI) mostra que o xG acumulado até N−1
  não acrescenta nada à média para prever a rodada N: o coeficiente fica em t=+0,53 (ATA+MEI),
  +0,08 (ATA), +1,15 (MEI), e o R² sai de 0,0601 para 0,0609. Chutes/jogo, que tinha a maior
  correlação *simples* entre os meias (r=+0,258, acima da própria média), também não sobrevive ao
  controle pela média — as duas são colineares. Ressalva honesta: com 3 transições só detectaríamos
  um r incremental de ~0,15, então "não significativo" aqui está mais perto de "não dá pra saber"
  do que de "é zero"; o que dá confiança é concordar com o achado anterior (correlação parcial
  negativa controlando por gols) por um caminho metodologicamente distinto.
- Valor de mercado (Transfermarkt) não melhora a previsão de partidas nesse ponto da temporada
  (18 rodadas de dados reais já dominam qualquer prior financeiro), e tem uma relação estatisticamente
  significativa mas **negativa** com a pontuação no Cartola (controlando pelo preço) — reflete
  reputação/potencial, não desempenho fantasy entregue.

## Fontes de dados

| Fonte | O que fornece | Como é obtida |
|---|---|---|
| football-data.co.uk (BRA.csv) | Resultados + odds **de fechamento** 1X2, 2012-2026 | `scripts/ingerir_resultados.py`, automático |
| Cartola FC (API oficial) | Preço, média, status, scouts por jogador, confrontos da rodada | `atualizar_mercado_cartola.py`, `atualizar_historico_cartola.py`, `atualizar_confrontos_cartola.py` — todos automáticos |
| The Odds API | Odds **pré-jogo** da rodada que vem (coluna de edge) | `scripts/atualizar_odds_mercado.py` — opcional, precisa do secret `ODDS_API_KEY` |
| Transfermarkt (transfermarkt-scraper + endpoint de valor de mercado) | Valor de mercado e desempenho por jogador | `scripts/coletar_transfermarkt.py` + `scripts/coletar_valores_jogadores.py` (rodar local, ver aviso abaixo) |
| CBF / ESPN | Calendário completo da temporada | Coletado manualmente via busca, embutido no `index.html` |

**Sobre rodar os coletores**: todos funcionam no GitHub Actions, que é onde o pipeline roda de
verdade. A API do Cartola (`api.cartolafc.globo.com`) também responde localmente — o aviso antigo
de que estaria bloqueada no ambiente do Claude não vale mais, foi verificado em setembro/2026. O
Transfermarkt segue sendo coleta manual, mas por peso (~1000+ requisições), não por bloqueio.

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

**Falha de terceiro não é a mesma coisa que bug** — e a distinção custou caro para ser aprendida.
Primeiro o pipeline usava `continue-on-error`, e isso mantinha o Actions verde enquanto o
histórico de scouts congelava na rodada 21 com `KeyError` todo dia. Removemos. Aí, em setembro, o
football-data.co.uk devolveu HTTP 503 por dois dias e, como é o primeiro passo, derrubou o job
inteiro — inclusive o mercado do Cartola, que não depende dele. **O site ficou 5 dias parado por
causa de um servidor de terceiro fora do ar.**

A distinção agora é feita dentro de cada script, via [`scripts/lib/rede.py`](scripts/lib/rede.py),
que é onde se sabe o que cada erro significa:

| Sintoma | O que é | Resposta |
|---|---|---|
| 503, 429, timeout, conexão recusada | o terceiro caiu | tenta 3x com espera crescente; se insistir, segue sem aquela fonte e avisa |
| 404, 401, 403 | URL ou chave errada | quebra alto, sem retentar (não melhora tentando) |
| `KeyError`, coluna sumida, time desconhecido, JSON inválido | contrato mudou ou nosso código está errado | quebra alto |

Degradar não é publicar qualquer coisa: a rede de segurança é o portão no fim. Se a degradação
deixar o dado velho demais, `verificar_integridade.py` bloqueia a publicação.

**O portão confere valor, não presença.** Ele recusa publicar se: a tabela de pontuação do Cartola
divergir da oficial; os `RATINGS` embutidos no `index.html` divergirem do modelo; o rótulo da
rodada, o top 3 do cabeçalho ou `JOGOS_ATUAIS_APROX` estiverem defasados; faltar análise em algum
confronto; ou os resultados atrasarem mais de 2 rodadas.

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
