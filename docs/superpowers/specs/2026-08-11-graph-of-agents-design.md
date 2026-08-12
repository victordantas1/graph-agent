# Sentinela Graph Agent — Design

**Data:** 2026-08-11
**Status:** aprovado, pronto para plano de implementação

## Objetivo

Um grafo de agentes que leva uma issue do Linear — status **`To Do`** e label **`Ready`**,
as duas condições obrigatórias — até um Merge Request aberto no GitLab, **sem intervenção
humana durante a execução**. O humano escreve a spec
detalhada na issue; o grafo planeja, implementa em TDD, valida de forma adversarial e
abre o MR, reportando cada etapa de volta na issue.

O sistema é a versão determinística e executável da skill `linear-ready-loop`
(`~/.claude/skills/linear-ready-loop/SKILL.md`), que hoje roda de forma interativa e
mantém estado em prosa num arquivo markdown.

**Stack:** Python ≥3.12, LangGraph (engine de estado), Claude Agent SDK (LLM),
Langfuse (observabilidade), `glab`/`gh` (forjas), Linear GraphQL API.

## Decisões estruturantes

| Decisão | Escolha |
|---|---|
| Autonomia | Total. Sem gates humanos, sem `interrupt` do LangGraph. |
| Isolamento | Um `git worktree` por issue. |
| Validação funcional | Sobe o app no worktree e exercita de verdade, onde o repo permite. |
| Escopo de repos | Os 6 repos da Nomos desde a v1, via registry declarativo. |
| Ciclo de correção | Volta ao implementador; máx. 3 tentativas; depois desiste. |
| Método dos agentes | Skills próprias, versionadas no projeto, sem interatividade. |
| Divisão LangGraph × Agent SDK | Grafo fino, agentes com mandato estreito (Abordagem A). |
| Validadores | 2 em paralelo: revisor adversarial + QA funcional. |
| Ambiguidade de repo | Aborta e comenta no Linear. Nunca aposta. |
| Trigger | CLI manual, uma issue por execução. |
| Contexto do Linear | Injetado eagerly no prompt + uma ferramenta de leitura preguiçosa. |

### Abordagem A — grafo fino, agentes com mandato estreito

O LangGraph é o **único** orquestrador. Cada nó é ou determinístico (Linear API, git,
`glab`, subir o app, healthcheck) ou **exatamente uma sessão do Agent SDK** com mandato
estreito, ferramentas restritas, `cwd` no worktree e contrato de saída estruturado.
Artefatos volumosos (plano, laudos, logs) ficam em disco no worktree; o `state` do grafo
carrega ponteiros, vereditos e contadores.

Alternativas descartadas:

- **Grafo grosso com Agent SDK sub-orquestrando:** o contador de 3 tentativas viraria
  instrução em linguagem natural dentro de uma caixa opaca, sem checkpoint intermediário,
  e o revisor herdaria o contexto de quem implementou — o que anula a revisão adversarial.
- **Agente ReAct próprio, sem Agent SDK:** reconstruiria permissões, gestão de contexto e
  carregamento de skills que já funcionam.

## Topologia do grafo

```
                    fetch_queue ──(fila vazia)──> END
                         │
                    load_issue          (issue + comentários + relações)
                         │
                     classify           [Agent SDK · read-only]
                         │                → {repo, base, forge, dirs[], rota, confiança, evidência}
                    ┌────┴────┐
        (baixa conf.)│         │(alta conf.)
        abort_ambiguous       claim     [det: → Doing + comentário "repo X porque Y"]
              │                 │
             END        prepare_workspace  [det: fetch, worktree add, copy_untracked, install]
                                │
                          (rota Bug) diagnose  [Agent SDK]
                                │
                             plan        [Agent SDK · autonomous-planning]
                                │
                     ┌──────────┴──────────┐
          (subespecificado)                │
          abort_underspecified          post_plan  [det: comenta o plano na issue]
                    │                        │
                   END              ┌──> implement   [Agent SDK · autonomous-tdd]  <───┐
                                    │        │                                          │
                                    │    repo_gates  [det: build, lint, format, testes] │
                                    │        │                                          │
                                    │    serve_app   [det: só se qa_mode != none]       │ laudo
                                    │        │                                          │ unificado
                                    │   ┌────┴────┐  fan-out paralelo                   │
                                    │ review_adv  qa_func   (qa_func só se qa_mode != none)
                                    │   └────┬────┘                                     │
                                    │   verdict_gate ──(reprovado, tentativa<3)─────────┘
                                    │        │
                                    │  (reprovado, tentativa=3) ──> abort_failed ──> END
                                    │        │(aprovado)
                                    └──── open_mr   [det: add caminho-a-caminho, push, mr create]
                                             │
                                          report    [det: links + Review + comentário] ──> END
```

### Invariantes

1. **Toda escrita no Linear e no Git é nó determinístico.** Nenhum agente LLM recebe
   ferramenta de `glab`/`gh` nem de escrita no Linear. O LLM decide *conteúdo*; o grafo
   decide *quando* e executa.
2. **`serve_app` tem teardown garantido.** `try/finally` no nó, pidfile em `.state/`, e um
   limpador na saída do CLI, inclusive em `SIGINT`. Porta alocada dinamicamente.
3. **O contador de tentativas vive no `state`, não em prompt.** `repo_gates` reprovando
   também consome tentativa — senão um implementador que não faz o projeto compilar roda
   para sempre.
4. **Só o caminho feliz avança o status da issue.** Todo fracasso deixa a issue onde um
   humano a encontra, com label explicando por quê.

## Nós determinísticos

### `fetch_queue`

Linear GraphQL. Filtro **estrito**, todas as condições obrigatórias:

- time `Nomos` (prefixo `NOM-`)
- `state.name == "To Do"`
- label `Ready` presente
- `assignee == viewer` (o dono da `LINEAR_API_KEY`)

Ordena por prioridade e pega **uma** issue. Fila vazia → `END` com outcome `fila_vazia`,
exit code 0. Nunca relaxa o filtro.

Issue já em `Doing` não é elegível — evita que o grafo roube trabalho manual em andamento
ou colida com um run anterior que travou.

### `load_issue`

Busca e congela no `state`, antes de qualquer agente rodar:

- título, descrição (**a spec escrita pelo humano**), `gitBranchName`, labels, prioridade, estado
- **todos os comentários**, em ordem, com autor e data — o contrato mora aqui, não na descrição
- links e anexos
- relações (parent, sub-issues, blocked-by, related): **apenas título, estado e URL**, sem corpo

Congelar o contexto no checkpoint torna o run reproduzível: `--resume` e a investigação no
Langfuse mostram o que o agente viu, não o que a issue virou depois.

### `claim`

`state → Doing` e comentário informando repositório escolhido, rota e a evidência que
motivou a escolha.

### `prepare_workspace`

1. `git fetch origin` no repo canônico em `/home/victor/nomos/<repo>`
2. `git worktree add /home/victor/nomos/.worktrees/<repo>/<branch> -b <branch> origin/<base>`
   — `<branch>` é o campo `gitBranchName` da issue, nunca inventado
3. copia os arquivos de `copy_untracked` do registry (`.env`, service accounts JSON) do repo
   canônico para o worktree — sem eles nada roda
4. roda `install` do registry

O nó é **idempotente**: se o worktree já existe e está na branch esperada, reaproveita em vez
de falhar. Sem isso, `--resume` quebraria no primeiro nó. Worktree existente numa branch
*diferente* da esperada é erro determinístico.

Falha em qualquer outro passo → outcome `erro`.

### `repo_gates`

Executa, na ordem, os comandos do registry: `build`, `lint`, `format_check` e os testes
**apenas dos arquivos tocados**, derivados de `git diff --name-only origin/<base>...HEAD`,
um alvo por vez. Rodar a suíte inteira estoura memória nos repos de backend.

Falha → volta a `implement` com a saída do comando, consumindo uma tentativa.

### `serve_app`

Só executa quando `qa_mode != none`. Sobe o processo conforme o registry, aguarda o
healthcheck com timeout, expõe a porta alocada no `state`. Encerra em `finally`.

### `open_mr`

1. `git add` **caminho a caminho**, a partir do diff — nunca `-A`. Há service accounts
   `.json` untracked circulando em `nomos-api/app/` e em `/home/victor/nomos/`.
2. commit em Conventional Commits, **sem trailer `Co-Authored-By` e sem qualquer menção a
   Claude ou Anthropic** (regra GH-2 do `CLAUDE.md` do `nomos-api`)
3. `git push -u origin <branch>`
4. `glab mr create --target-branch <base>` (ou `gh pr create --base main` no `nomos-tldr`),
   não-interativo, com título e descrição renderizados pelo grafo

### `report`

`save_issue` com `links: [{url: <MR>, title: "MR !N"}]`, `state → Review`, e comentário
final estruturado. Não há integração automática entre as forjas e o Linear: os dois lados
são vinculados explicitamente.

**Nunca move para `Done`.** Quem fecha é o merge.

## Estado do grafo

Pydantic. Artefatos grandes ficam em disco; o estado guarda o caminho.

```python
issue           : IssueRef       # id, identifier, title, url, gitBranchName, spec, comments[], relations[]
routing         : Routing        # repo, base, forge, dirs[], rota, confianca, evidencia
workspace       : Workspace      # worktree_path, branch, app_root, install_ok, port
plan_path       : str            # docs/superpowers/plans/AAAA-MM-DD-nom-xxx.md, no worktree
plan_summary    : PlanSummary    # bugs[], features[], arquivos[], riscos[], suposicoes[]
attempt         : int            # 0..3
gate_report     : GateReport     # por comando: passou + saída
verdicts        : list[Verdict]  # {agente, aprovado, achados[], evidencia}
findings_digest : str            # laudo unificado devolvido ao implementador
impl_summary    : ImplementationSummary
mr              : MrRef | None
outcome         : Literal["mr_aberto","fila_vazia","ambiguo","subespecificado",
                          "reprovado_3x","erro"]
```

**Checkpointer:** `SqliteSaver` em `.state/graph.db`, `thread_id = issue.identifier`.
Substitui integralmente o `.linear-loop-state.md`: o "onde parei" vira estado tipado e
retomável. O CLI ganha `--resume NOM-716`, que reentra no nó que falhou com worktree e
contador de tentativas preservados.

## Registry de repos

YAML declarativo, uma entrada por repo. É o que faz 6 repos custarem configuração e não
código.

| repo | root | base | forge | testes | qa_mode |
|---|---|---|---|---|---|
| `nomos-api` | `app/` | develop | glab | `npx jest <arquivo>` | **http** |
| `nomos.pro` | `.` | develop | glab | `yarn test <arquivo>` | **playwright** |
| `monitor-search` | `app/` | develop | glab | `npm test <arquivo>` | none |
| `gov-open-data` | `app/` | develop | glab | `npm test <arquivo>` | none |
| `official-diaries` | `.` | develop | glab | `pytest <arquivo>` | none |
| `nomos-tldr` | `.` | **main** | **gh** | `npx jest <arquivo>` | none |

Cada entrada carrega também `install`, `build`, `lint`, `format_check`,
`copy_untracked: [...]` e — quando `qa_mode != none` — `serve` e `health`.

### Por que `qa_mode` não é uniforme

Só `nomos-api` é um servidor HTTP de vida longa. Os demais têm formas diferentes:

- `nomos.pro` é React (CRA + `react-app-rewired`); validação real exige browser, via
  **Playwright MCP**, não `curl`.
- `monitor-search` e `gov-open-data` são Cloud Functions com handlers CloudEvent
  (`exports.entrypoint`); não há endpoint para exercitar.
- `official-diaries` é Python `functions_framework.http`, mas o `CLAUDE.md` do repo declara:
  *"desenvolvimento: não existe — e fica assim, por decisão do time"*.
- `nomos-tldr` tem `docker-compose.yml`, porém entra na v1 sem QA funcional para não
  ampliar a superfície.

**Limitação declarada:** em 4 dos 6 repos a validação é revisão adversarial + gates, sem
prova empírica. O MR diz isso explicitamente (ver template).

## Os agentes

Seis sessões do Agent SDK, todas com `cwd` no worktree — o `CLAUDE.md` do repo-alvo é lido
naturalmente, e é dele que vêm gates e convenções.

| agente | pode | **não** pode | sessão |
|---|---|---|---|
| `classify` | Read, Grep, Glob, `fetch_linear_issue` | qualquer escrita | nova |
| `diagnose` *(só rota Bug)* | Read, Grep, Glob, Bash leitura, `fetch_linear_issue` | Edit, Write | nova |
| `plan` | Read, Grep, Glob, Write só em `docs/superpowers/plans/` | Edit em `src/`, Bash mutante | nova |
| `implement` | Read, Edit, Write, Bash (test/build) | `git push`, `glab`, `gh` | **retomada** entre tentativas |
| `review_adv` | Read, Grep, Glob, `git diff` | Edit, Write, Bash mutante | **sempre nova** |
| `qa_func` | Bash (curl/scripts), Read, Playwright MCP | Edit, Write | **sempre nova** |

Três consequências dessa tabela:

- **`implement` retoma a sessão entre tentativas; os validadores nunca.** O implementador
  precisa lembrar o que já tentou; os validadores precisam *não* lembrar — independência é
  o produto que eles entregam.
- **`bypassPermissions` torna `allowed_tools` o único guarda-corpo, e `Bash` fura todos.**
  Entra um hook `PreToolUse` com denylist de comandos aplicada a todos os agentes:
  `git push`, `git commit --no-verify`, `git add -A`, `glab`, `gh pr`, `rm -rf`. É o único
  ponto onde a restrição é real, e não uma promessa em prompt.
- **`qa_func` só existe quando `qa_mode != none`.** Nos outros repos o `verdict_gate` exige
  um veredito em vez de dois, e o comentário final diz que não houve verificação funcional.

### Contexto do Linear nos agentes

Injeção eager é a via principal: os seis agentes recebem no prompt a issue completa e todos
os comentários, congelados por `load_issue`.

Além disso, uma única ferramenta de leitura preguiçosa, `fetch_linear_issue(identifier)`,
implementada sobre o mesmo cliente GraphQL dos nós determinísticos e exposta como servidor
MCP in-process (`create_sdk_mcp_server`). Serve ao caso que a injeção não alcança:
referência descoberta em tempo de execução (um comentário citando `NOM-643`).

Não se usa o MCP remoto do Linear: ele é OAuth e quebra num run desassistido quando o token
expira. A escrita no Linear fica estruturalmente impossível para os agentes, em vez de
proibida por prompt.

### Skills autônomas

Versionadas em `prompts/skills/`, derivadas das superpowers com a interatividade removida.
**Carregadas como system prompt composto, não como skills descobríveis** — skill descoberta
é convite, e o agente pode escolher não invocar; em modo autônomo o método é obrigatório.
Além disso, o `cwd` está no repo-alvo, que tem `.claude/skills` próprio, com risco real de
colisão de nomes.

- **`autonomous-planning`** — substitui `writing-plans`. Entrada: a spec escrita pelo humano
  na issue. Regra central: **não perguntar**. Onde a spec for omissa, escolher o caminho mais
  conservador, registrar a escolha numa seção "Suposições" do plano, e seguir. Se o que falta
  for estrutural — a ponto de qualquer escolha produzir trabalho jogado fora —, emitir
  `underspecified` com as perguntas exatas, que viram o comentário `agent:needs-spec`. É a
  válvula de escape que substitui a pergunta ao humano.
- **`autonomous-tdd`** — vermelho-verde-refatora, sem checkpoints de confirmação.
- **`autonomous-diagnosis`** — causa raiz com evidência antes de qualquer correção.
- **`adversarial-review`** — mandato de *refutar*, não de aprovar; veredito estruturado com
  evidência por achado.
- **`functional-qa`** — verificações black-box derivadas **da issue, não do código**, contra o
  app rodando. Não basta rerodar a suíte do implementador: ele está em TDD, os testes dele já
  passam, e reexecutá-los é circular.

`brainstorming` **não existe no grafo**. Quem faz o brainstorming é o humano, ao escrever a
spec na issue.

## Seleção de repositório e diretórios

`classify` recebe a issue completa e tem leitura sobre os 6 repos. Devolve:

```python
Routing(repo=..., dirs=[...], rota="feature|bug|improvement",
        confianca=0.0..1.0, evidencia="grep/arquivos que sustentam a escolha")
```

Abaixo do limiar de confiança, ou com dois repos empatados, o grafo **aborta**: não move a
issue para `Doing`, comenta os candidatos com a evidência de cada um e o que desempataria, e
aplica `agent:blocked`. Repo errado significa MR inteiro jogado fora — falhar barato é
melhor que apostar.

A tabela problema→repo da skill `linear-ready-loop` entra no prompt do `classify` como
conhecimento de partida, mas a decisão exige evidência no código, não só a tabela.

## Ciclo de correção

`verdict_gate` aprova apenas com **todos** os vereditos aplicáveis positivos. Qualquer
reprovação:

- `attempt += 1`
- `attempt < 3` → volta a `implement` com o `findings_digest` unificado
- `attempt == 3` → `abort_failed`

`repo_gates` reprovando entra na mesma contagem.

## Prestação de contas

O grafo **nunca sabe se a issue foi resolvida**. Seu estado terminal de sucesso é "MR aberto
e issue em `Review`". Quem resolve é o merge. Fechar esse laço (polling do MR) fica **fora
da v1**.

### Canal 1 — Linear

| outcome | status final | label | comentário |
|---|---|---|---|
| `mr_aberto` | **Review** | — | resumo da implementação + URL do MR + o que foi verificado |
| `ambiguo` | fica em **To Do** | `agent:blocked` | repos candidatos, evidência, o que desempata |
| `subespecificado` | fica em **To Do** | `agent:needs-spec` | as perguntas exatas que a spec não responde |
| `reprovado_3x` | fica em **Doing** | `agent:failed` | as 3 tentativas, laudo de cada uma, branch e worktree |
| `erro` | fica em **Doing** | `agent:error` | nó que quebrou, stack, o que já tinha sido feito |

As 4 labels são criadas de forma idempotente no primeiro uso e removidas quando um run
posterior tem sucesso.

### Canal 2 — CLI

Exit codes: `0` mr aberto ou fila vazia, `10` ambíguo, `11` subespecificado, `12` reprovado
3x, `1` erro. Mais um bloco final legível com issue, repo, branch, tentativas, vereditos e
URL. Exit code distinto permite que um cron futuro reaja sem parsear texto.

### Canal 3 — Langfuse

Chaves já presentes no `.env`. Um trace por run, `session_id = <identifier da issue>`, tags
com outcome e repo, um span por nó, custo em tokens por agente. É onde se investiga um
`reprovado_3x` sem reler log.

### Ledger

`.state/runs.jsonl`, append-only, uma linha por run terminal: issue, outcome, tentativas,
duração, custo, MR. Responde "quantos MRs foram abertos essa semana e quantos travaram" sem
depender de o Langfuse estar de pé.

## Formato do MR

**O MR é renderizado pelo grafo a partir do `state`, não escrito livremente pelo LLM.** Os
agentes devolvem objetos (`ImplementationSummary`, `Verdict`); o nó preenche um template
fixo.

**Título:** `<tipo>(<escopo>): <resumo imperativo em pt-BR>`, Conventional Commits (regra GH-1
do `nomos-api`). `tipo` deriva da rota (`Bug` → `fix`, senão `feat`/`refactor`/`chore`
conforme o plano); `escopo` vem do módulo tocado.

**Descrição:**

```markdown
## Contexto
<o problema, extraído da spec da issue — 1 a 3 frases>

## O que mudou
- <por módulo/arquivo, do ImplementationSummary>

## Como validar
<comandos exatos que qualquer pessoa roda para reproduzir>

## Verificação executada
- Gates: build / lint / format / testes (N arquivos tocados)
- Revisão adversarial: APROVADO — N achados endereçados na tentativa M
- QA funcional: APROVADO — <endpoints/fluxos exercitados>
  | NÃO EXECUTADO — repo sem ambiente executável (qa_mode=none)

## Suposições
- <as suposições registradas pelo plano onde a spec era omissa>

## Issue
[NOM-716 — <título>](<url>)
```

A linha do QA nunca é omitida quando não roda: diz "NÃO EXECUTADO" em voz alta. Um MR
silencioso sobre o que não verificou é pior que um MR sem verificação.

## Tratamento de erros

Duas classes, tratadas de formas opostas:

- **Transiente** (5xx do Linear, rede, rate limit da Anthropic, `install` instável): retry com
  backoff exponencial, máximo 3, **dentro do nó**. Não consome tentativa do ciclo de correção
  — o implementador não errou.
- **Determinístico** (comando inexistente, worktree já existe, `LINEAR_API_KEY` ausente,
  healthcheck estourado): falha imediata, sem retry, outcome `erro`.

Complementos:

- **Timeout por nó:** `classify` 5min, `diagnose` 20min, `plan` 20min, `implement` 45min,
  `review_adv` e `qa_func` 20min cada. Timeout é erro determinístico.
- **Worktree preservado em qualquer fracasso**, removido só em `mr_aberto`. Depurar um
  `reprovado_3x` sem o worktree é impossível.
- Crash duro deixa o checkpoint intacto; `--resume <identifier>` reentra no nó que morreu.

## Estratégia de testes do próprio grafo

O projeto se constrói em TDD. O alvo dos testes é escolhido:

- **Nós determinísticos** — unit tests com dublês do cliente Linear e do git. É onde mora a
  maior parte do risco real: montar o filtro da fila, derivar arquivos do diff, renderizar o MR.
- **Roteamento condicional** — o teste de maior valor do projeto. Dado um `state` sintético, o
  `verdict_gate` roteia certo em toda a matriz: aprovado/reprovado × tentativa 0,1,2,3 ×
  `qa_mode` none/http/playwright. Um bug aqui custa um loop infinito ou um MR aberto sem
  validação.
- **Agentes** — não se testa o LLM; testa-se o contrato: que a saída estruturada parseia, que
  saída malformada vira erro claro, e que a denylist do `PreToolUse` realmente barra `git push`.
- **End-to-end offline** — repo de fixture com `git init` e remoto local, cliente Linear falso,
  agentes falsos com respostas gravadas. Prova a topologia inteira sem gastar token nem tocar
  no Linear.

## Fora de escopo na v1

- Polling do MR para saber se foi mergeado (o grafo termina em `Review`).
- Execução de várias issues em paralelo — uma issue por run, worktree/porta/estado únicos.
- Cron. O CLI é manual; o cron vira um wrapper depois que o fluxo estabilizar, e precisará de
  lock em disco.
- QA funcional em `monitor-search`, `gov-open-data`, `official-diaries` e `nomos-tldr`.
- Mover issues para `Done` — isso é do merge, nunca do agente.
