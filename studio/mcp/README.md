# Estúdio Ellie — ponte OpenClaw e MCP

O chat conversa com o agente `ellie-studio` pelo Gateway oficial. Autenticação e modelo pertencem ao OpenClaw; a ponte não cria uma cobrança de API de planejamento. Confira o login por assinatura e os fallbacks configurados no agente.

Leia [como conectar a assinatura](../../docs/OPENCLAW_ASSINATURAS.md). O iniciador do Estúdio abre a ponte em `127.0.0.1:8790`; o Gateway precisa estar aberto separadamente.

## Rodar

Node.js 24+. Instale com `npm ci`, depois `npm start`. Variáveis: `OPENCLAW_AGENTE` (ellie-studio), `OPENCLAW_URL` (ws://127.0.0.1:18789), `ESTUDIO_URL` (http://127.0.0.1:8000), `PORTA_MCP` (8790). `OPENCLAW_CONFIG_PATH` seleciona uma configuração local diferente; o token também pode vir do ambiente `OPENCLAW_GATEWAY_TOKEN`. Nunca versionar esses valores.

- `GET /ia/status`: verifica Gateway e existência do agente. Isso ainda não comprova uma resposta do modelo.
- `POST /ia/perguntar`: envia o contexto da produção e recebe a resposta. Cada pedido usa uma sessão própria; o aplicativo inclui a conversa recente e o plano atual.
- `/mcp`: transporte streamable HTTP; `node src/index.ts --stdio`: cliente MCP externo.

## Ferramentas ativas

`estado_estudio`, `criar_producao`, `ver_producao`, `definir_referencia`, `salvar_estrutura`, `consultar_custo`, `acompanhar_producao`, `montar_video`.

Não expõem execução de geração paga. O botão do aplicativo autoriza um lote concreto com cotação e teto. Os módulos antigos de avaliações e pilares permanecem no código legado, sem registro no MCP ativo.

O chat interno funciona pela ponte Gateway e recebe o contrato completo do aplicativo; não depende de cadastrar o MCP no OpenClaw. Para usar as ferramentas num cliente externo, configure nesse cliente o transporte suportado. Não copie uma seção de configuração antiga sem conferir a versão instalada.

## Conferir

Com a API aberta: `node test-smoke.mjs`. O teste inicia o transporte stdio e confere ferramentas e biblioteca sem geração paga.

O serviço escuta em loopback e não foi preparado como servidor público. Imagens de referência anexadas à conversa são enviadas ao provedor configurado no OpenClaw.
