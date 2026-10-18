import { useCallback, useEffect, useState } from 'react'
import NovoVideo from '@/components/NovoVideo'
import { api } from '@/lib/api'
import type { Assets, Etapa, Projeto } from '@/types'

interface Props {
  assets: Assets
  recarregarAssets: () => Promise<void>
  onAbrir: (id: string) => void
}

const COLUNAS: { etapas: Etapa[]; titulo: string; dica: string }[] = [
  { etapas: ['estrategia', 'midias'], titulo: 'Estratégia e mídias', dica: 'Definir o gancho e montar o plano' },
  { etapas: ['gerar', 'gerando'], titulo: 'Gerar', dica: 'Teste barato e versão para postar' },
  { etapas: ['revisar'], titulo: 'Revisar', dica: 'Escolher o melhor vídeo, texto e legenda' },
  { etapas: ['postar'], titulo: 'Pronto para postar', dica: 'Baixar, colar a legenda e postar' },
  { etapas: ['postado', 'medido'], titulo: 'Postado', dica: 'Colocar os números em 48h' },
]
const NOME_PILAR: Record<string, string> = { outfit_clima: 'Outfit e clima', pov_london: 'POV London', lugar: 'Lugar' }

// Tela inicial: criar um vídeo (movimento + roupa + cenário) e acompanhar os vídeos por etapa
export default function Projetos({ assets, recarregarAssets, onAbrir }: Props) {
  const [projetos, setProjetos] = useState<Projeto[]>([])
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      setProjetos(await api.projetos())
    } catch {
      setErro('Não consegui falar com o servidor do Estúdio.')
    }
  }, [])

  useEffect(() => {
    void carregar()
    const timer = setInterval(() => void carregar(), 15000)
    return () => clearInterval(timer)
  }, [carregar])


  return (
    <div className="space-y-6">
      <NovoVideo assets={assets} recarregarAssets={recarregarAssets} onCriado={onAbrir} />

      <h2 className="pt-4 text-lg font-semibold text-slate-900">Seus vídeos</h2>
      {erro && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{erro}</p>}

      <div className="grid gap-4 overflow-x-auto pb-2 lg:grid-cols-5">
        {COLUNAS.map((col) => {
          const itens = projetos.filter((p) => col.etapas.includes(p.etapa))
          return (
            <section key={col.titulo} className="min-w-[220px] space-y-3 rounded-2xl bg-slate-100/70 p-3">
              <header>
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-800">{col.titulo}</h3>
                  <span className="rounded-full bg-white px-2 text-xs text-slate-600">{itens.length}</span>
                </div>
                <p className="text-[11px] text-slate-500">{col.dica}</p>
              </header>
              {itens.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onAbrir(p.id)}
                  className="w-full space-y-1.5 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-rose-400 hover:shadow-sm"
                >
                  {p.capa && <video src={p.capa} muted preload="metadata" className="aspect-[9/16] max-h-40 w-full rounded-lg bg-black object-cover" />}
                  <div className="text-sm font-semibold text-slate-900">{p.titulo || 'Sem título'}</div>
                  {p.gancho_en && <div className="line-clamp-2 text-xs italic text-slate-600">"{p.gancho_en}"</div>}
                  <div className="flex flex-wrap gap-1 text-[11px]">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{NOME_PILAR[p.pilar] ?? p.pilar}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 ${p.etapa === 'gerando' ? 'bg-amber-100 text-amber-800' : 'bg-rose-50 text-rose-700'}`}
                    >
                      {p.etapa === 'gerando' ? '⏳ ' : ''}
                      {p.nome_etapa}
                    </span>
                  </div>
                </button>
              ))}
            </section>
          )
        })}
      </div>
    </div>
  )
}
