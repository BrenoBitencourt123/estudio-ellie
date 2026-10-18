import { useEffect, useState } from 'react'
import PassoRevisao from '@/components/PassoRevisao'
import Secao from '@/components/Secao'
import { api } from '@/lib/api'
import { ehKling, formatarBrl, formatarUsd, OPCOES_GERAR, paraPedido } from '@/lib/estudioUtil'
import type { Estimativa, PropsPasso } from '@/types'

interface Props extends PropsPasso {
  estimativa: Estimativa | null
  promptAuto: string
  erro: string
  problema: string | null
  onGerado: () => void
}

// Último passo: dois botões claros (testar barato e versão para postar), avisos do autoestudo e ajustes avançados escondidos
export default function PassoFinal(props: Props) {
  const { estado, mudar, config, estimativa, problema, onGerado } = props
  const motor = ehKling(estado.modelo) ? 'kling' : 'seedance'
  const opcoes = OPCOES_GERAR[motor]
  const [custos, setCustos] = useState<Record<string, number>>({})
  const [enviando, setEnviando] = useState('')
  const [erro, setErro] = useState('')

  // Custo de cada botão (mesmo vídeo, modelo diferente)
  const chave = JSON.stringify({ ...estado, modelo: '', resolucao: '', promptManual: null, nome: '' })
  useEffect(() => {
    let cancelado = false
    void Promise.all(
      opcoes.map((o) =>
        api
          .estimar(paraPedido({ ...estado, modelo: o.modelo, resolucao: o.resolucao }))
          .then((e) => [o.id, e.custo_usd] as const)
          .catch(() => [o.id, NaN] as const),
      ),
    ).then((pares) => {
      if (!cancelado) setCustos(Object.fromEntries(pares))
    })
    return () => {
      cancelado = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave, motor])

  async function gerar(modelo: string, resolucao: '480p' | '720p', id: string) {
    setErro('')
    setEnviando(id)
    try {
      mudar({ modelo, resolucao })
      await api.gerar(paraPedido({ ...estado, modelo, resolucao }))
      onGerado()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao gerar')
    } finally {
      setEnviando('')
    }
  }

  const restante = config.teto_usd - config.gasto_semana_usd

  return (
    <Secao titulo="Gerar" descricao="Teste barato primeiro quando a ideia for nova. Quando a cena já funcionou antes, vá direto para a versão de postar.">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-medium text-slate-800">Duração</span>
        <button
          type="button"
          onClick={() => mudar({ duracao: Math.max(4, estado.duracao - 1) })}
          className="h-8 w-8 rounded-lg border border-slate-300 text-lg leading-none"
          aria-label="Diminuir duração"
        >
          −
        </button>
        <span className="w-10 text-center text-base font-semibold">{estado.duracao}s</span>
        <button
          type="button"
          onClick={() => mudar({ duracao: Math.min(15, estado.duracao + 1) })}
          className="h-8 w-8 rounded-lg border border-slate-300 text-lg leading-none"
          aria-label="Aumentar duração"
        >
          +
        </button>
        <span className={estado.duracao >= 7 && estado.duracao <= 9 ? 'text-emerald-700' : 'text-amber-700'}>
          {estado.duracao >= 7 && estado.duracao <= 9 ? 'No ponto ideal (7 a 9s)' : 'O ideal para a Ellie é 7 a 9s'}
        </span>
      </div>

      {estimativa?.dica && <p className="rounded-lg bg-sky-50 p-3 text-sm text-sky-800">Autoestudo: {estimativa.dica}</p>}
      {estimativa && estimativa.repetidos.length > 0 && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Você já gerou exatamente isso: {estimativa.repetidos.map((r) => `${r.arquivo}${r.nota === 'bom' ? ' 👍' : r.nota === 'ruim' ? ' 👎' : ''}`).join(', ')}.
          Gere de novo só se quiser outra tentativa; para economizar, mude a cena, o trecho ou as referências.
        </p>
      )}
      {problema && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{problema}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {opcoes.map((o, i) => {
          const custo = custos[o.id]
          return (
            <div key={o.id} className={`rounded-2xl border-2 p-4 ${i === 1 ? 'border-rose-300' : 'border-slate-200'}`}>
              <div className="font-semibold text-slate-900">{o.titulo}</div>
              <div className="text-xs text-slate-500">
                {o.modelo}
                {motor === 'seedance' ? ` · ${o.resolucao}` : ''}
              </div>
              <p className="mt-1 text-sm text-slate-600">{o.dica}</p>
              <button
                type="button"
                onClick={() => void gerar(o.modelo, o.resolucao, o.id)}
                disabled={Boolean(problema) || Boolean(enviando) || (Number.isFinite(custo) && custo > restante)}
                className={`mt-3 w-full rounded-lg px-4 py-2.5 font-semibold transition disabled:cursor-not-allowed disabled:bg-slate-300 ${
                  i === 1 ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-slate-900 text-white hover:bg-slate-700'
                }`}
              >
                {enviando === o.id
                  ? 'Enviando...'
                  : `Gerar · ${Number.isFinite(custo) ? `${formatarUsd(custo)} (${formatarBrl(custo * config.cotacao)})` : '...'}`}
              </button>
              {Number.isFinite(custo) && custo > restante && <p className="mt-1 text-xs text-red-600">Passa do que resta no teto da semana.</p>}
            </div>
          )
        })}
      </div>
      {erro && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{erro}</p>}
      <p className="text-xs text-slate-500">Resta no teto da semana: {formatarUsd(Math.max(0, restante))}. O vídeo aparece na Fila em 1 a 4 minutos.</p>

      <details className="rounded-xl border border-slate-200 p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">Ajustes avançados (modelo, resolução, prompt final)</summary>
        <div className="mt-4">
          <PassoRevisao {...props} />
        </div>
      </details>
    </Secao>
  )
}
