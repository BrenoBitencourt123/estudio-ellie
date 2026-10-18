# Conectar o planejamento às assinaturas

O Estúdio usa a ponte Gateway que já existia no sistema enviado. O chat novo faz pedidos a essa ponte, sem chamar uma API de planejamento diretamente. Tokens do Gateway ficam no ambiente/configuração local do OpenClaw; não são incluídos em projetos, registros ou ZIP.

## Configuração

No Estúdio, abra **Conectar IA**. A janela explica as etapas e permite verificar novamente depois de abrir o Gateway; a confirmação da conta exige uma resposta real no chat.

### Se ainda não instalou

No Windows, siga o [instalador oficial](https://docs.openclaw.ai/start/getting-started). Ele oferece configuração guiada e pode detectar um login Codex/Claude CLI existente. Confirme que a rota escolhida é a assinatura desejada: a detecção também pode encontrar uma chave de API. Não envie tokens ou códigos de acesso pelo chat do Estúdio.

### OpenClaw neste computador

Neste computador, a instalação nativa foi concluída em 18/10/2026 e `--version` retornou **OpenClaw 2026.10.4 (383c124)**. Login ainda não concluído. Isso é o estado deste teste, não uma dependência fixada do pacote.

Use **abrir-openclaw.bat** para abrir o assistente clássico e escolher sua assinatura. O atalho usa `openclaw-local.ps1`, que encontra um Node compatível no PATH ou no runtime local do Codex; não altera o Node global. Em outro PC, instale Node 24.16+ ou 26.1+ e OpenClaw oficialmente. O wrapper espera a instalação npm do usuário; instalações em outro local devem usar sua CLI diretamente.

Para os comandos abaixo, se `openclaw` não funcionar no seu terminal por causa do Node antigo, substitua-o por `./openclaw-local.cmd` na pasta do projeto.

1. Instale/abra o OpenClaw e selecione o acesso por assinatura no fluxo oficial. Para ChatGPT/Codex, a documentação atual usa `openclaw models auth login --provider openai`; para Claude, use a opção de reaproveitar o login Claude CLI disponível no seu host.
2. Selecione um modelo realmente disponível para essa conta. Não copie identificadores antigos do sistema original nem configure API-key/fallback pago para contornar o limite.
3. Confira `openclaw agents list`. O script `configurar_openclaw.py` apenas prepara/registra `ellie-studio` com o workspace deste pacote e copia sua skill. Ele deixa a autenticação e a seleção de modelo sob controle do OpenClaw.
4. Com o Gateway aberto, inicie o Estúdio. A indicação de conexão depende de `agents.list` retornar o agente correto. “Ponte aberta” e “assinatura autenticada” são estados diferentes.

Depois de registrar o agente, confira `openclaw models status --agent ellie-studio`. Se faltar autenticação ChatGPT nesse agente, execute no computador do Gateway:

```powershell
openclaw models auth login --provider openai --agent ellie-studio
```

Conclua o fluxo no navegador e deixe o comando terminar. Confira o modelo, a autenticação e os fallbacks do agente novamente. Para Claude, use o fluxo Claude CLI da versão instalada; a documentação de autenticação descreve `claude auth login` seguido por `openclaw models auth login --provider anthropic --method cli --agent ellie-studio`. Disponibilidade e termos da conta continuam valendo.

Verifique `openclaw gateway status`. Se já estiver instalado como serviço, mantenha esse serviço aberto; se estiver no assistente em primeiro plano, preserve o terminal em execução. A instalação como serviço é uma etapa separada do OpenClaw.

### VPS, outro computador ou WSL

Configure e autentique o agente no ambiente que executa o Gateway. O script Python deste pacote usa o workspace local; não registre um caminho Windows como se ele existisse numa VPS Linux. Copie o workspace do agente para o host correto e registre esse caminho pela CLI oficial de lá.

A ponte precisa alcançar esse Gateway e receber a credencial por configuração local ou variável de ambiente. Use acesso privado/túnel conforme a documentação oficial; não exponha o Estúdio diretamente na internet. O pacote ainda não automatiza implantação remota ou encaminhamento Windows/WSL.

## Futuro repositório GitHub

O `.gitignore` exclui contas, configurações de autenticação, conversas/SQLite, logs, referências pessoais e vídeos. O ZIP de demonstração inclui mídias escolhidas para uso local; isso não significa que elas devam ser publicadas no GitHub. Confira os arquivos preparados para o primeiro commit. Nenhum repositório foi criado ou enviado por esta entrega.

O nome do agente é configurável em `.env` por `OPENCLAW_AGENTE`. `OPENCLAW_URL` aponta para o Gateway local. O token do Gateway pode ser resolvido da configuração local ou de `OPENCLAW_GATEWAY_TOKEN`, sem ser persistido pelo Estúdio.

Se sua configuração do OpenClaw usar uma API key, essa cobrança pertence à configuração do OpenClaw; o Estúdio não consegue transformar essa chave em assinatura. Garanta que o agente esteja associado à autenticação de assinatura escolhida. Não prometemos uso ilimitado: cotas e disponibilidade da conta continuam valendo.

## Fontes oficiais verificadas em 18/10/2026

- [OAuth e autenticação por assinatura](https://docs.openclaw.ai/oauth).
- [Configuração e autenticação](https://docs.openclaw.ai/gateway/authentication).
- [Gerenciamento de agentes/workspaces](https://docs.openclaw.ai/cli/agents).
- [Protocolo Gateway](https://docs.openclaw.ai/gateway/protocol).

Esses comandos/formatos podem variar entre versões. Use a CLI e o fluxo oficial instalados como fonte de verdade. O Estúdio não instala outro agente/modelo nem altera a conta silenciosamente.
