import os

import sentinela_graph


def test_pacote_expoe_versao():
    assert sentinela_graph.__version__ == "0.1.0"


def test_pacote_ativa_msgpack_estrito():
    # Precisa valer no import do pacote: o langgraph le esse flag no import
    # dele, e depois disso mudar a variavel nao tem efeito.
    assert os.environ["LANGGRAPH_STRICT_MSGPACK"] == "true"
