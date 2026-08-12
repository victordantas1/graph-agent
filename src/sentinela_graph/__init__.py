"""Grafo de agentes que leva uma issue do Linear ate um MR aberto."""

import os

# Precisa vir antes de qualquer import de langgraph: o flag e lido uma unica
# vez, no import de langgraph.checkpoint.serde._msgpack. Sem ele, cada leitura
# de checkpoint loga um WARNING por modelo Pydantic do projeto.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

__version__ = "0.1.0"
