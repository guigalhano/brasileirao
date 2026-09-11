"""
O boost de tecnico melhora a previsao fora da amostra? Resposta medida: NAO.

POR QUE ISSO EXISTE
-------------------
O refit_with_coach_boost.py multiplica por 6 o peso dos jogos disputados sob
tecnico novo, para 9 times que trocaram de comando em 2026, e o README
descrevia isso como metade do modelo. Duas coisas estavam erradas:

1. O arquivo que ele gera (team_ratings_coach_adjusted.json) NAO E LIDO POR
   NINGUEM. A cadeia que chega no site e fit_model_v2 -> final_v2 ->
   recalibrar_com_whoscored -> calibrado. O ajuste era um ramo morto.

2. E ainda bem. Medido aqui: treinando so com jogos anteriores a um corte e
   avaliando nos seguintes, o boost PIORA a previsao em todos os 8 cortes
   testados, de abril a agosto de 2026:

       corte        n teste   sem boost   com boost
       2026-04-15      150      1.0226      1.0512
       2026-05-01      130      1.0579      1.1245
       2026-05-15      110      1.0246      1.0921
       2026-06-01       82      1.0580      1.1195
       2026-06-15       80      1.0571      1.1167
       2026-07-01       80      1.0571      1.1167
       2026-08-01       51      1.0448      1.1039
       2026-08-15       41      1.0485      1.1388

   (log-loss, menor e melhor). A degradacao de 0,03 a 0,09 e grande no
   contexto: a distancia entre o nosso melhor modelo e o proprio mercado e
   de apenas 0,02.

POR QUE NAO FUNCIONA
As trocas de tecnico sao todas de fevereiro a abril. Na rodada 27, quase todo
jogo de 2026 desses times ja e posterior a troca -- entao o "6x" nao destaca
mais um periodo novo, so infla a temporada inteira de 9 times contra o
historico deles. O decaimento temporal de 450 dias ja da peso alto a 2026
sozinho; o boost por cima disso vira sobreajuste.

O script continua no repositorio porque a pergunta pode voltar (uma troca de
tecnico em setembro, por exemplo, seria um caso genuinamente novo). Mas o
ajuste NAO entra no modelo publicado.

Uso:
    python scripts/validar_coach_boost.py
"""
import numpy as np, pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

DATA='D:/brasileirao/data/matches_2012_2026.csv'
HALF_LIFE=450.0
COACH={"Atletico-MG":"2026-02-26","Vasco":"2026-03-03","Sao Paulo":"2026-03-09",
       "Flamengo":"2026-03-03","Cruzeiro":"2026-03-23","Santos":"2026-03-19",
       "Botafogo":"2026-03-22","Corinthians":"2026-04-05","Chapecoense":"2026-04-03"}

df=pd.read_csv(DATA,parse_dates=['date']).sort_values('date').reset_index(drop=True)
df=df.dropna(subset=['home_goals','away_goals'])
teams=sorted(set(df.home_team)|set(df.away_team)); idx={t:i for i,t in enumerate(teams)}; n=len(teams)

def ajustar(treino, boost):
    max_date=treino['date'].max()
    dias=(max_date-treino['date']).dt.days.clip(lower=0)
    w=(0.5**(dias/HALF_LIFE)).values.copy()
    if boost!=1.0:
        for t,d in COACH.items():
            d=pd.Timestamp(d)
            m=((treino.date>=d)&((treino.home_team==t)|(treino.away_team==t))).values
            w[m]*=boost
    hi=treino.home_team.map(idx).values; ai=treino.away_team.map(idx).values
    hg=treino.home_goals.values.astype(float); ag=treino.away_goals.values.astype(float)
    def nll(p):
        a,d,h=p[:n],p[n:2*n],p[2*n]
        lh=np.exp(a[hi]-d[ai]+h); la=np.exp(a[ai]-d[hi])
        ll=w*(hg*np.log(lh)-lh+ag*np.log(la)-la)
        return -ll.sum()+0.01*(a**2).sum()+0.01*(d**2).sum()
    p0=np.zeros(2*n+1); p0[2*n]=0.3
    r=minimize(nll,p0,method='L-BFGS-B')
    return r.x[:n], r.x[n:2*n], r.x[2*n]

def avaliar(par, teste):
    a,d,h=par
    ll=[]; mae=[]
    for _,m in teste.iterrows():
        if m.home_team not in idx or m.away_team not in idx: continue
        lh=np.exp(a[idx[m.home_team]]-d[idx[m.away_team]]+h)
        la=np.exp(a[idx[m.away_team]]-d[idx[m.home_team]])
        M=np.outer(poisson.pmf(np.arange(11),lh),poisson.pmf(np.arange(11),la))
        pH=np.tril(M,-1).sum(); pD=np.trace(M); pA=np.triu(M,1).sum()
        s=pH+pD+pA; pH,pD,pA=pH/s,pD/s,pA/s
        real = 'H' if m.home_goals>m.away_goals else ('D' if m.home_goals==m.away_goals else 'A')
        ll.append(-np.log(max({'H':pH,'D':pD,'A':pA}[real],1e-12)))
        mae.append(abs(lh-m.home_goals)+abs(la-m.away_goals))
    return np.mean(ll), np.mean(mae), len(ll)

print("Corte: treina antes da data, mede nos jogos a partir dela (so 2026)\n")
print(f"{'corte':<12}{'n teste':>8}{'log-loss s/ boost':>20}{'log-loss c/ boost':>20}{'melhor':>10}")
for corte in ('2026-07-01','2026-08-01','2026-08-15'):
    c=pd.Timestamp(corte)
    treino=df[df.date<c]; teste=df[(df.date>=c)&(df.season==2026)]
    if len(teste)<20: continue
    sem=avaliar(ajustar(treino,1.0),teste)
    com=avaliar(ajustar(treino,6.0),teste)
    melhor='sem boost' if sem[0]<com[0] else 'com boost'
    print(f"{corte:<12}{sem[2]:>8}{sem[0]:>20.4f}{com[0]:>20.4f}{melhor:>10}")
