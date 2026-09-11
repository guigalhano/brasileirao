"""
Busca em rede com nova tentativa -- e a distincao entre "o terceiro caiu" e
"o nosso codigo esta errado".

POR QUE ISSO EXISTE
-------------------
Em agosto o pipeline passou a falhar alto em qualquer erro de coleta. Isso
corrigiu um problema real: o `continue-on-error: true` deixava o
atualizar_historico_cartola.py quebrar todo dia com KeyError enquanto o
GitHub Actions ficava verde e o historico de scouts congelava.

Mas a correcao foi longe demais. Entre 08 e 09 de setembro o
football-data.co.uk devolveu HTTP 503 por cerca de dois dias, e como o
ingerir_resultados.py e o primeiro passo de coleta, ele derrubou o job
inteiro -- inclusive a atualizacao do mercado do Cartola, que nao tem nada a
ver com aquela fonte. O site ficou cinco dias sem atualizar (05/09 a 10/09)
por causa de um servidor de terceiro fora do ar.

Os dois casos NAO sao o mesmo e nao merecem a mesma resposta:

  - 503, timeout, conexao recusada: o terceiro caiu. Nao ha nada a consertar
    no nosso lado, e a proxima execucao (3x por dia) provavelmente resolve.
    Tentar de novo e, se insistir, seguir sem aquela fonte.

  - KeyError, coluna que sumiu, nome de time desconhecido, JSON invalido: o
    contrato com a fonte mudou ou o nosso codigo esta errado. Isso PRECISA
    quebrar alto, senao vira o bug de agosto de novo.

Quem decide e o script que chama, porque e ele que sabe se a fonte e
essencial. O que este modulo garante e que a diferenca fique explicita no
tipo da excecao, em vez de virar um `except Exception` que engole tudo.

A rede de seguranca de seguir sem uma fonte e o verificar_integridade.py:
se os resultados atrasarem demais, ele bloqueia a publicacao. Degradar nao
significa publicar qualquer coisa.
"""
import time

import requests

# Codigos que sao "o servidor caiu / esta sobrecarregado", nao "voce errou".
# 429 entra aqui: e limite de taxa, resolve esperando.
HTTP_TRANSITORIO = {408, 425, 429, 500, 502, 503, 504}

TENTATIVAS_PADRAO = 3
ESPERA_INICIAL = 3.0     # segundos; dobra a cada tentativa


class FonteIndisponivel(RuntimeError):
    """A fonte esta fora do ar ou inacessivel agora.

    Nao e defeito nosso. Quem chama decide entre abortar ou seguir sem ela.
    """


class RespostaInvalida(RuntimeError):
    """A fonte respondeu, mas com algo que nao entendemos.

    Contrato mudou, ou o nosso parser esta errado. Isso tem que quebrar alto.
    """


def buscar(url, *, tentativas=TENTATIVAS_PADRAO, espera=ESPERA_INICIAL,
           timeout=30, headers=None, params=None, descricao=None):
    """GET com nova tentativa em falha transitoria.

    Devolve o objeto Response. Levanta FonteIndisponivel se o problema for
    do outro lado (5xx, timeout, conexao), e RespostaInvalida em 4xx que nao
    seja limite de taxa -- 404 e 401 nao melhoram tentando de novo, sao
    contrato errado.
    """
    nome = descricao or url
    ultimo = None

    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers,
                                params=params)
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code == 200:
                return resp
            if resp.status_code in HTTP_TRANSITORIO:
                ultimo = f"HTTP {resp.status_code}"
            else:
                # 404, 401, 403... tentar de novo so gasta tempo.
                raise RespostaInvalida(
                    f"{nome} respondeu HTTP {resp.status_code} -- isso nao e "
                    f"queda temporaria, e contrato errado (URL mudou? chave "
                    f"invalida?)")

        if tentativa < tentativas:
            pausa = espera * (2 ** (tentativa - 1))
            print(f"  [{nome}] {ultimo} -- tentativa {tentativa}/{tentativas}, "
                  f"nova tentativa em {pausa:.0f}s")
            time.sleep(pausa)

    raise FonteIndisponivel(
        f"{nome} indisponivel apos {tentativas} tentativas ({ultimo})")


def buscar_json(url, **kwargs):
    """Como buscar(), mas devolve o JSON ja decodificado.

    JSON quebrado e RespostaInvalida, nao indisponibilidade: o servidor
    respondeu 200 com corpo que nao da pra ler.
    """
    resp = buscar(url, **kwargs)
    try:
        return resp.json()
    except ValueError as e:
        raise RespostaInvalida(
            f"{kwargs.get('descricao') or url} respondeu 200 mas o corpo nao "
            f"e JSON valido: {e}") from None
