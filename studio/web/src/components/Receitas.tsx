import { useState } from 'react'
import { api } from '@/lib/api'
import type { EstadoEstudio, Receitas as TipoReceitas } from '@/types'

interface Props {
  receitas: TipoReceitas
  estado: EstadoEstudio
  onCarregar: (estado: EstadoEstudio) => void
  onMudou: () => Promise<void>
}

export default function Receitas({ receitas, estado, onCarregar, onMudou }: Props) {
  const [nome, setNome] = useState('')
  const nomes = Object.keys(receitas)

  async function salvar() {
    const limpo = nome.trim()
    if (!limpo) return
    // A receita guarda o setup (fotos, peça, movimento, cena, modelo), sem o prompt editado à mão
    await api.salvarReceita(limpo, { ...estado, promptManual: null, rascunhoId: '' })
    setNome('')
    await onMudou()
  }

  async function apagar(alvo: string) {
    if (!window.confirm(`Apagar a receita "${alvo}"?`)) return
    await api.apagarReceita(alvo)
    await onMudou()
  }

  return (
    <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3 text-sm">
      <div className="font-semibold text-slate-800">Receitas</div>
      <p className="text-xs text-slate-500">Salve o setup que funcionou e repita em outros vídeos.</p>
      <div className="flex gap-2">
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="nome da receita"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 outline-none focus:border-rose-500"
        />
        <button
          type="button"
          onClick={salvar}
          disabled={!nome.trim()}
          className="rounded-lg bg-slate-900 px-3 py-1.5 text-white disabled:bg-slate-300"
        >
          Salvar
        </button>
      </div>
      {nomes.length > 0 && (
        <ul className="space-y-1">
          {nomes.map((n) => (
            <li key={n} className="flex items-center justify-between gap-2">
              <button type="button" onClick={() => onCarregar({ ...receitas[n], promptManual: null })} className="truncate text-left text-rose-600 underline">
                {n}
              </button>
              <button type="button" onClick={() => apagar(n)} className="text-slate-400 hover:text-red-600" aria-label={`Apagar ${n}`}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
