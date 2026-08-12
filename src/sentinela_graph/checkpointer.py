"""Checkpointer do grafo.

`thread_id` e o identifier da issue: um run por issue, retomavel com
`--resume NOM-716`. Substitui o `.linear-loop-state.md`, que guardava o
"onde parei" em prosa.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

CAMINHO_PADRAO = Path(".state/graph.db")


@contextmanager
def build_checkpointer(caminho: Path = CAMINHO_PADRAO) -> Iterator[SqliteSaver]:
    """Abre o checkpointer, criando o diretorio se preciso."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(caminho)) as saver:
        yield saver


def config_da_issue(identifier: str) -> dict:
    """Config do LangGraph para o run de uma issue."""
    return {"configurable": {"thread_id": identifier}}
