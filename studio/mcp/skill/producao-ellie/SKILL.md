---
name: producao-ellie
description: Conduzir a produção de vídeos da Ellie por conversa no Estúdio local, selecionando referências reais, preparando poucas tomadas, consultando o custo Dreamina e montando arquivos existentes. Sem avaliações, métricas ou publicação automática.
---

# Produção da Ellie

Use as ferramentas MCP do Estúdio. Português com Breno; prompts e texto visível em inglês britânico. O formato padrão compara outono à esquerda e verão contínuo à direita. A interface é o chat: escolha os controles que a próxima decisão exige.

1. `estado_estudio` mostra produções e biblioteca. `ver_producao` retoma o estado exato, sem recomeçar.
2. Entenda a referência antes de propor ações. Distingua quadros observados, adaptação e resultado já gerado. Não invente uma reprodução contínua a partir de uma folha de quadros.
3. `criar_producao` abre o contexto. `definir_referencia` associa modelo, vídeo de movimento, estado da roupa ou bruto existente. Só use nomes presentes na biblioteca.
4. `salvar_estrutura` recebe o plano COMPLETO com a versão esperada. Para a forma JSON, consulte `ver_producao`: duracao_final, tomadas, cortes, faixa, legenda. Preserve IDs e referências.
5. Comece com duas tomadas, no máximo três no primeiro lote. Não gere inserts pagos automaticamente. Prefira adaptar cortes e texto localmente.
6. `consultar_custo` prepara rascunhos e consulta a CLI sem executar vídeo. Apresente valor, tomadas e unidade. O usuário aprova pelo botão do Estúdio. Esta skill não tem ferramenta de geração paga.
7. `acompanhar_producao` consulta as submissões originais e baixa resultados existentes. `montar_video` edita localmente sem créditos de geração. Nunca publicar.

Modelo aprovada: `persona/ellie-aprovada.png` na raiz do Estúdio. Estado de roupa novo deriva diretamente dessa modelo, preservando rosto, cabelo escuro longo ondulado e corpo atlético. Imagens são feitas na ferramenta integrada ao chat; se ela não estiver disponível, entregue prompt e peça a imagem anexada. Não gastar Dreamina em imagem.

Dirija ações concretas: apresentar peça, iniciar gesto, cortar para peça vestida, ajustar e mudar apoio. Não travar a pose da foto. Prompt longo não garante anatomia, física ou coreografia. A cotação atual e a especificação da CLI prevalecem sobre preços/modelos memorizados.

Use a faixa de 350/1280 da altura somente para cobrir o rosto em pé. Não aumentar para ocultar rosto inclinado e perder o outfit. Serifas, fundo creme, texto marrom e destaque amarelo; pergunta de preferência é permitida.

Legenda curta em inglês e poucos hashtags. Sem crédito automático de referência e sem frase de IA na legenda: o usuário indicou que marcará na plataforma. Não transformar essa escolha em afirmação de que a rotulagem é desnecessária.

Erros: conservar arquivos, custos e IDs. Uma falha não prova estorno. Não reenviar submissão incerta. Uma aprovação cobre o lote concreto e o teto, não testes futuros. Nunca logar tokens nem cadastrar fallback de API paga.
