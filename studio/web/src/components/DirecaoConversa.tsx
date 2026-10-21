import type { Bloco, Producao } from '@/types/processo'

export default function DirecaoConversa({ producao: p, responder, abrir }: {
  producao: Producao; responder: (s: string) => void; abrir: (b: Bloco) => void
}) {
  const d = p.direcao
  if (!d?.ideia) return <>
    <p>Vamos resumir a ideia, a mudança que acontece no vídeo e a linguagem visual antes de produzir.</p>
    <button className="secondary-button" onClick={() => responder('Organize a direção criativa desta produção com base no que já decidimos. Salve em direcao e mostre uma proposta concreta, sem gerar mídia.')}>Organizar a direção atual</button>
  </>
  return <div className="creative-direction">
    <p className="direction-idea">{d.ideia}</p>
    {d.objetivo && <p className="direction-purpose">{d.objetivo}</p>}
    <dl>{([['abertura', 'Começa com'], ['desenvolvimento', 'O que muda'], ['fecho', 'Termina com'], ['visual', 'Linguagem visual'], ['audio', 'Áudio']] as const).map(([k, label]) =>
      d[k] && <div key={k}><dt>{label}</dt><dd>{d[k]}</dd></div>)}</dl>
    <p className="field-note">Este é o resumo da direção atual. Você pode mudar qualquer parte pelo chat.</p>
    <button className="secondary-button" onClick={() => p.tomadas.length ? abrir({ tipo: 'plano', titulo: 'Sequência de cenas' })
      : responder('Desenvolva a direção atual em uma sequência de cenas. Para cada cena mostre o que acontece e por que ela existe. Preserve o que já decidimos. Só planejamento, sem gerar mídia.')}>{p.tomadas.length ? 'Ver sequência de cenas' : 'Desenvolver as cenas'}</button>
  </div>
}
