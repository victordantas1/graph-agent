import pytest
from pydantic import ValidationError

from sentinela_graph.models.agent_outputs import (
    ImplementationSummary,
    PlanSummary,
    Verdict,
)


def test_plan_summary_vazio_ainda_tem_suposicoes():
    # "Suposicoes" e a valvula que substitui a pergunta ao humano: a secao
    # existe sempre, ainda que vazia.
    plano = PlanSummary()
    assert plano.suposicoes == []
    assert plano.bugs == []


def test_plan_summary_round_trip():
    plano = PlanSummary(
        bugs=["tracing perde o span em erro 500"],
        features=["exportar custo por agente"],
        arquivos=["app/src/modules/tracing/tracing.service.ts"],
        riscos=["latencia adicional no hot path"],
        suposicoes=["a spec nao diz o sampling; assumido 100%"],
    )
    assert PlanSummary.model_validate_json(plano.model_dump_json()) == plano


def test_verdict_aprovado_dispensa_achado():
    veredito = Verdict(agente="review_adv", attempt=0, aprovado=True, evidencia="diff limpo")
    assert veredito.achados == []


def test_verdict_reprovado_sem_achado_e_rejeitado():
    # Reprovar sem dizer o que esta errado nao alimenta o findings_digest.
    with pytest.raises(ValidationError):
        Verdict(agente="qa_func", attempt=1, aprovado=False, evidencia="curl 500")


def test_verdict_reprovado_com_achado_e_valido():
    veredito = Verdict(
        agente="qa_func",
        attempt=1,
        aprovado=False,
        achados=["POST /traces devolve 500 sem body"],
        evidencia="curl -X POST localhost:3000/traces",
    )
    assert veredito.achados


def test_verdict_de_agente_desconhecido_e_rejeitado():
    with pytest.raises(ValidationError):
        Verdict(agente="implement", attempt=0, aprovado=True, evidencia="e")


def test_verdict_round_trip():
    veredito = Verdict(
        agente="review_adv",
        attempt=2,
        aprovado=False,
        achados=["teste nao cobre o caminho de erro"],
        evidencia="git diff origin/develop...HEAD",
    )
    assert Verdict.model_validate_json(veredito.model_dump_json()) == veredito


def _impl(**overrides) -> ImplementationSummary:
    campos = {
        "tipo": "feat",
        "escopo": "tracing",
        "resumo": "instrumenta o tracing das requisicoes com Langfuse",
        "mudancas": ["tracing.service.ts: cria o span por requisicao"],
        "arquivos_tocados": ["app/src/modules/tracing/tracing.service.ts"],
        "comandos_validacao": ["npx jest app/src/modules/tracing/tracing.service.spec.ts"],
    }
    campos.update(overrides)
    return ImplementationSummary(**campos)


def test_implementation_summary_round_trip():
    impl = _impl()
    assert ImplementationSummary.model_validate_json(impl.model_dump_json()) == impl


def test_implementation_summary_sem_comando_de_validacao_e_rejeitado():
    # A secao "Como validar" do MR nao pode sair vazia.
    with pytest.raises(ValidationError):
        _impl(comandos_validacao=[])


def test_tipo_de_commit_fora_do_vocabulario_e_rejeitado():
    with pytest.raises(ValidationError):
        _impl(tipo="feature")
