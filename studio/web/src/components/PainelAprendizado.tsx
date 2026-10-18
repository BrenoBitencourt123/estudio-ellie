import type { ReactNode } from 'react'
import { dePedido, formatarUsd } from '@/lib/estudioUtil'
import type { Aprendizado, EstadoEstudio } from '@/types'

interface Props {
  dados: Aprendizado | null
  onReusar: (estado: EstadoEstudio) => void
}

const NOME_PILAR: Record<string, string> = { outfit_clima: 'Outfit e clima', pov_london: 'POV London', lugar: 'Lugar' }
// Largura da barra de pilar em passos de 10% (classes escritas por extenso para o Tailwind encontrar)
const LARGURAS = ['w-0', 'w-[10%]', 'w-[20%]', 'w-[30%]', 'w-[40%]', 'w-1/2', 'w-[60%]', 'w-[70%]', 'w-[80%]', 'w-[90%]', 'w-full']
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)
const din = (v: number | null) => (v === null ? '—' : formatarUsd(v))

function Bloco({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="mb-3 text-lg font-semibold text-slate-900">{titulo}</h2>
      {children}
    </section>
  )
}

// O que o estúdio aprendeu com as avaliações e os números do TikTok
export default function PainelAprendizado({ dados, onReusar }: Props) {
  if (!dados) return <p className="text-slate-500">Carregando...</p>

  return (
    <div className="space-y-6">
      <Bloco titulo="O que fazer agora">
        {dados.recomendacoes.length === 0 ? (
          <p className="text-sm text-slate-500">Ainda sem dados. Gere e avalie alguns vídeos.</p>
        ) : (
          <ul className="space-y-2 text-sm text-slate-800">
            {dados.recomendacoes.map((r) => (
              <li key={r} className="rounded-lg bg-sky-50 p-3">
                {r}
              </li>
            ))}
          </ul>
        )}
      </Bloco>

      <Bloco titulo="Qual modelo vale a pena (custo por vídeo aprovado)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Caminho</th>
                <th className="py-2 pr-3 font-medium">Modelo</th>
                <th className="py-2 pr-3 font-medium">Gerados</th>
                <th className="py-2 pr-3 font-medium">Falhas</th>
                <th className="py-2 pr-3 font-medium">👍 / 👎</th>
                <th className="py-2 pr-3 font-medium">Aprovação</th>
                <th className="py-2 pr-3 font-medium">Custo médio</th>
                <th className="py-2 font-medium">Por aprovado</th>
              </tr>
            </thead>
            <tbody>
              {dados.configs.map((c) => (
                <tr key={c.modo + c.modelo} className="border-t border-slate-100">
                  <td className="py-2 pr-3 text-slate-700">{dados.modos[c.modo] ?? c.modo}</td>
                  <td className="py-2 pr-3 font-medium text-slate-900">{c.modelo}</td>
                  <td className="py-2 pr-3">{c.gerados}</td>
                  <td className="py-2 pr-3">{c.falhas}</td>
                  <td className="py-2 pr-3">
                    {c.bons} / {c.ruins}
                  </td>
                  <td className="py-2 pr-3">{pct(c.aprovacao)}</td>
                  <td className="py-2 pr-3">{din(c.custo_medio)}</td>
                  <td className="py-2 font-semibold">{din(c.custo_por_aprovado)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          "Por aprovado" soma tudo o que foi gasto no modelo e divide pelos vídeos com 👍. É o número que mostra onde o dinheiro rende.
        </p>
      </Bloco>

      <div className="grid gap-6 lg:grid-cols-2">
        <Bloco titulo="Problemas que se repetem">
          {dados.problemas.length === 0 ? (
            <p className="text-sm text-slate-500">Nenhum marcado ainda. Marque o que deu errado nos vídeos com 👎.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {dados.problemas.map((p) => (
                <li key={p.problema}>
                  <span className="font-medium text-slate-900">
                    {p.nome} ({p.vezes}x):
                  </span>{' '}
                  <span className="text-slate-700">{p.como_corrigir}</span>
                </li>
              ))}
            </ul>
          )}
        </Bloco>

        <Bloco titulo="Pilares (meta 70/20/10)">
          <ul className="space-y-3 text-sm">
            {dados.pilares.map((p) => (
              <li key={p.pilar}>
                <div className="flex justify-between">
                  <span className="font-medium text-slate-900">{NOME_PILAR[p.pilar] ?? p.pilar}</span>
                  <span className="text-slate-600">
                    {p.videos} vídeos · {Math.round(p.fatia * 100)}% (meta {Math.round(p.meta * 100)}%)
                  </span>
                </div>
                <div className="mt-1 h-2 rounded-full bg-slate-100">
                  <div className={`h-2 rounded-full bg-rose-500 ${LARGURAS[Math.min(10, Math.round(p.fatia * 10))]}`} />
                </div>
                {p.views_media !== null && (
                  <div className="mt-1 text-xs text-slate-500">
                    {p.views_media} views em média · {p.conclusao_media ?? '—'}% até o fim · {p.seguidores_por_100_views ?? '—'} seguidores
                    por 100 views
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Bloco>
      </div>

      <Bloco titulo="Configurações vencedoras">
        {dados.vencedores.length === 0 ? (
          <p className="text-sm text-slate-500">Os vídeos com 👍 aparecem aqui, com os melhores no TikTok primeiro, prontos para reusar.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {dados.vencedores.map((v) => (
              <li key={v.prediction_id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                <div>
                  <div className="font-medium text-slate-900">{v.arquivo}</div>
                  <div className="text-xs text-slate-500">
                    {v.modelo} · {formatarUsd(v.custo_usd)}
                    {v.pilar ? ` · ${NOME_PILAR[v.pilar] ?? v.pilar}` : ''}
                    {v.views ? ` · ${v.views} views · ${v.conclusao_pct ?? '—'}% até o fim · ${v.seguidores ?? '—'} seguidores` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onReusar({ ...dePedido(v.pedido), rascunhoId: '' })}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:border-slate-500"
                >
                  Reusar
                </button>
              </li>
            ))}
          </ul>
        )}
      </Bloco>

      {dados.rejeicoes_kling.length > 0 && (
        <Bloco titulo="Vídeos de movimento que o Kling rejeita">
          <ul className="text-sm text-slate-700">
            {dados.rejeicoes_kling.map((r) => (
              <li key={r.movimento}>
                {r.movimento} ({r.vezes}x): use só no Seedance.
              </li>
            ))}
          </ul>
        </Bloco>
      )}
    </div>
  )
}
