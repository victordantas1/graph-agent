from sentinela_graph.shell import CommandResult, run_com_retry, run_command


def test_captura_stdout_e_stderr_juntos(tmp_path):
    r = run_command("python -c \"import sys;sys.stderr.write('erro');print('ok')\"", tmp_path)
    assert r.passou
    assert "ok" in r.saida and "erro" in r.saida


def test_exit_code_nao_zero_nao_passa(tmp_path):
    r = run_command('python -c "raise SystemExit(3)"', tmp_path)
    assert not r.passou
    assert r.exit_code == 3


def test_comando_inexistente_nao_levanta(tmp_path):
    # Erro deterministico: vira resultado, e quem decide o que fazer e o no.
    r = run_command("comando-que-nao-existe-1234", tmp_path)
    assert not r.passou
    assert r.exit_code == 127


def test_timeout_marca_timed_out(tmp_path):
    r = run_command('python -c "import time;time.sleep(5)"', tmp_path, timeout=1)
    assert r.timed_out
    assert not r.passou


def test_roda_no_cwd_pedido(tmp_path):
    (tmp_path / "marcador.txt").write_text("x")
    r = run_command('python -c "import os;print(os.listdir())"', tmp_path)
    assert "marcador.txt" in r.saida


def test_retry_desiste_depois_das_tentativas():
    chamadas = []

    def falha(comando, cwd, timeout=None):
        chamadas.append(comando)
        return CommandResult(comando, 1, "rede caiu")

    r = run_com_retry("git fetch origin", None, tentativas=3, espera=0, run=falha)
    assert not r.passou
    assert len(chamadas) == 3


def test_retry_para_no_primeiro_sucesso():
    respostas = [CommandResult("x", 1, "rede"), CommandResult("x", 0, "ok")]

    def instavel(comando, cwd, timeout=None):
        return respostas.pop(0)

    r = run_com_retry("x", None, tentativas=3, espera=0, run=instavel)
    assert r.passou
    assert respostas == []
