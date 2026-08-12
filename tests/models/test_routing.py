import pytest
from pydantic import ValidationError

from sentinela_graph.models.routing import Routing


def _routing(**overrides) -> Routing:
    campos = {
        "repo": "nomos-api",
        "base": "develop",
        "forge": "glab",
        "dirs": ["app/src/modules/tracing"],
        "rota": "feature",
        "confianca": 0.87,
        "evidencia": "grep 'langfuse' encontrou app/src/modules/tracing",
    }
    campos.update(overrides)
    return Routing(**campos)


def test_routing_valido():
    assert _routing().repo == "nomos-api"


@pytest.mark.parametrize("valor", [-0.01, 1.01])
def test_confianca_fora_de_zero_a_um_e_rejeitada(valor):
    with pytest.raises(ValidationError):
        _routing(confianca=valor)


@pytest.mark.parametrize("valor", [0.0, 1.0])
def test_confianca_aceita_os_extremos(valor):
    assert _routing(confianca=valor).confianca == valor


def test_rota_fora_do_vocabulario_e_rejeitada():
    with pytest.raises(ValidationError):
        _routing(rota="epico")


def test_forge_fora_do_vocabulario_e_rejeitada():
    with pytest.raises(ValidationError):
        _routing(forge="hub")


def test_routing_sem_diretorio_e_rejeitado():
    # Roteamento sem diretorio nao diz onde o agente trabalha.
    with pytest.raises(ValidationError):
        _routing(dirs=[])


def test_routing_sem_evidencia_e_rejeitado():
    # A escolha de repo exige evidencia no codigo: repo errado e um MR
    # inteiro jogado fora.
    with pytest.raises(ValidationError):
        _routing(evidencia="")
