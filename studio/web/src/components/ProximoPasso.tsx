import { proximoPasso } from '@/lib/orientacao'
import type { Bloco, Producao } from '@/types/processo'

export default function ProximoPasso({ producao, abrir }: { producao: Producao; abrir: (b: Bloco) => void }) {
  const passo = proximoPasso(producao)
  return <section className="production-next" aria-label="Próximo passo">
    <div><span className="eyebrow">PRÓXIMO PASSO</span><strong>{passo.titulo}</strong><p>{passo.detalhe}</p></div>
    {passo.bloco && <button className="secondary-button" onClick={() => abrir(passo.bloco!)}>{passo.botao}</button>}
  </section>
}
