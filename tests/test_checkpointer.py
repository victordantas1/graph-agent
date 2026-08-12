import logging

from langgraph.graph import END, START, StateGraph

from sentinela_graph.checkpointer import build_checkpointer, config_da_issue
from sentinela_graph.models.agent_outputs import Verdict
from sentinela_graph.models.issue import IssueRef
from sentinela_graph.models.routing import Routing
from sentinela_graph.models.workspace import Workspace
from sentinela_graph.state import GraphState

ISSUE = IssueRef(
    id="e5a1-uuid",
    identifier="NOM-716",
    title="Instrumentar o tracing com Langfuse",
    url="https://linear.app/nomos/issue/NOM-716",
    git_branch_name="victor/nom-716-langfuse",
    spec="Adicionar tracing por requisicao.",
    state="Doing",
)
ROUTING = Routing(
    repo="nomos-api",
    base="develop",
    forge="glab",
    dirs=["app/src/modules/tracing"],
    rota="feature",
    confianca=0.87,
    evidencia="grep langfuse",
)
WORKSPACE = Workspace(
    worktree_path="/home/victor/nomos/.worktrees/nomos-api/victor/nom-716",
    branch="victor/nom-716-langfuse",
    app_root="/home/victor/nomos/.worktrees/nomos-api/victor/nom-716/app",
    install_ok=True,
    port=4321,
)


def _carrega(state: GraphState) -> dict:
    return {"issue": ISSUE, "routing": ROUTING, "workspace": WORKSPACE}


def _review(state: GraphState) -> dict:
    return {
        "verdicts": [Verdict(agente="review_adv", attempt=0, aprovado=True, evidencia="diff limpo")]
    }


def _qa(state: GraphState) -> dict:
    return {"verdicts": [Verdict(agente="qa_func", attempt=0, aprovado=True, evidencia="curl 200")]}


def _grafo() -> StateGraph:
    """Fan-out minimo que reproduz a topologia review_adv || qa_func."""
    g = StateGraph(GraphState)
    g.add_node("carrega", _carrega)
    g.add_node("review", _review)
    g.add_node("qa", _qa)
    g.add_edge(START, "carrega")
    g.add_edge("carrega", "review")
    g.add_edge("carrega", "qa")
    g.add_edge("review", END)
    g.add_edge("qa", END)
    return g


def test_estado_sobrevive_ao_round_trip_pelo_sqlite_saver(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    db = tmp_path / ".state" / "graph.db"
    config = config_da_issue("NOM-716")

    with build_checkpointer(db) as saver:
        _grafo().compile(checkpointer=saver).invoke(GraphState(), config)

    # Segunda conexao: e o que o `--resume` faz, num processo novo.
    with build_checkpointer(db) as saver:
        valores = _grafo().compile(checkpointer=saver).get_state(config).values
    restaurado = GraphState.model_validate(valores)

    assert restaurado.issue == ISSUE
    assert restaurado.routing == ROUTING
    assert restaurado.workspace == WORKSPACE
    assert restaurado.workspace.port == 4321
    assert {v.agente for v in restaurado.verdicts_da_tentativa(0)} == {"review_adv", "qa_func"}
    assert not [r for r in caplog.records if "unregistered type" in r.getMessage()]


def test_o_banco_e_criado_no_caminho_pedido(tmp_path):
    db = tmp_path / "fundo" / ".state" / "graph.db"
    with build_checkpointer(db) as saver:
        saver.setup()
    assert db.exists()


def test_thread_id_e_o_identifier_da_issue():
    assert config_da_issue("NOM-716") == {"configurable": {"thread_id": "NOM-716"}}


def test_threads_diferentes_nao_se_misturam(tmp_path):
    db = tmp_path / ".state" / "graph.db"
    with build_checkpointer(db) as saver:
        app = _grafo().compile(checkpointer=saver)
        app.invoke(GraphState(), config_da_issue("NOM-716"))
        assert app.get_state(config_da_issue("NOM-999")).values == {}
