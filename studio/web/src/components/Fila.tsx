import { useCallback, useEffect, useRef, useState } from 'react'
import CartaoVideo from '@/components/CartaoVideo'
import { api } from '@/lib/api'
import { dePedido, formatarUsd } from '@/lib/estudioUtil'
import type { EstadoEstudio, ItemHistorico, Job, Rascunho } from '@/types'

interface Props {
  nomesProblemas: Record<string, string>
  onAbrir: (estado: EstadoEstudio) => void
  onMudou: () => void
}

const NOME_PILAR: Record<string, string> = { outfit_clima: 'Outfit e clima', pov_london: 'POV London', lugar: 'Lugar' }

function Titulo({ texto, qtd }: { texto: string; qtd: number }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-900">
      {texto}
      <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700">{qtd}</span>
    </h2>
  )
}

// Tela inicial: o que o assistente preparou, o que está gerando, o que falta avaliar e o histórico
export default function Fila({ nomesProblemas, onAbrir, onMudou }: Props) {
  const [rascunhos, setRascunhos] = useState<Rascunho[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [historico, setHistorico] = useState<ItemHistorico[]>([])
  const [erro, setErro] = useState('')
  const [gerando, setGerando] = useState('')
  const [verAvaliados, setVerAvaliados] = useState(false)
  const rodandoAntes = useRef(0)

  const atualizar = useCallback(async () => {
    try {
      const [r, j, h] = await Promise.all([api.rascunhos(), api.jobs(), api.historico()])
      setRascunhos(r)
      setJobs(j)
      setHistorico(h)
      const rodando = j.filter((x) => x.status === 'rodando').length
      if (rodando < rodandoAntes.current) onMudou() // algo terminou: atualiza gasto e aprendizado
      rodandoAntes.current = rodando
    } catch {
      setErro('Não consegui falar com o servidor do Estúdio.')
    }
  }, [onMudou])

  const rodando = jobs.filter((j) => j.status === 'rodando')

  useEffect(() => {
    void atualizar()
    const timer = setInterval(() => void atualizar(), rodando.length ? 3000 : 12000)
    return () => clearInterval(timer)
  }, [atualizar, rodando.length])

  async function gerarRascunho(r: Rascunho) {
    setErro('')
    setGerando(r.id)
    try {
      await api.gerar(r.pedido)
      await atualizar()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao gerar')
    } finally {
      setGerando('')
    }
  }

  async function descartar(r: Rascunho) {
    if (!window.confirm(`Descartar o rascunho "${r.pedido.nome || r.id}"?`)) return
    await api.descartarRascunho(r.id)
    await atualizar()
  }

  const prontos = historico.filter((i) => i.status === 'ok' && i.arquivo)
  const paraAvaliar = prontos.filter((i) => !i.avaliacao?.nota)
  const avaliados = prontos.filter((i) => i.avaliacao?.nota)
  const falhasRecentes = jobs.filter((j) => j.status === 'falhou')

  return (
    <div className="space-y-8">
      {erro && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{erro}</p>}

      {rascunhos.length > 0 && (
        <section>
          <Titulo texto="Preparados pelo assistente" qtd={rascunhos.length} />
          <div className="grid gap-3 md:grid-cols-2">
            {[...rascunhos].reverse().map((r) => (
              <div key={r.id} className="space-y-2 rounded-2xl border border-rose-200 bg-white p-4 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900">{r.pedido.nome || r.id}</div>
                    <div className="text-xs text-slate-500">
                      {r.pedido.modelo} · {r.pedido.duracao}s{r.pedido.pilar ? ` · ${NOME_PILAR[r.pedido.pilar]}` : ''}
                    </div>
                  </div>
                  <span className="shrink-0 font-semibold text-slate-900">{formatarUsd(r.custo_usd)}</span>
                </div>
                {r.nota && <p className="text-slate-700">{r.nota}</p>}
                {r.dica && <p className="rounded-lg bg-sky-50 p-2 text-xs text-sky-800">Autoestudo: {r.dica}</p>}
                {r.repetidos?.length > 0 && (
                  <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
                    Já existe vídeo igual: {r.repetidos.map((x) => x.arquivo).join(', ')}. Só gere se quiser outra tentativa.
                  </p>
                )}
                {r.passa_do_teto && <p className="text-xs font-medium text-red-600">Passa do teto semanal.</p>}
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => void gerarRascunho(r)}
                    disabled={gerando === r.id || r.passa_do_teto}
                    className="rounded-lg bg-rose-600 px-4 py-2 font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300"
                  >
                    {gerando === r.id ? 'Enviando...' : `Gerar (${formatarUsd(r.custo_usd)})`}
                  </button>
                  <button
                    type="button"
                    onClick={() => onAbrir(dePedido(r.pedido))}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-slate-700 hover:border-slate-500"
                  >
                    Abrir e ajustar
                  </button>
                  <button type="button" onClick={() => void descartar(r)} className="px-2 text-slate-400 hover:text-red-600">
                    Descartar
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {(rodando.length > 0 || falhasRecentes.length > 0) && (
        <section>
          <Titulo texto="Gerando agora" qtd={rodando.length} />
          <div className="space-y-2">
            {[...rodando, ...falhasRecentes].map((j) => (
              <div key={j.id} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm">
                <span className="font-medium text-slate-900">{j.nome}</span>
                <span className={j.status === 'falhou' ? 'text-red-600' : 'text-slate-600'}>
                  {j.status === 'rodando' ? `⏳ ${j.etapa}` : `⚠️ ${j.erro || 'falhou'} (não cobrado)`}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <Titulo texto="Para avaliar" qtd={paraAvaliar.length} />
        {paraAvaliar.length === 0 ? (
          <p className="text-sm text-slate-500">Nada pendente. Cada 👍/👎 ensina o sistema a escolher o modelo certo e gastar menos.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {paraAvaliar.map((i) => (
              <CartaoVideo key={i.prediction_id} item={i} nomesProblemas={nomesProblemas} onReusar={onAbrir} onMudou={onMudou} />
            ))}
          </div>
        )}
      </section>

      {avaliados.length > 0 && (
        <section>
          <button type="button" onClick={() => setVerAvaliados(!verAvaliados)} className="w-full text-left">
            <Titulo texto={`Avaliados ${verAvaliados ? '▾' : '▸'}`} qtd={avaliados.length} />
          </button>
          {verAvaliados && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {avaliados.map((i) => (
                <CartaoVideo key={i.prediction_id} item={i} nomesProblemas={nomesProblemas} onReusar={onAbrir} onMudou={onMudou} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
