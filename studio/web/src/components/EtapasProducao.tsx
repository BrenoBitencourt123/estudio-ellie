import Cronometro from '@/components/Cronometro'
import type { Producao, Trabalho } from '@/types/processo'

// Painel de etapas: o que já está pronto, o que está sendo feito agora e o que ainda falta.
// Tudo é derivado do estado real da produção — nada aqui é só decoração.
type Estado = 'feito' | 'agora' | 'espera' | 'atencao'
type Etapa = { chave: string; nome: string; estado: Estado; detalhe: string; desde?: number }

const emCurso = (trabalhos: Trabalho[], faixa: Trabalho['faixa'], ...termos: string[]) =>
  trabalhos.find(t => t.faixa === faixa && (!termos.length || termos.some(x => t.rotulo.toLowerCase().includes(x))))

export function etapasDa(p: Producao): Etapa[] {
  const tr = p.trabalhos ?? []
  const tomadas = p.tomadas ?? []
  const prontas = tomadas.filter(s => s.arquivo).length
  const falhas = tomadas.filter(s => ['failed', 'canceled', 'cancelled'].includes(s.estado ?? '')).length
  const enviadas = tomadas.filter(s => s.submit_id).length
  const comImagem = tomadas.filter(s => s.imagens.length > 0 || Boolean(p.master && s.ellie !== false)).length
  const n = p.narracao
  const lista: Etapa[] = []
  // Quando a faixa está rodando, o rótulo vem do próprio servidor — é o que ele está fazendo de verdade
  const passo = (chave: string, nome: string, estado: Estado, detalhe: string, t?: Trabalho) => lista.push({
    chave, nome, estado: t ? 'agora' : estado, detalhe: t ? t.rotulo : detalhe,
    desde: t ? Date.parse(t.iniciado) : undefined,
  })

  passo('ideia', 'Ideia e direção', p.mensagens.length ? 'feito' : 'espera',
    p.mensagens.length ? `${p.mensagens.length} mensagens na conversa` : 'me conte o que quer fazer',
    emCurso(tr, 'conversa'))

  const temRef = !!p.referencia || tomadas.some(s => s.imagens.length > 0)
  passo('referencias', 'Referências', temRef ? 'feito' : 'espera',
    temRef ? 'escolhidas' : 'nenhuma ainda', emCurso(tr, 'midia', 'pinterest'))

  passo('imagens', 'Quadros das cenas', tomadas.length > 0 && comImagem === tomadas.length ? 'feito' : 'espera',
    tomadas.length ? `${comImagem} de ${tomadas.length} com imagem` : 'o plano ainda não tem cenas',
    emCurso(tr, 'midia', 'gerando'))

  if (n?.texto) passo('voz', 'Narração', n.audio ? 'feito' : 'espera',
    n.audio ? `${n.palavras?.length ?? 0} palavras sincronizadas` : 'texto escrito, falta gerar a voz',
    emCurso(tr, 'voz'))

  passo('custo', 'Custo aprovado', p.cotacao ? 'feito' : 'espera',
    p.cotacao ? `${p.cotacao.total.toLocaleString('pt-BR')} créditos${p.cotacao.executada ? ' · já usado' : ' · esperando seu OK'}`
      : 'ainda não consultado', emCurso(tr, 'producao', 'custo'))

  passo('tomadas', 'Tomadas no Dreamina',
    falhas ? 'atencao' : tomadas.length > 0 && prontas === tomadas.length ? 'feito' : 'espera',
    !tomadas.length ? 'sem cenas no plano' : falhas ? `${falhas} não concluiu` :
      `${prontas} de ${tomadas.length} prontas${enviadas > prontas ? ' · gerando lá fora' : ''}`,
    emCurso(tr, 'producao', 'tomadas'))

  passo('montagem', 'Vídeo montado', p.resultado ? 'feito' : 'espera',
    p.resultado ? `${Math.round(p.resultado.duracao)}s · pronto para baixar` : 'falta montar',
    emCurso(tr, 'producao', 'montando'))
  return lista
}

export default function EtapasProducao({ producao }: { producao: Producao }) {
  const lista = etapasDa(producao)
  const feitas = lista.filter(e => e.estado === 'feito').length
  return <section className="steps-panel" aria-label="Etapas da produção">
    <div className="steps-head"><span className="eyebrow">ETAPAS</span><small>{feitas} de {lista.length}</small></div>
    <ol className="steps-list">{lista.map(e =>
      <li key={e.chave} className={`step step-${e.estado}`} aria-current={e.estado === 'agora' ? 'step' : undefined}>
        <span className="step-dot" aria-hidden="true">{e.estado === 'feito' ? '✓' : e.estado === 'atencao' ? '!' : ''}</span>
        <div><strong>{e.nome}</strong>
          <small>{e.detalhe}{e.desde !== undefined && <> · <Cronometro desde={e.desde} /></>}</small></div>
      </li>)}
    </ol>
  </section>
}
