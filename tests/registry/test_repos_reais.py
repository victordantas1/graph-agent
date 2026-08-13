"""O registry real, checado contra a tabela normativa da spec.

Os testes sem marca rodam em qualquer maquina: so leem o YAML. Os marcados
`requires_nomos` exigem /home/victor/nomos e sao pulados fora dela.
"""

import shlex
import shutil

import pytest

from sentinela_graph.registry import load_registry
from sentinela_graph.shell import run_command

REGISTRY = load_registry()

# Spec, secao "Registry de repos". Estes valores sao normativos.
TABELA = {
    "nomos-api": ("app", "develop", "glab", "npx jest {arquivo}", "http"),
    "nomos.pro": (".", "develop", "glab", "yarn test {arquivo}", "playwright"),
    "monitor-search": ("app", "develop", "glab", "npm test {arquivo}", "none"),
    "gov-open-data": ("app", "develop", "glab", "npm test {arquivo}", "none"),
    "official-diaries": (".", "develop", "glab", "pytest {arquivo}", "none"),
    "nomos-tldr": (".", "main", "gh", "npx jest {arquivo}", "none"),
}


def test_os_seis_repos_estao_no_registry():
    assert set(REGISTRY.repos) == set(TABELA)


@pytest.mark.parametrize("nome", sorted(TABELA))
def test_entrada_bate_com_a_tabela_da_spec(nome):
    root, base, forge, teste, qa_mode = TABELA[nome]
    cfg = REGISTRY.repo(nome)
    assert (cfg.root, cfg.base, cfg.forge, cfg.qa_mode) == (root, base, forge, qa_mode)
    # A spec e normativa sobre QUAL runner roda, nao sobre o wrapper
    # (`uv run`) nem sobre flags obrigatorias (--watchAll=false, sem a qual
    # o CRA fica em watch e o gate nunca termina). Entao os tokens da spec
    # tem que aparecer em ordem dentro do template, nao serem iguais a ele.
    assert _e_subsequencia(teste.split(), cfg.test.split()), cfg.test
    assert "{arquivo}" in cfg.test


def _e_subsequencia(esperados: list[str], tokens: list[str]) -> bool:
    restante = iter(tokens)
    return all(token in restante for token in esperados)


@pytest.mark.parametrize("nome", sorted(TABELA))
def test_toda_entrada_declara_o_estado_da_verificacao(nome):
    # Criterio de aceite da #22: divergencias registradas no proprio YAML.
    notas = REGISTRY.repo(nome).notas
    assert notas.startswith("NAO VERIFICADO") or notas.startswith("verificado em ")


def test_so_nomos_api_e_nomos_pro_tem_qa_funcional():
    executaveis = {n for n, c in REGISTRY.repos.items() if c.qa_mode != "none"}
    assert executaveis == {"nomos-api", "nomos.pro"}


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_repo_canonico_existe(nome):
    canonico = REGISTRY.caminho_canonico(nome)
    assert (canonico / ".git").exists(), f"{canonico} nao e um clone git"


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_copy_untracked_existe_de_verdade_no_repo_canonico(nome):
    # Criterio de aceite da #22. Sem esses arquivos o install morre.
    canonico = REGISTRY.caminho_canonico(nome)
    ausentes = [
        alvo for alvo in REGISTRY.repo(nome).copy_untracked if not (canonico / alvo).exists()
    ]
    assert not ausentes, f"{nome}: copy_untracked inexistente: {ausentes}"


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_o_binario_de_cada_comando_existe_no_path(nome):
    # Checagem barata e de falha clara quando o binario nem existe. Nao
    # substitui o teste abaixo: `npm` no PATH nao diz nada sobre os scripts.
    cfg = REGISTRY.repo(nome)
    comandos = [cfg.install, cfg.build, cfg.lint, cfg.format_check, cfg.test, cfg.serve]
    faltando = [c for c in comandos if c and shutil.which(shlex.split(c)[0]) is None]
    assert not faltando, f"{nome}: binario ausente em {faltando}"


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_build_lint_e_format_check_saem_com_zero_no_canonico(nome):
    """Step 6 da Task 2 mecanizado: e este teste que licencia o `verificado em`.

    O plano manda rodar `npm run build && npm run lint && npx prettier
    --check .` a mao em cada repo antes de trocar `NAO VERIFICADO` por
    `verificado em AAAA-MM-DD`. Enquanto isso morava so no texto do plano,
    um operador podia rodar `-m requires_nomos`, ver verde vindo do
    `shutil.which` e concluir que tinha verificado — sem ter executado
    script nenhum. Verde aqui e a condicao para trocar o prefixo em `notas`;
    vermelho aqui nomeia o comando que diverge do repo real.

    Exige `install` ja rodado no canonico (node_modules/.venv presentes).
    """
    cfg = REGISTRY.repo(nome)
    cwd = (REGISTRY.caminho_canonico(nome) / cfg.root).resolve()
    assert cwd.is_dir(), f"{nome}: root {cfg.root!r} nao existe em {cwd}"

    for comando in (cfg.build, cfg.lint, cfg.format_check):
        resultado = run_command(comando, cwd)
        assert resultado.passou, (
            f"{nome}: `{comando}` em {cwd} saiu com {resultado.exit_code}"
            f"{' (timeout)' if resultado.timed_out else ''}:\n{resultado.saida}"
        )
