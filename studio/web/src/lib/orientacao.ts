import type { Bloco, Producao } from '../types/processo.ts'

export type Orientacao = { titulo: string; detalhe: string; botao?: string; bloco?: Bloco }

export function proximoPasso(p: Producao): Orientacao {
  const cenas = p.tomadas
  const trabalhos = p.trabalhos ?? []
  if (p.resultado?.pendencias?.length) return { titulo: 'Vídeo com pendências', detalhe: p.resultado.pendencias.join(' '), botao: 'Ver vídeo', bloco: { tipo: 'resultado' } }
  if (p.resultado) return { titulo: 'Vídeo disponível', detalhe: 'Assista ao resultado e confira antes de baixar.', botao: 'Ver vídeo', bloco: { tipo: 'resultado' } }
  const executando = trabalhos.find(t => t.faixa === 'producao')
  if (executando) return { titulo: executando.rotulo, detalhe: 'Esta etapa está em andamento. Você pode continuar conversando enquanto ela termina.' }
  if (!cenas.length) return p.direcao?.ideia
    ? { titulo: 'Desenvolver a sequência', detalhe: 'A direção está resumida. Agora vamos mostrar o que acontece em cada parte do vídeo.', botao: 'Ver direção', bloco: { tipo: 'direcao', titulo: 'Direção do vídeo' } }
    : { titulo: 'Desenvolver a ideia', detalhe: 'Vamos definir a mudança que o vídeo mostra, do começo ao fim. Você pode conversar livremente.' }
  // O áudio muda o plano inteiro (tempos, prompt de vídeo, montagem): decide-se logo depois das cenas
  if (p.fluxo_dirigido && p.ficha && p.ficha.audio === 'indefinido' && !p.narracao?.texto)
    return { titulo: 'Decidir o áudio', detalhe: 'Narração, som original das tomadas ou silêncio. Isso define os tempos e a montagem.', botao: 'Abrir caderno', bloco: { tipo: 'caderno', titulo: 'Caderno da produção' } }
  if (p.narracao?.texto && !p.narracao.audio) return { titulo: 'Preparar a narração', detalhe: 'Com a sequência definida, a voz vai informar o ritmo dos cortes.', botao: 'Abrir narração', bloco: { tipo: 'narracao' } }
  const faltam = cenas.filter(s => !s.arquivo && !s.imagens.length && !(s.tipo !== 'imagem' && p.master && s.ellie !== false))
  if (faltam.length) return trabalhos.some(t => t.faixa === 'midia')
    ? { titulo: 'Preparando os quadros', detalhe: 'Você pode continuar conversando. Assim que a imagem ficar pronta, ela aparecerá na cena.' }
    : { titulo: 'Completar os quadros', detalhe: `Falta imagem em ${faltam.length} cena(s). Peça no chat ou escolha uma referência.`, botao: 'Escolher quadro', bloco: { tipo: 'galeria', pasta: 'quadros', papel: 'estado', tomada: faltam[0].id } }
  // Quadro só vale depois de conferido contra as exigências da cena (antes de qualquer gasto)
  const situacao = (id: string) => p.situacoes?.[id]
  const reprovado = cenas.find(s => !s.arquivo && ['problema', 'indeterminada'].includes(situacao(s.id)?.quadro ?? ''))
  if (reprovado) return { titulo: `Resolver o quadro de “${reprovado.titulo}”`, detalhe: p.conferencias?.[reprovado.id]?.resumo || 'O quadro não passou na conferência.', botao: 'Ver storyboard', bloco: { tipo: 'plano', titulo: 'Storyboard' } }
  if (cenas.some(s => !s.arquivo && situacao(s.id)?.quadro === 'pendente'))
    return trabalhos.some(t => t.faixa === 'midia')
      ? { titulo: 'Conferindo os quadros', detalhe: 'Cada quadro é comparado com o que a cena exige. Pode seguir conversando.' }
      : { titulo: 'Conferir os quadros', detalhe: 'Há quadros ainda não conferidos.', botao: 'Ver storyboard', bloco: { tipo: 'plano', titulo: 'Storyboard' } }
  const tomadaRuim = cenas.find(s => s.arquivo && situacao(s.id)?.video === 'problema')
  if (tomadaRuim) return { titulo: `Revisar a tomada “${tomadaRuim.titulo}”`, detalhe: p.conferencias_video?.[tomadaRuim.id]?.resumo || 'A tomada não passou na conferência.', botao: 'Ver tomadas', bloco: { tipo: 'custo', titulo: 'Tomadas' } }
  const enviadas = cenas.filter(s => s.submit_id && !s.arquivo)
  if (enviadas.length) return { titulo: 'Acompanhar as tomadas', detalhe: 'Confira o pedido existente e recupere o resultado sem enviar outra geração.', botao: 'Ver tomadas', bloco: { tipo: 'custo' } }
  const pendentes = cenas.filter(s => s.tipo !== 'imagem' && !s.arquivo)
  if (pendentes.length && p.fluxo_dirigido && p.revisao_atual && !p.revisao_atual.atual)
    return { titulo: 'Revisar o storyboard', detalhe: 'Veja a sequência inteira com os quadros conferidos antes de gastar créditos.', botao: 'Ver storyboard', bloco: { tipo: 'plano', titulo: 'Storyboard' } }
  if (pendentes.length) return { titulo: p.cotacao && !p.cotacao.executada ? 'Revisar custo e autorizar' : 'Consultar o custo', detalhe: 'O quadro está pronto. A geração só começa após sua autorização no cartão de custo.', botao: 'Ver custo e geração', bloco: { tipo: 'custo', titulo: 'Custo e geração' } }
  return { titulo: 'Montar o vídeo', detalhe: 'As cenas estão disponíveis. A montagem local não usa créditos de vídeo.', botao: 'Abrir montagem', bloco: { tipo: 'edicao', titulo: 'Montagem local' } }
}
