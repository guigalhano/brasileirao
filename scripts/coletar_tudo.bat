@echo off
setlocal enabledelayedexpansion

REM =====================================================================
REM  coletar_tudo.bat
REM  Roda o pipeline completo do Transfermarkt: clona a ferramenta,
REM  instala as dependencias direto com pip (sem poetry -- o poetry
REM  esbarrava no bug do "python.exe" fake da Microsoft Store no Windows),
REM  baixa o valor total do elenco dos 20 times da Serie A e o valor de
REM  mercado individual de cada jogador.
REM
REM  COMO USAR: coloque este arquivo NA MESMA PASTA que:
REM    - processar_transfermarkt_scraper.py
REM    - coletar_valores_jogadores.py
REM  e da um duplo-clique, ou rode "coletar_tudo.bat" no cmd.
REM
REM  Isso pode demorar de 20 a 40 minutos (principalmente a parte de valor
REM  por jogador, que faz uma chamada por jogador com pausa de seguranca).
REM  Nao feche a janela ate aparecer "TUDO PRONTO" no final.
REM =====================================================================

set SCRIPT_DIR=%~dp0
set REPO_DIR=%SCRIPT_DIR%transfermarkt-scraper
set SEASON=2026
set COMPETITION_HREF=/campeonato-brasileiro-serie-a/startseite/wettbewerb/BRA1

echo ============================================================
echo  PASSO 0: verificando pre-requisitos (python, git, pip)
echo ============================================================
where py >nul 2>nul
if errorlevel 1 (
    echo ERRO: nao encontrei o Python instalado ^(comando "py"^). Instale o Python
    echo e tente de novo: https://www.python.org/downloads/
    goto :erro
)
where git >nul 2>nul
if errorlevel 1 (
    echo ERRO: nao encontrei o Git instalado ^(comando "git"^). Instale o Git
    echo e tente de novo: https://git-scm.com/downloads
    goto :erro
)

echo.
echo ============================================================
echo  PASSO 1: clonando/preparando o transfermarkt-scraper
echo ============================================================
if exist "%REPO_DIR%" (
    echo Pasta "%REPO_DIR%" ja existe, pulando o clone.
) else (
    git clone https://github.com/dcaribou/transfermarkt-scraper "%REPO_DIR%"
    if errorlevel 1 goto :erro
)

cd /d "%REPO_DIR%"
echo Instalando dependencias direto com pip ^(sem poetry^)...
py -m pip install .
if errorlevel 1 goto :erro

echo.
echo ============================================================
echo  PASSO 2: baixando o valor total do elenco dos 20 times
echo ============================================================
echo {"type":"competition","href":"%COMPETITION_HREF%","competition_type":"first_tier"} > parent.json

py -m tfmkt clubs --season %SEASON% -p parent.json > clubs.json
if errorlevel 1 goto :erro
echo OK: clubs.json gerado.

echo.
echo ============================================================
echo  PASSO 3: baixando o perfil de cada jogador ^(pode demorar
echo           alguns minutos, sao ~500+ jogadores^)
echo ============================================================
type clubs.json | py -m tfmkt players > players.json
if errorlevel 1 goto :erro
echo OK: players.json gerado.

echo.
echo Copiando os arquivos JSON de volta para a pasta original...
copy /y clubs.json "%SCRIPT_DIR%brasileirao_clubes_2026.json" >nul
copy /y players.json "%SCRIPT_DIR%brasileirao_jogadores_2026.json" >nul

cd /d "%SCRIPT_DIR%"

echo.
echo ============================================================
echo  PASSO 4: processando o valor total por time
echo ============================================================
if not exist "%SCRIPT_DIR%processar_transfermarkt_scraper.py" (
    echo AVISO: nao encontrei processar_transfermarkt_scraper.py nesta pasta.
    echo Pulando esta etapa -- copie o script pra ca e rode-o manualmente depois.
) else (
    py "%SCRIPT_DIR%processar_transfermarkt_scraper.py" "%SCRIPT_DIR%brasileirao_clubes_2026.json"
    if errorlevel 1 goto :erro
)

echo.
echo ============================================================
echo  PASSO 5: instalando 'requests' e coletando valor por jogador
echo           ^(a parte mais demorada, ~15-25 minutos^)
echo ============================================================
py -m pip install requests
if errorlevel 1 goto :erro

if not exist "%SCRIPT_DIR%coletar_valores_jogadores.py" (
    echo AVISO: nao encontrei coletar_valores_jogadores.py nesta pasta.
    echo Pulando esta etapa -- copie o script pra ca e rode-o manualmente depois.
    goto :fim
)
py "%SCRIPT_DIR%coletar_valores_jogadores.py" "%SCRIPT_DIR%brasileirao_jogadores_2026.json"
if errorlevel 1 goto :erro

:fim
echo.
echo ============================================================
echo  TUDO PRONTO
echo ============================================================
echo Arquivos gerados nesta pasta:
echo   - brasileirao_clubes_2026.json      ^(bruto, por time^)
echo   - brasileirao_jogadores_2026.json   ^(bruto, por jogador^)
echo   - transfermarkt_times_resumo.csv    ^(valor total do elenco por time^)
echo   - valores_por_jogador.csv           ^(valor individual de cada jogador^)
echo.
echo Suba os dois arquivos .csv aqui no chat com o Claude para processar.
pause
exit /b 0

:erro
echo.
echo ============================================================
echo  ALGO FALHOU -- veja a mensagem de erro acima.
echo ============================================================
pause
exit /b 1
