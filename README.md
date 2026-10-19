# Estúdio Ellie — produção por conversa

Você conversa com a diretora de produção. Ela organiza o vídeo e mostra perguntas, seletores de referências, plano e orçamento conforme precisar. As escolhas e a conversa ficam salvas. Sem avaliações, métricas de rede social ou escolha de pilares.

Esta versão evolui o sistema enviado em `estudio-ellie.zip`: preserva a biblioteca, o extrator de quadros, a ponte OpenClaw e o código anterior de geração/edição. O caminho principal foi substituído por produção conversacional com Dreamina e montagem local. O ZIP original permanece intacto. Veja [as mudanças e decisões](docs/ARQUITETURA_E_MIGRACAO.md).

## Abrir (jeito fácil)

Rode uma vez `./instalar-atalhos.ps1`. Ele cria **Estúdio Ellie** e **Parar Estúdio Ellie** na área de trabalho e faz o Estúdio ligar sozinho com o Windows. Tudo roda em segundo plano, sem janelas de terminal, por `studio/supervisor.py`:

- sobe o servidor e a ponte, e sobe de novo o que cair;
- quando um arquivo do sistema muda (atualização ou correção), espera terminar o que estiver em andamento (resposta da IA, imagem, vídeo) e reinicia só a parte que mudou;
- a página no navegador se recarrega sozinha quando a interface muda, mantendo o texto digitado.

Registro: `studio/dados/logs/supervisor.log`. O Gateway do OpenClaw continua sendo aberto pelo OpenClaw.

## Abrir

Requisitos: Windows, Python 3.12+, Node.js 24+, FFmpeg/FFprobe no PATH, OpenClaw configurado e CLI Dreamina instalada. O ZIP inclui a interface compilada; ao clonar do GitHub, o instalador compila a interface localmente.

1. Extraia esta pasta para um local definitivo. Não copie por cima da pasta antiga; preserve seus arquivos e `.env`.
2. No PowerShell da pasta, rode `./instalar.ps1`. O script instala as dependências do Estúdio e conserva um `.env` existente.
3. Abra o OpenClaw e conecte **sua assinatura**, por OAuth ChatGPT/Codex ou pelo login Claude CLI disponível. O Estúdio não exige chave de API para conversar. [Como conectar](docs/OPENCLAW_ASSINATURAS.md).
   Neste PC, `abrir-openclaw.bat` abre a configuração oficial usando o Node compatível encontrado pelo atalho. A instalação foi verificada; o login precisa ser concluído pelo dono da conta.
4. Rode `python configurar_openclaw.py` para ver a configuração proposta. Depois `python configurar_openclaw.py --executar` registra o agente separado `ellie-studio` pela CLI oficial. Ele não reescreve seu `openclaw.json` nem troca modelos/contas existentes. Reinicie o Gateway.
5. Dê dois cliques em `estudio.bat` ou rode `./iniciar.ps1`. Abra **http://127.0.0.1:8000**.

O chat usa o agente `ellie-studio` e o acesso configurado no OpenClaw. Se a assinatura estiver indisponível, a conversa fica salva e aparece um aviso. Não há fallback de API pago no novo fluxo. O limite da assinatura continua valendo; confirme no OpenClaw que o modelo escolhido usa essa autenticação, sem fallback de API.

## Conversar e produzir

Conte a ideia no chat. A IA pode mostrar:

- uma galeria com os vídeos reais de movimento e suas prévias;
- uma pergunta curta com opções e resposta livre;
- a estrutura de tomadas e prompts para ajustar;
- um cartão de custo consultado na CLI Dreamina;
- controles de texto, faixa, legenda e montagem;
- o vídeo final e os botões de download e copiar legenda.

**Colar imagem (Ctrl+V):** cole, arraste ou use o **+** do chat. A imagem vira um chip com **×** para remover antes de enviar. Se a mensagem disser o que fazer (“cenário”, “roupa”, “Ellie com essa roupa”, “só guardar”), o Estúdio resolve sem chamar a IA do chat e gera com o GPT Image (`gpt-image-2` pelo OpenClaw, login Codex) em segundo plano. Sem texto, aparece um quiz de 1 clique. Pedidos mais elaborados vão para a IA com a imagem anexada, e ela pode pedir a geração. “Gera outra versão” repete o último pedido. **Descartar** move o arquivo para `lixeira/`, sem apagar. As imagens coladas ficam em `anexos/`.

As janelas também podem ser abertas pelos atalhos do chat. A produção pode ser retomada em **Suas produções**; em telas menores, use **Conversas**.

O ZIP de demonstração inclui o exemplo **“Verão → outono · exemplo pronto”**, o vídeo desta conversa e duas fontes locais para remontagem. Funciona para experimentar a edição sem acessar o Dreamina. A fonte de outono deste exemplo já está montada: é reaproveitamento do V7, não um teste que provou gerar toda a transformação numa única tomada. O GitHub contém somente código e documentação; referências e vídeos pessoais ficam no computador e devem ser anexados pela biblioteca após a instalação.

**Claude + GPT no chat:** configure `OPENCLAW_MODELO_CHAT` (ex.: Claude) e `OPENCLAW_MODELO_RESERVA` (ex.: GPT) no `.env`; a reserva assume sozinha se o principal falhar. Cada produção mantém uma sessão contínua: a primeira mensagem leva o contexto completo e as próximas só o que mudou. A resposta aparece enquanto chega, e cada uma mostra modelo, tokens e tempo. [Como configurar](docs/OPENCLAW_ASSINATURAS.md).

**Formato narrado (cena única + voz + legenda karaokê + CTA):** escolha "Narrado com legenda" ao começar um vídeo. Cole uma imagem e escolha "Usar como quadro inicial" (ou peça o quadro ao GPT), cote e gere a cena (~10 s) no Dreamina, gere a voz pelo ElevenLabs (`ELEVENLABS_API_KEY` e `ELEVENLABS_VOZ` no `.env`) ou envie um áudio pronto, e monte localmente, sem créditos. A legenda é sincronizada pelo tempo de cada palavra. Com áudio enviado, usa o texto do roteiro e, se instalado, o Whisper local (`pip install faster-whisper`) para os tempos.

## Assinatura e créditos são separados

Conversar/planejar: conexão local com o OpenClaw e sua assinatura configurada. Gerar vídeo: créditos Dreamina, com cotação atual e botão humano de autorização. Cortar, trocar texto/faixa e remontar: local, sem créditos de geração. Publicação continua manual.

O padrão inicial usa duas tomadas: verão contínuo à direita e transformação à esquerda. O cartão de custo permite testar só a transformação primeiro e cotar o restante depois; não cria oito brutos ou inserts pagos por hábito. O Seedance 2.5 só é oferecido se o catálogo atual da CLI o retornar; seu preço não é deduzido a partir do 2.0 Fast. [Custos e lições do V7](docs/PROCESSO_E_DECISOES.md).

Imagens: use a ferramenta integrada ao chat e anexe o resultado à biblioteca. Esta versão não compra imagens no Dreamina nem presume que uma assinatura libere qualquer gerador de imagem. O agente pode preparar o prompt; a geração de imagem pelo OpenClaw depende de uma ferramenta de imagem realmente disponível e autorizada. O novo fluxo mantém esse passo por anexo quando ela não existe.

## Recuperação e arquivos

O estado novo fica em `studio/dados/producoes.sqlite3`; arquivos em `saida/` e referências nas pastas originais. Faça backup dessas pastas juntas. IDs de envio, recursos, reservas e custos conhecidos ficam salvos antes/depois das operações. Submissão incerta não é reenviada. Uma falha não significa estorno confirmado.

O download de vídeo foi comprovado com `dreamina-canvas resource download` na CLI 1.0.3, apesar da ajuda mencionar imagens. O sistema usa esse comando e valida o arquivo antes de adotá-lo.

## Desenvolvimento e validação

- Backend: `python -m uvicorn studio.server:app --host 127.0.0.1 --port 8000`.
- Ponte: em `studio/mcp`, `npm start` com Node 24+.
- Frontend: em `studio/web`, `npm ci`, `npm run dev` ou `npm run build`.
- Testes: `python -m unittest discover -s tests -v`. As chamadas pagas são simuladas.
- MCP: com a API aberta, em `studio/mcp`, `node test-smoke.mjs`.
- [Validação realizada e limites](docs/VALIDACAO.md).

O pacote não inclui credenciais, `node_modules` ou a autenticação de suas contas. A conexão real com sua assinatura e uma nova geração paga precisam ser verificadas no ambiente configurado; os testes locais não são prova de um novo vídeo gerado.
