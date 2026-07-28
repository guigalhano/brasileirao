@echo off
REM Wrapper pro Agendador de Tarefas do Windows: coleta o snapshot de xG
REM individual do WhoScored e, se houver rodada nova, faz commit e push.
REM
REM Roda localmente (IP residencial) -- o WhoScored bloqueia datacenter, entao
REM isto NAO pode ir pro GitHub Actions.
REM
REM Registrar (uma vez, num PowerShell/cmd normal):
REM   schtasks /Create /TN "BrasileiraoWhoScoredXG" /TR "D:\brasileirao\scripts\coletar_whoscored.bat" /SC DAILY /MO 3 /ST 10:00 /F
REM Rodar na hora pra testar:  schtasks /Run /TN "BrasileiraoWhoScoredXG"
REM Remover:                   schtasks /Delete /TN "BrasileiraoWhoScoredXG" /F

cd /d "D:\brasileirao"

REM Ajuste o caminho do python se necessario (ex: py em vez de python)
py scripts\coletar_whoscored_players.py
if errorlevel 1 (
  echo Coleta falhou ^(WhoScored fora do ar ou anti-bot^). Nada commitado.
  exit /b 1
)

git add data\whoscored_player_xg_history.csv data\whoscored_player_xg_2026_r*.csv

REM So commita se houver mudanca de verdade (rodada nova). Re-rodar a mesma
REM rodada nao gera diff por causa do dedup no script.
git diff --cached --quiet
if errorlevel 1 (
  for /f "tokens=2 delims==" %%d in ('wmic os get localdatetime /value ^| find "="') do set DT=%%d
  git commit -m "Snapshot automatico de xG individual do WhoScored (%DATE%)"
  git pull --no-edit origin main
  git push origin main
  echo Snapshot novo commitado e enviado.
) else (
  echo Sem rodada nova desde o ultimo snapshot. Nada a commitar.
)
