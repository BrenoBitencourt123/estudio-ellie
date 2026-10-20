# Relatório de latência — OpenClaw

**Data:** 2026-10-19 · **Versão:** OpenClaw 2026.10.4 (383c124) · **Host:** Windows 11 (10.0.26300), i7-1255U (10 núcleos / 12 lógicos), 15,7 GB RAM, SSD 477 GB

**Modo do diagnóstico:** somente leitura, exceto três turnos triviais cronometrados (seção *Medições ao vivo*).

> **Etapa A aplicada em 2026-10-19** — ver [Etapa A: o que foi aplicado](#etapa-a-o-que-foi-aplicado-2026-10-19) no fim do documento. O corpo do relatório descreve o estado **antes** das correções.

---

## Os 3 ganhos mais rápidos

| # | Mudança | Evidência | Ganho medido/estimado | Esforço |
|---|---|---|---|---|
| **1** | **Reaproveitar a sessão em `perguntar()`**, em vez de criar uma `sessionKey` nova a cada pergunta (`studio/mcp/src/openclaw.ts:143`) | Turno frio **48,3 s** vs. turno quente na mesma sessão **19,1 s**, mesma pergunta ("Responda apenas: OK"). O frio gastou `in=29301, cacheRead=0`; o quente, `in=134, cacheRead=29184` | **−29 s por pergunta (−60%)**, medido | Baixo (1 linha) |
| **2** | **Encerrar os 7 processos `codex.js` órfãos e apurar por que não são recolhidos** | 7 processos filhos do gateway, 43–95 min de idade, **688 MB somados**, CPU ~0,2 s cada (pendurados, não trabalhando). RAM livre caiu de 2,1 GB para **1,1 GB** durante o diagnóstico | Libera ~690 MB; remove a pressão de memória que provoca a lentidão intermitente | Baixo (reversível) |
| **3** | **Desabilitar os ~20 plugins de provedor que você não usa** (`tools.profile: "full"` carrega 42 de 66) | O prompt de sistema fixo é de **29.301 tokens** com **55 ferramentas** para responder "OK" (5 tokens de saída). A contagem subiu de 41 para 55 ferramentas entre 18/10 e hoje | Corta a maior parte dos 29 k tokens fixos por turno frio; reduz o tempo até o primeiro token | Baixo–médio |

---

## 1. Arquitetura encontrada

### Onde roda

- **Instalação:** `C:\Users\breno\AppData\Roaming\npm\node_modules\openclaw` (npm global, `installKind: package`)
- **Config:** `C:\Users\breno\.openclaw\openclaw.json` (4.090 bytes, mais 6 backups)
- **Estado:** `C:\Users\breno\.openclaw\state\openclaw.sqlite` (3,35 MB, WAL saudável: `consecutiveBlocked: 0`)
- **Bancos por agente:** `.openclaw\agents\<id>\agent\openclaw-agent.sqlite` (main 680 KB, ellie-studio 1,61 MB, ellie-claude 938 KB)
- **Gateway:** processo **PID 23312**, `mode: local`, `ws://127.0.0.1:18789`, bind loopback, auth por token
- **Não está instalado como serviço** (`gatewayService.installed: false`) — roda como processo de primeiro plano iniciado à mão
- **Logs:** praticamente inexistentes. Só `.openclaw\logs\gateway-restart.log`, com **1 linha** de 18/10. Não há log de requisição, de turno ou de erro em arquivo.

### Modelos e fallbacks

| Papel | Modelo | Runtime | Contexto |
|---|---|---|---|
| Padrão (`agents.defaults.model`) | `openai/gpt-6.1-sol` | harness `codex` | 475.000 tokens efetivos |
| Utilitário (`utilityModel`) | `openai/gpt-6.1-sol` | codex | — |
| Agente `ellie-claude` | `anthropic/claude-opus-5-5` | **`claude-cli`** | 1.000.000 |
| 11 modelos Anthropic na allowlist | fable-5/5-1, haiku-5-5, opus-4-6/4-7/4-8/5/5-5, sonnet-4-6/5/5-5 | todos `claude-cli` | 1.000.000 |

**Autenticação:** assinatura via OAuth, não API por token. Dois perfis OpenAI (`openai:brenoventreschi123@gmail.com` e `openai:setup-ab9a9b27-…`). O custo reportado em todo turno é `cost.total: 0`, confirmando que não há cobrança por token.

**Cadeia de fallback do Estúdio** (`studio/mcp/src/openclaw.ts:30`, via `.env`): `ellie-claude` (Claude Opus 5.5) → `ellie-studio` (GPT-6.1-sol) → `ellie-studio`. O fallback é **sequencial, nunca paralelo** (comentário explícito na linha 242), e um agente que falha por motivo "persistente" fica **pausado 15 minutos** (`PAUSA_AGENTE_MS`).

**Nível de raciocínio:** o CLI aceita `--thinking off|minimal|low|medium|high|xhigh|adaptive|max|ultra`, mas **nenhum nível está configurado** em `openclaw.json` nem é passado pela ponte. Todo turno usa o padrão do provedor, igual para "Responda apenas: OK" e para uma tarefa complexa.

### Canais, ferramentas, plugins

- **Canais ativos: nenhum.** `channelSummary: []`
- **Plugins: 42 de 66 habilitados.** Os habilitados incluem ~20 provedores que não aparecem em nenhuma configuração de uso: `alibaba, azure-speech, deepgram, elevenlabs, fal, huggingface, kie, litellm, lmstudio, microsoft-foundry, minimax, nvidia, ollama, openrouter, runway, senseaudio, sglang, together, tts-local-cli, vllm, xai, github-copilot, copilot-proxy, opencode-go, cua-computer, geolocation`
- **Ferramentas por turno: 55** (era 41 em 18/10) — `session.started.data.toolCount`
- **Ponte MCP do Estúdio** (`studio/mcp`, porta 8790): **não estava escutando** durante o diagnóstico. O caminho de IA do Estúdio estava fora do ar (`netstat` não mostra 8790; só 8000 do uvicorn e 18789 do gateway).
- **Skills de plugin:** 2 (`browser-automation`, `canvas`), ambas symlinks para o dist

### Jobs agendados (5 crons)

| Job | Agenda | Último estado |
|---|---|---|
| `heartbeat:main` | a cada **30 min** | **falha sistemática**: 11 de 14 execuções com `heartbeat skipped: no-route`; também `cron-in-progress` e `requests-in-flight`. O `status` confirma `waitingForRoute: true` |
| `memory-core:memory-dreaming-promotion` | diário **03:00** | `lastDurationMs: 324164` = **5 min 24 s** de turno de agente. Uma execução anterior morreu em 61,8 s com `cron: isolated agent setup timed out before runner start` |
| `skill-collection-review:main` | semanal | agendado |
| `skill-collection-review:ellie-studio` | semanal | agendado |
| `skill-collection-review:ellie-claude` | semanal | agendado |

---

## 2. Medições ao vivo

Consumiram cota: 3 turnos triviais, ~11 tokens de saída no total. Pergunta idêntica nos três: `"Responda apenas: OK"`.

| Cenário | Parede (CLI) | `meta.durationMs` (gateway) | Turno do modelo (trajetória) | Tokens |
|---|---|---|---|---|
| `ellie-studio`, sessão **nova** | **48,3 s** | 30,6 s | **5,3 s** | `in=29301 out=5 cacheRead=0` |
| `ellie-studio`, **mesma** sessão | **19,1 s** | 7,0 s | **3,9 s** | `in=134 out=5 cacheRead=29184` |
| `ellie-claude` (Claude Opus 5.5), nova | **34,1 s** | 12,7 s | **sem telemetria** | `cacheWrite=77269` |

### Onde vão os 48 segundos do turno frio

```
48,3 s parede total
├── 17,7 s  overhead do CLI/conexão   (48,3 − 30,6)
├── 25,3 s  setup do agente/runtime   (30,6 − 5,3)  ← spawn do harness codex
└──  5,3 s  trabalho real do modelo   (trajetória)
             └── 5,0 s do prompt.submitted ao model.completed
```

**Só 11% do tempo é o modelo pensando.** Os outros 89% são montagem de sessão e overhead de cliente.

### Histórico de 16 turnos gravados (18/10, agentes main + ellie-studio)

| Métrica | Valor |
|---|---|
| Total por turno | min 1,5 s · **mediana 6,3 s** · p90 44,2 s · **máx 78,0 s** |
| Turnos sem ferramenta (n=11) | mediana **5,4 s** |
| Turnos com ferramenta (n=5) | mediana **44,2 s** |
| Tokens de entrada | min 417 · mediana 24.284 · máx 40.221 |
| `cacheRead` | zero em **10 dos 16** turnos |
| Compilação de contexto local | 36–142 ms (**não é gargalo**) |

**O tempo de "pensar depois da ferramenta" domina os turnos longos:**

| Turno | Até a 1ª ferramenta | Execução da ferramenta | **Pensando após o último resultado** | Total |
|---|---|---|---|---|
| c22de00b | 18,9 s | 8,2 s | **50,7 s** | 78,0 s |
| fd983bc8 | 5,2 s | 1,8 s | **36,9 s** | 44,2 s |
| 6ef3cca8 | 6,2 s | 1,6 s | **34,5 s** | 42,5 s |

As ferramentas em si são rápidas (o `bash` medido levou `durationMs: 514`). O custo é o modelo reprocessando um contexto de 27–40 k tokens depois de cada resultado.

---

## 3. Tabela de gargalos, por impacto

| # | Gargalo | Evidência | Causa provável | Correção proposta | Ganho estimado | Risco |
|---|---|---|---|---|---|---|
| **1** | **Sessão nova a cada pergunta**, logo cache sempre frio e setup de runtime repetido | `studio/mcp/src/openclaw.ts:143`: `sessionKey = agent:${AGENTE}:estudio-${Date.now()}-${uuid}`. Medido: frio 48,3 s / `cacheRead=0`; quente 19,1 s / `cacheRead=29184`. 10 de 16 turnos históricos com `cacheRead=0` | Chave derivada de `Date.now()` nunca repete. O caminho `conversar()` (linha 213) já usa sessão estável e é o único que aproveita cache (até `cacheRead=105600`) | Derivar a `sessionKey` do contexto (produção/aba), como já faz `conversar()`. Reaproveitar por N minutos | **−29 s/pergunta (−60%)**, medido | Baixo. Sessão longa acumula contexto; precisa de janela ou reset |
| **2** | **Setup do harness `codex` custa ~25 s** em toda sessão nova | `meta.durationMs` 30,6 s vs. turno de modelo 5,3 s (frio); 7,0 s vs. 3,9 s (quente). O delta cai de 25,3 s para 3,1 s com sessão reaproveitada | Spawn do processo `codex.js`, admissão de runtime e carga de 55 ferramentas por sessão | Resolvido em grande parte pelo nº 1. Avaliar pool de runtime se o OpenClaw expuser a opção | Incluído no nº 1 | Baixo |
| **3** | **7 processos `codex.js` órfãos, 688 MB; RAM livre em 1,1 GB** | `Win32_Process`: PIDs 22304, 19936, 20212, 24064, 7348, 20556, 25296 — todos filhos do gateway 23312, idades 43–95 min, CPU 0,0–0,2 s. RAM livre caiu de 2,1 para **1,1 GB** de 15,7 GB durante a sessão | Processos de sessão não recolhidos ao fim do turno. Cada sessão nova (nº 1) cria mais um | Encerrar os órfãos; apurar o vazamento no gateway. Monitorar após aplicar o nº 1 | Libera ~690 MB; **remove a causa mais provável da intermitência** | Baixo (encerrar processos ociosos) |
| **4** | **Gateway com 1,02 GB de RSS e crescendo** | `processMemory.rssBytes: 1011236864`; `heapUsed 383 MB / heapTotal 450 MB` (**85% do heap ocupado**, logo GC frequente). RSS observado subindo de 908 para 923, 957 e **1.020 MB** em ~90 min | Vazamento ou cache sem limite. Heap quase cheio força GC, e GC trava a thread única de JS — é exatamente isso que produz pausas intermitentes | Reiniciar o gateway (com aprovação) para medir o baseline; depois acompanhar o RSS. Avaliar `--max-old-space-size` | Elimina pausas de GC | Médio: reiniciar derruba sessões em andamento |
| **5** | **29.301 tokens fixos de prompt e 55 ferramentas por turno** | `session.started.data.toolCount: 55` (era 41 em 18/10). `usage.input: 29301` para responder 5 tokens. `tools.profile: "full"`, **42 de 66 plugins habilitados** | ~20 plugins de provedor sem uso (`alibaba`, `elevenlabs`, `ollama`, `vllm`, `xai`, `runway`, `minimax`, `together`, `sglang` e outros) registram ferramentas no prompt | Desabilitar os provedores não usados; considerar `tools.profile` mais enxuto | Corta a maior parte dos 29 k tokens no turno frio; acelera o 1º token | Baixo. Reversível por config |
| **6** | **Overhead de 12–21 s no cliente CLI** | Parede menos `meta.durationMs`: 17,7 s / 12,1 s / 21,4 s. `gateway.connectLatencyMs` = **9.278 / 12.170 / 12.093 / 8.930 ms** em 4 medições. **Mas o socket é rápido**: TCP 1–2 ms, handshake WS **1–4 ms**, `GET /health` **1 ms** (sondagem direta minha). E `CLI cleanup timed out: shared-state after 5000ms` em toda saída | O socket não é o problema: o custo está no handshake RPC autenticado e na sincronização inicial do cliente, mais 5 s fixos de timeout na limpeza de `shared-state` | Investigar o `hello`/sync do `GatewayClient`. Corrigir o timeout de 5 s na limpeza. Afeta todo comando CLI e toda reconexão da ponte | **−12 a −21 s** por chamada via CLI | Baixo para diagnosticar |
| **7** | **`openclaw status` leva 47–50 s** | 3 execuções: 50,5 s / 48,0 s / 47,5 s. Causas visíveis na saída: `gatewayService`: "Task Scheduler probe timed out after 1336 ms"; `nodeService`: "Scheduled Task inspection deadline expired"; `modelCatalog.workerFailures: 7`; "Model discovery could not refresh all providers" | Sondagens do Agendador de Tarefas do Windows que expiram, mais worker de catálogo de modelos falhando 7 vezes com retry | Não está no caminho do turno interativo, mas cega o diagnóstico. Apurar as 7 falhas do `modelCatalog` | Diagnóstico utilizável | Baixo |
| **8** | **Pensar após a ferramenta: 34–51 s** | c22de00b **50,7 s**; fd983bc8 **36,9 s**; 6ef3cca8 **34,5 s** — com a ferramenta levando só 1,6–8,2 s e `durationMs: 514` no `bash` medido | Contexto de 27–40 k tokens reprocessado após cada resultado, com nível de raciocínio no padrão do provedor | Ajustar `--thinking` por tipo de tarefa (ver nº 9); reduzir o volume dos `tool outputs` | Alto nos turnos com ferramenta | Médio: raciocínio menor pode piorar a qualidade |
| **9** | **Nenhum nível de raciocínio configurado** | `--thinking` existe no CLI (`off` até `ultra`) e **não aparece** em `openclaw.json` nem na ponte. O mesmo padrão vale para "Responda apenas: OK" e para planejar uma produção | Falta de configuração: tudo usa o default do provedor | Definir `thinking` baixo para o agente utilitário e tarefas simples; manter alto só onde decide | Reduz o tempo até o 1º token nas tarefas simples | Médio: afeta qualidade, testar por tipo de tarefa |
| **10** | **Heartbeat falhando a cada 30 min** | 11 de 14 `task_runs` com `heartbeat skipped: no-route`; `status`: `waitingForRoute: true`; `channelSummary: []` | Heartbeat ligado para o agente `main` sem nenhum canal de entrega configurado | Desligar o heartbeat enquanto não houver canal | Pequeno em CPU (≈0,4 s por execução), mas elimina ruído e 2 execuções por hora | Baixo |
| **11** | **Cron de memória com turno de 5 min 24 s** | `memory-dreaming-promotion`: `lastDurationMs: 324164`; execução anterior `timed_out` em 61,8 s com `isolated agent setup timed out before runner start`. 130 entradas de `memory-core` em `plugin_state_entries` | Turno de agente longo às 03:00. Se o horário coincidir com uso, compete pelo mesmo gateway de thread única | Confirmar que 03:00 é fora de uso; reduzir o escopo da promoção | Evita competição com sessões interativas | Baixo |
| **12** | **Fallback sequencial com timeout de até 600 s** | `openclaw.ts:191` `LIMITE_GATEWAY_MS = 180_000`; `tempoMaximoMs` padrão **600.000 ms**; linha 242: "Estourou o tempo: não dispara outro em paralelo"; `PAUSA_AGENTE_MS = 15 min` | Se o `ellie-claude` travar, o pedido espera até 10 min antes de tentar o GPT | Reduzir o timeout do primeiro agente (por exemplo 90–120 s) antes do fallback | Transforma uma espera de 10 min em 2 min no pior caso | Baixo |
| **13** | *(Hipótese)* **Defender sem exclusões para `.openclaw` e Node** | `RealTimeProtectionEnabled: True`. **Não foi possível ler as exclusões** — exige administrador: "Must be an administrator to view exclusions" | Varredura em tempo real de cada `node.exe`/`codex.js` que sobe encarece o spawn no Windows | Verificar como administrador; se não houver exclusão, adicionar para `.openclaw` e para os runtimes de Node | Potencialmente alguns segundos por spawn de sessão | Baixo, mas é decisão de segurança sua |

### O que não é gargalo (descartado com medição)

- **Rede e DNS:** `api.anthropic.com` DNS 23 ms / TCP443 54 ms · `chatgpt.com` 0 ms / 14 ms · `api.openai.com` 22 ms / 28 ms. Saudável.
- **Socket do gateway:** TCP loopback 1–2 ms, handshake WS 1–4 ms, `/health` 1 ms.
- **Compilação de contexto local:** 36–142 ms em todos os turnos.
- **Disco:** SSD saudável, 50,1 GB livres de 474,7 GB. SQLite WAL `complete`, `consecutiveBlocked: 0`, 78 KB de WAL.
- **CPU do host:** 32% de carga, 12 núcleos lógicos. O gateway em repouso usa **15,4% de um núcleo** (amostra de 20 s), não 76% — os 4.200 s acumulados são picos durante turnos. `eventLoop.degraded: false`, `delayP99Ms` 50,8 ms em repouso (sobe a 160 ms sob carga).
- **Startup do CLI em si:** `openclaw --version` leva **207–221 ms**. O custo está no `status` e na conexão, não em carregar o binário.
- **Tamanho dos bancos:** estado 3,35 MB, agentes até 1,61 MB. Irrelevante.
- **Compactação de contexto:** nenhum evento de compactação nos 16 turnos. Não houve.

---

## 4. O que não foi possível medir, e como passar a medir

| Lacuna | Por que | Como coletar |
|---|---|---|
| **Tempo até o primeiro token (TTFT)** | A trajetória só registra `prompt.submitted` e `model.completed`. Não há evento de primeiro delta | O caminho `conversar()` da ponte já recebe deltas (`deltaText`). Registrar o timestamp do primeiro delta na ponte e logar |
| **Todo o caminho `ellie-claude` (Claude Opus 5.5), hoje o agente primário do chat** | `trajectory_runtime_events` do `ellie-claude` está **vazia**. O runtime `claude-cli` não emite trajetória. Só sei `meta.durationMs: 12710` e `cacheWrite: 77269` | Rodar com `--log-level debug` e capturar a saída, ou instrumentar a ponte. **Sem isso, o caminho que você mais usa é invisível** |
| **429, retries e rotação de perfil de autenticação** | Nenhum registro em `task_runs`, `audit_events` (só `agent_run` 65 e `tool_action` 24) ou `diagnostic_events` (8, todos de escrita de config). Zero logs em arquivo | Subir o gateway com `--log-level debug` redirecionado para arquivo. Hoje **não existe nenhum log de requisição** |
| **Limites de taxa da assinatura** | O `status` não expõe nada sobre cota ou enfileiramento. `cost.total: 0` confirma assinatura, mas não mostra limite | `openclaw models status --agent <id>`. Verificar se o gateway expõe contadores de rate limit |
| **Causa das 7 falhas do `modelCatalog`** | `workerPools.modelCatalog.workerFailures: 7`, sem detalhe do erro | `--log-level debug` e repetir `openclaw models list` |
| **Exclusões do Windows Defender** | Exige administrador | `Get-MpPreference` em PowerShell elevado |
| **Baseline de memória do gateway** | O processo já estava com 90 min de uso ao começar o diagnóstico; não sei o RSS inicial | Reiniciar e medir RSS a cada 10 min (precisa da sua aprovação) |
| **Cold start do gateway** | `gateway_boot_lifecycle` tem 3 registros, sem duração | Cronometrar um `gateway restart` (precisa da sua aprovação) |

**A lacuna mais séria:** não há **nenhum log de requisição em arquivo**. `.openclaw\logs\` tem só 1 linha, de 18/10. Todo o diagnóstico acima saiu de SQLite e de medição ativa. Ativar `--log-level debug` com saída para arquivo é o pré-requisito para medir qualquer coisa de forma contínua.

---

## 5. Próximos passos — para você aprovar um a um

Nada abaixo foi aplicado.

### Etapa A — reversível, sem reiniciar nada

- **A1.** Reaproveitar a `sessionKey` em `perguntar()` (`studio/mcp/src/openclaw.ts:143`), seguindo o que `conversar()` já faz. *Ganho medido: −29 s por pergunta.*
- **A2.** Encerrar os 7 processos `codex.js` órfãos (PIDs 22304, 19936, 20212, 24064, 7348, 20556, 25296). *Libera ~690 MB.* São processos ociosos, mas **encerrar processos é escrita, preciso do seu OK.**
- **A3.** Desligar o `heartbeat:main` enquanto não houver canal configurado. *Remove 2 execuções falhas por hora.*
- **A4.** Reduzir o timeout do primeiro agente da cadeia de fallback de 600 s para 90–120 s. *Pior caso cai de 10 min para 2 min.*

### Etapa B — mexe em configuração

- **B1.** Desabilitar os ~20 plugins de provedor sem uso. *Corta a maior parte dos 29 k tokens fixos.* Requer recarregar o gateway.
- **B2.** Definir `thinking` baixo para o modelo utilitário e para tarefas simples, mantendo alto onde há decisão. *Reduz o tempo até o primeiro token.* **Pode afetar qualidade — sugiro testar em paralelo antes de fixar.**
- **B3.** Ativar `--log-level debug` com saída para arquivo, para passar a medir TTFT, 429 e retries de forma contínua.

### Etapa C — precisa reiniciar o gateway

- **C1.** Reiniciar o gateway e acompanhar o RSS a cada 10 min, para confirmar o vazamento (1,02 GB hoje) e medir o cold start.
- **C2.** Apurar o overhead de 12–21 s no handshake do cliente e o `CLI cleanup timed out: shared-state after 5000ms`.
- **C3.** Investigar as 7 falhas do worker `modelCatalog`.

### Fora de escopo, mas registrado

- A ponte MCP do Estúdio (porta **8790**) **não estava escutando** durante o diagnóstico — o caminho de IA do Estúdio está fora do ar. Isso não é latência, é indisponibilidade, e provavelmente explica eventuais mensagens de "o serviço de IA do Estúdio não está aberto".
- O gateway **não está instalado como serviço**. Roda como processo manual, então morre junto com a sessão que o iniciou.
- `update.deps.status: "unknown"`, motivo `"lockfile missing"`.

---

### Nota sobre a autenticação

Tudo acima preserva a assinatura OAuth. **Não recomendo migrar para API paga por token**: nenhum dos 13 gargalos tem como causa o modo de autenticação. O maior deles (nº 1, −29 s medidos) é uma linha de código na ponte, e os três ganhos rápidos somados não custam nada em cota — ao contrário, reduzem o consumo, porque hoje cada pergunta reprocessa 29 k tokens que o cache poderia servir.

---

## Etapa A: o que foi aplicado (2026-10-19)

Aprovada por você e aplicada por inteiro. Backup da configuração antes de qualquer escrita: `~/.openclaw/openclaw.json.antes-etapaA-20261019-172948`.

### A1 — Reaproveitar a sessão por escopo ✅ aplicado e verificado

**O que mudou:**
- `studio/mcp/src/openclaw.ts`: `perguntar()` ganhou o parâmetro `escopo` e um pool de sessões. Cada escopo guarda a sua `sessionKey` e só troca quando o contexto já não serve: **10 min sem uso**, **8 pedidos**, ou após falha/timeout (a sessão sai do pool para o próximo pedido começar limpo).
- `studio/mcp/src/index.ts`: o endpoint `/ia/perguntar` repassa `escopo` do corpo da requisição.
- `studio/server.py`: `perguntar_ia()` aceita `escopo`, e cada chamador passa o seu — `prompt`, `revisao`, `legenda`, `texto-tela`, `plano`, `estrategia`, `pauta`. Escopos diferentes nunca compartilham contexto.

**Verificação** (3 pedidos "Responda apenas: OK" pela ponte real):

| Pedido | Escopo | Tempo | `sessionKey` | `in` | `cacheRead` |
|---|---|---|---|---|---|
| 1º | `prompt` | 97,1 s | `estudio-prompt-…-43232ba0` | 28.538 | 0 |
| 2º | `prompt` | **8,3 s** | **a mesma** `…-43232ba0` | **166** | **28.416** |
| 3º | `legenda` | 13,1 s | `estudio-legenda-…-f9733307` (nova) | 22.522 | 6.016 |

**Ganho medido: 97,1 s → 8,3 s no mesmo escopo (−91%).** A entrada caiu de 28.538 para 166 tokens. O 3º pedido confirma que escopos diferentes seguem isolados, como projetado.

⚠️ **A ponte em execução (PID 30276) ainda roda o código antigo.** A mudança passa a valer quando o Estúdio/ponte for reiniciado — não reiniciei o seu aplicativo.

### A2 — Encerrar os processos `codex.js` órfãos ✅ aplicado

7 processos encerrados (PIDs 22304, 19936, 20212, 7348, 24064, 25296, 20556), todos confirmados ociosos antes: **0 s de CPU em 12 s de amostra**, idades de 60 a 112 min.

| | Antes | Depois |
|---|---|---|
| Processos `codex.js` | 7 | **0** |
| Commit em uso | 24,36 GB | 24,00 GB |
| RAM livre | 3,23 GB | 3,46 GB |
| RSS do gateway | 1.020 MB | **853 MB** |
| Handles do gateway | 625 | 499 |

**Correção honesta da minha estimativa:** o relatório previa ~690 MB liberados. O real foi **366 MB de commit**. Os 688 MB eram o *working set de pico*; o Windows já havia reduzido esses processos para 142 MB de memória privada quando os encerrei. O ganho colateral foi melhor que o previsto: o gateway soltou 167 MB e 126 handles junto.

**A causa raiz não foi corrigida** — os órfãos continuarão aparecendo até o vazamento ser resolvido. O A1 reduz muito a taxa de criação (menos sessões novas), mas vale reconferir a contagem em alguns dias.

### A3 — Desligar o heartbeat ✅ aplicado

Não foi direto: `openclaw cron disable` recusou (*"system-owned monitor jobs cannot be edited by cron clients"*), e remover `agents.defaults.heartbeat` **não bastou** — `resolveHeartbeatAgentIds` tem um fallback de ambiente (`tryResolveAmbientHeartbeatAgentId`) que reinscreve o agente padrão. O caminho correto é zerar a cadência: com `every` resolvendo para intervalo nulo, `resolveHeartbeatIntervalMs` devolve `null` e o heartbeat sai do ar.

Aplicado `agents.defaults.heartbeat = { "every": "0", "agentId": "main" }`. Confirmado no `status`:

```
main           enabled=False  every=disabled  everyMs=None
ellie-claude   enabled=False  every=disabled  everyMs=None
ellie-studio   enabled=False  every=disabled  everyMs=None
```

Fim das 2 execuções falhas por hora com `heartbeat skipped: no-route`. Para religar quando houver canal: `openclaw config set agents.defaults.heartbeat.every '"30m"'`.

### A4 — Prazo curto antes da reserva ✅ aplicado, ⚠️ não verificado em execução

**O que mudou** em `studio/mcp/src/openclaw.ts`, função `conversar()`:
- Agente que **não é o último da fila** espera no máximo `LIMITE_PRIMEIRO_AGENTE_MS = 120_000` (antes: os mesmos 600 s de todos).
- Ao estourar o prazo, o turno é **abortado pelo Gateway** (`chat.abort`, que existe no protocolo e só precisa da `sessionKey`) e só então a reserva é chamada. Antes o código fazia `break` e desistia; agora cai para o próximo agente.
- Se o `chat.abort` falhar, o código **para** em vez de seguir — mantém a garantia original de nunca ter dois modelos trabalhando em paralelo.

**Efeito esperado:** um `ellie-claude` travado custa ~2 min em vez de 10 min, e agora efetivamente cai para o GPT em vez de falhar o pedido.

**Não verifiquei em execução:** reproduzir exigiria travar um agente de propósito. A lógica está revisada e o módulo carrega, mas o caminho de timeout não foi exercitado.

### Verificação geral

- `python -m pytest tests/` → **66 testes, todos passam**
- `openclaw.ts` e `index.ts` carregam sem erro de sintaxe ou de tipo (Node 24 com type stripping)
- Gateway segue vivo e respondendo (`/health` 200)

### O que ficou de fora

Nada das Etapas B e C foi tocado: os ~20 plugins sem uso seguem habilitados, o `thinking` segue no padrão do provedor, não há log em arquivo, o gateway não foi reiniciado e o vazamento de memória (853 MB agora) segue sem diagnóstico. O overhead de 12–21 s no handshake do CLI também permanece.

---

## Faixas de trabalho paralelas no Estúdio (2026-10-20)

**Problema.** O Estúdio tinha um cadeado único por produção (`Processo.busy`, um `set` de ids). Qualquer
operação em segundo plano — imagem, Pinterest, narração, cotação, geração, acompanhamento, montagem —
ocupava esse cadeado, e `chat()` recusava a conversa enquanto ele estivesse tomado. A interface fechava o
botão de enviar (`podeEnviar` olhava `p.ocupado`). Não era limite técnico: era política.

**O que mudou.** `busy` virou um registro de trabalhos por faixa (`Processo.trabalhos`), com política por tipo:

| Faixa | O que entra | Quantas ao mesmo tempo |
|---|---|---|
| `midia` | imagem do GPT, busca no Pinterest | 3 |
| `voz` | ElevenLabs, sincronização de áudio enviado | 1 |
| `producao` | cotar, gerar, acompanhar, montar | 1 (mexe no plano e no dinheiro) |
| `conversa` | turno de IA | 1, e nunca bloqueada pelas outras |

A montagem pedida pela IA (`acao: "montar"`) passou a ir para a faixa `producao` em vez de segurar o turno
de conversa até o ffmpeg terminar.

**Escrita concorrente.** Com paralelismo, o padrão `store.get()` → mudar → `store.save()` perde escrita: o
turno de IA demora minutos e grava por cima da mensagem que a imagem escreveu no meio. Três mudanças:

- `Store.update(id, mudar)` faz ler-mudar-gravar dentro de um `BEGIN IMMEDIATE` só.
- `Processo._gravar(p, mensagens)` grava uma operação longa preservando a lista de mensagens fresca.
- `turno_ia` relê o registro assim que a resposta chega, antes de aplicar qualquer coisa.
- `save_plan` passou a acusar conflito quando o **plano** mudou, não quando a versão subiu — uma imagem
  pronta no meio de uma edição de estrutura não invalida mais a edição.

**Medição do risco que restava.** A dúvida era se o Gateway serializa por agente: a imagem usa sessão nova
(`openclaw.ts:362`) mas o mesmo `AGENTE`. Dois `/ia/perguntar` simultâneos com escopos diferentes:

```
A: terminou +77.5s (levou 77.5s)   B: terminou +77.7s (levou 77.7s)
total de parede 77.7s · soma 155.2s  → PARALELO
```

O Gateway atende sessões concorrentes do mesmo agente em paralelo. A faixa `midia` com 3 vagas se paga.

**Verificação:** `python -m pytest tests/` → 74 testes, todos passam (8 novos cobrem as faixas, a conversa
livre durante operação, o limite de 3 imagens, a exclusividade da faixa que gasta e as duas direções da
perda de escrita). `npm run build` no front passa com `tsc --noEmit`.

**Não medido:** o custo de CPU de rodar ffmpeg (montagem) junto de outras faixas. A montagem pode ficar
mais lenta quando há imagem e voz correndo ao mesmo tempo; não foi cronometrado.
