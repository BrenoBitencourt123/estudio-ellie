# Validação desta versão

18/10/2026. Nenhuma nova geração paga e nenhuma publicação foram feitas para implementar/testar o sistema.

## Verificado

- Testes Python com chamadas Dreamina simuladas: plano inicial pequeno, orçamento inferior ao preço, alteração de preço/canvas, segundo clique, perda de conexão após envio, persistência após reiniciar, reserva preservada sem presumir estorno, hash de imagem alterada, plano de janela antiga, edição local que conserva a geração, bloqueio de mudança de tomada enviada, caminhos inválidos, JSON de quiz, filtragem de nomes inexistentes, ausência de fallback API no chat, concorrência, cotação sem geração e teste de uma única tomada.
- API FastAPI importa e inicia sem `.env`/chave Atlas. Ponte Node inicia com Node 24 e informa corretamente que o Gateway não está configurado.
- Transporte MCP real em stdio com oito ferramentas; consulta à biblioteca/produções do servidor local concluída. Nenhuma ferramenta de geração paga exposta ao agente.
- TypeScript da interface verificado e aplicação compilada pelo Vite.
- Navegador: tela inicial, galeria com vídeos reais, conversa salva, editor contextual e salvar. Prévia dos vídeos retornou `readyState=4` e dimensões reais. Montagem local acionada e concluída com o exemplo.
- Remontagem real por FFmpeg: 720 × 1280, 30 fps, 270 quadros, 9 s e sem áudio. Usa os arquivos existentes, não simula vídeo gerado.
- CLI Dreamina autenticada consultada somente para catálogo e fatos/cotação de recurso já existente. `seedance_2.5` encontrado. Nenhum novo rascunho/canvas foi gerado para cotar o 2.5 nesta entrega.

## Ainda depende do ambiente do usuário

- Registrar/conectar o agente `ellie-studio` no OpenClaw com a assinatura correta. Não havia configuração Gateway neste ambiente; conversa real pela assinatura não foi concluída aqui.
- Disponibilidade, autenticação, modelo e limite da assinatura. Não foram copiados tokens nem alteradas contas.
- Uma nova geração Dreamina com os parâmetros do novo fluxo. Os testes de envio/erro/retry são simulados e não comprovam a qualidade criativa de outro vídeo.
- Ferramenta de imagem integrada ao host OpenClaw. Sem ela, o caminho implementado é prompt + anexar o resultado do chat. Não há fallback para comprar imagem no Dreamina.

A entrega contém um exemplo local pronto para exercitar referências, edição e download antes de configurar as contas. Não tratar esse exemplo como demonstração de que o plano novo de duas tomadas já foi gerado com sucesso.
