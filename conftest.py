# Importado pelo pytest antes dos modulos de teste. Garante que o
# LANGGRAPH_STRICT_MSGPACK definido no pacote valha mesmo em testes que
# importam langgraph direto.
import sentinela_graph  # noqa: F401
