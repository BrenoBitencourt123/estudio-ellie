# Processo Ellie: referências, decisões e custo

18/10/2026. Este guia é a direção do produto atual. Conversa e preferências mais recentes prevalecem sobre regras antigas do sistema recebido.

## Fontes e aplicação

| Fonte | O que aproveitamos | Limite |
|---|---|---|
| [3 Steps to Master AI Realism in 2026](https://www.youtube.com/watch?v=mJUULemmPV8) | Preparar personagem/estados, dirigir ação, física, olhar e continuidade; testar economicamente | Não comprova que um prompt consiga preservar tudo na nossa ferramenta |
| [Zombie dog prompts, Shot 4](https://higgsfield.ai/@kaye_creatives/blogs/zombie-dog-prompts#shot-4-putting-the) | Sequência observável de ações, interação com objetos, expressão e corte | Cenário/história do filme são outra criação; não copiar como requisito de moda |
| [If I Started Instagram From 0](https://www.youtube.com/watch?v=k-FNGqaindk) | Estudar o mecanismo da referência antes de adaptar | Não criar promessa de alcance. O usuário retirou métricas/avaliações do produto |
| Vídeo de @sara_hymy enviado pelo usuário | Verão permanente à direita, peças/gestos e transformação à esquerda; cortes curtos | Coreografia precisa ser analisada; aceitar vídeo como referência não prova transferência exata |
| Teste local V6/V7 | Imagens/identidade escolhidas, movimentos, defeitos observados, composição e download pela CLI | Não é experimento controlado de superioridade entre modelos |

## Identidade e roupa

A foto `persona/ellie-aprovada.png` é a identidade ativa. Rosto específico, cabelo muito longo, escuro e ondulado, cintura definida, quadril cheio e coxas musculosas. Não substituir por uma modelo genérica. Novo estado deve derivar diretamente dela.

O look de verão atual é camisa azul-marinho com colo aberto/mangas dobradas, saia marfim com costuras e bolsos, cinto/bolsa conhaque e tênis branco/bege. O outono fecha a gola, baixa mangas e acrescenta colete creme, meia-calça marrom e botas marrons. A combinação vem da referência e do feedback, sem alegar que toda peça futura está automaticamente aprovada.

## Direção de movimento

Reproduzir primeiro a lógica da referência: apresentar a peça → iniciar o vestir → omitir no corte → ajustar → próxima peça. Olhar vai à peça e volta à lente; pés e joelhos mudam apoio; cabelo, tecido e bolsa respondem ao movimento. Preservar a pessoa não significa congelar a pose.

A transformação é uma montagem; o verão permanece contínuo. Duas metades exibidas simultaneamente têm fontes diferentes. Cabeça, mãos, bolsas e sapatos precisam caber no recorte de cada painel. Evitar inventar laço, óculos ou outras peças só porque aparecem no vídeo de movimento.

## Produção econômica

O V7 pediu oito gerações bem-sucedidas, totalizando 37 segundos brutos solicitados: 9 s de verão + sete tomadas de 4 s. Elas foram selecionadas para um vídeo final de 9 s, com as duas metades simultâneas. O verão de 9 s foi usado inteiro; os demais brutos foram recortados.

| Lançamento histórico V7 | Créditos |
|---|---:|
| Débitos iniciais | 1.960 |
| Seis estornos confirmados | −1.640 |
| Líquido dos dois detalhes | 320 |
| Seis tomadas da retomada aprovada | 1.560 |
| Total líquido registrado | **1.880** |

Downloads, cortes e várias mudanças de tipografia não acrescentaram créditos. O orçamento foi aprovado, mas o planejamento foi caro para um piloto: muitos brutos e detalhes pagos antes de validar a movimentação. Isso é um erro de processo do assistente, não um requisito do formato.

O novo padrão planeja duas tomadas de 9 s (18 s brutos), em vez de oito. O cartão de orçamento permite testar só a transformação primeiro. Reaproveitar um verão existente pode eliminar mais uma geração. A redução de segundos não é automaticamente a mesma redução percentual de custo: contam modelo, resolução, duração mínima e referências de vídeo.

Seedance 2.5 foi localizado no catálogo da CLI em 18/10/2026: ID `seedance_2.5`, com modo multimodal e durações consultadas de 4–30 s. **Não fizemos uma cotação equivalente do novo plano no 2.5**, então “caberia em 1.900” permanece uma possibilidade, não um valor confirmado. Não converter créditos para reais sem saber o plano/preço efetivamente pago na conta.

## O que os arquivos mostraram

- O verão novo mudou mãos, apoio e olhar; não manteve uma única pose.
- A camisa voltou a abrir/enrolar mangas depois do início. A edição usou o trecho inicial.
- O colete já vestido foi ajustado em uma nova tomada; a apresentação veio do V6, conforme a retomada aprovada.
- A meia trouxe uma faixa escura de continuidade imperfeita; as botas foram apresentadas sem o tênis solicitado.
- O detalhe da bota começou puxando a meia da coxa; só o fim inferior foi aproveitado.
- Bolsa/final incluiu apresentação, abaixar, cabelo e mudança de apoio. Pequenos saltos entre tomadas permaneceram.

O usuário disse “Ficou ótimo” sobre o vídeo e pediu melhorar a tipografia. Isso registra sua aprovação estética do conteúdo, sem transformar os defeitos conhecidos em inexistentes. Nenhum desempenho de publicação foi verificado.

## Gráfico e legenda atuais

Faixa creme de 350 px em 720 × 1280: cobre o rosto em pé, deixa o tronco visível e pode revelar o rosto quando ela se inclina. A variante de 540 px foi rejeitada porque escondia o look. Serifas, marrom escuro, itálico e destaque amarelo discreto.

Texto atual:
```
ONE OUTFIT / TWO SEASONS
Summer to
autumn.
Which would you wear — summer or autumn?
AUTUMN                         SUMMER
```

Legenda atual:
```
One outfit, two seasons ☀️🍂 Summer or autumn — which would you wear?

#OutfitInspo #AutumnOutfit #SummerStyle #SeasonalStyle
```

O usuário pediu não inserir crédito da referência nem frase de IA na legenda, pois fará a marcação de IA na plataforma. Isso não autoriza publicação automática nem afirma que a marcação é dispensável. Os arquivos e as escolhas ficam no registro da produção; o produto não exige notas, avaliações ou métricas.

## Evidência técnica importante

A CLI 1.0.3 descreve `resource download` como download de imagem, mas o teste real baixou seis vídeos com sucesso. A conclusão anterior de que a CLI não baixava vídeo estava errada. Verificar a capacidade real documentada antes de abandonar o caminho da CLI; não inventar comandos/endpoints. Nunca gerar outra vez para recuperar arquivo existente.

Movimentos recortados em 288 × 1024 foram recusados; preparar margens para 576 × 1024 corrigiu esse problema sem deformar os gestos. Conservar fonte, intervalo e hash do arquivo preparado. Compatibilidade técnica não comprova fidelidade criativa.
