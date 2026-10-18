import { useCallback, useEffect, useState, type ReactNode } from 'react'
import CartaoVideo from '@/components/CartaoVideo'
import SeletorAsset from '@/components/SeletorAsset'
import { api } from '@/lib/api'
import { formatarBrl, formatarUsd, normalizarEstado, OPCOES_GERAR } from '@/lib/estudioUtil'
import type { Aprendizado, Assets, ConfigEstudio, EstadoEstudio, Pasta, Projeto } from '@/types'

interface Props {
  id: string
  assets: Assets
  config: ConfigEstudio
  aprendizado: Aprendizado | null
  recarregarAssets: () => Promise<void>
  onVoltar: () => void
  onAbrirCriar: (estado: EstadoEstudio) => void
  onMudou: () => void
}

const NOME_PILAR: Record<string, string> = {
  outfit_clima: 'Outfit e clima',
  pov_london: 'POV de London girl',
  lugar: 'Lugar com sentimento',
}
const NOME_FORMATO: Record<string, string> = {
  movimento: 'Ellie copiando um vídeo',
  fotos: 'Ellie a partir das fotos',
  lugar: 'Lugar do UK',
}
const campo = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-rose-500'

function Etapa({ n, titulo, feito, atual, children }: { n: number; titulo: string; feito: boolean; atual: boolean; children: ReactNode }) {
  return (
    <details open={atual || !feito} className={`rounded-2xl border bg-white ${atual ? 'border-rose-300 shadow-sm' : 'border-slate-200'}`}>
      <summary className="flex cursor-pointer items-center gap-3 p-4">
        <span
          className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-sm font-semibold ${
            feito ? 'bg-emerald-500 text-white' : atual ? 'bg-rose-600 text-white' : 'bg-slate-200 text-slate-600'
          }`}
        >
          {feito ? '✓' : n}
        </span>
        <span className="font-semibold text-slate-900">{titulo}</span>
        {atual && <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs text-rose-700">você está aqui</span>}
      </summary>
      <div className="space-y-4 border-t border-slate-100 p-4">{children}</div>
    </details>
  )
}

function Miniatura({ pasta, nome }: { pasta: string; nome: string }) {
  return (
    <img
      src={`/files/${pasta}/${encodeURIComponent(nome)}`}
      alt={nome}
      title={nome}
      className="aspect-[3/4] w-20 shrink-0 rounded-lg border border-slate-200 object-cover"
    />
  )
}

// O passo a passo de um vídeo: da estratégia ao post
export default function ProjetoDetalhe({ id, assets, config, aprendizado, recarregarAssets, onVoltar, onAbrirCriar, onMudou }: Props) {
  const [p, setP] = useState<Projeto | null>(null)
  const [ocupado, setOcupado] = useState('')
  const [erro, setErro] = useState('')
  const [trocando, setTrocando] = useState<string>('')
  const [custos, setCustos] = useState<Record<string, number>>({})
  const [checklist, setChecklist] = useState<Record<string, boolean>>({})
  const [copiado, setCopiado] = useState('')
  const [prompts, setPrompts] = useState<Record<number, string>>({})
  const [criadoDoVideo, setCriadoDoVideo] = useState<Record<string, string>>({})

  const carregar = useCallback(async () => {
    try {
      setP(await api.projeto(id))
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui abrir o projeto')
    }
  }, [id])

  useEffect(() => {
    void carregar()
  }, [carregar])

  // Enquanto gera, atualiza sozinho
  useEffect(() => {
    if (p?.etapa !== 'gerando') return
    const timer = setInterval(() => void carregar(), 5000)
    return () => clearInterval(timer)
  }, [p?.etapa, carregar])

  // Custo de cada botão de gerar
  const motor = p?.plano?.plano.motor === 'kling' ? 'kling' : 'seedance'
  const chavePedido = JSON.stringify(p?.pedido ?? null)
  useEffect(() => {
    if (!p?.pedido || p.plano?.custo_usd === null) return
    const pedido = p.pedido
    void Promise.all(
      OPCOES_GERAR[motor].map((o) =>
        api
          .estimar({ ...pedido, modelo: o.modelo, resolucao: o.resolucao })
          .then((e) => [o.id, e.custo_usd] as const)
          .catch(() => [o.id, NaN] as const),
      ),
    ).then((pares) => setCustos(Object.fromEntries(pares)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chavePedido, motor])

  async function executar(rotulo: string, acao: () => Promise<Projeto | void>) {
    setErro('')
    setOcupado(rotulo)
    try {
      const novo = await acao()
      if (novo) setP(novo)
      else await carregar()
      onMudou()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Algo deu errado')
    } finally {
      setOcupado('')
    }
  }

  const salvar = (campos: Partial<Projeto>) => executar('salvar', () => api.editarProjeto(id, campos))

  async function copiar(texto: string, chave: string) {
    try {
      await navigator.clipboard.writeText(texto)
      setCopiado(chave)
      setTimeout(() => setCopiado(''), 1500)
    } catch {
      setErro('Não consegui copiar. Selecione o texto e copie à mão.')
    }
  }

  if (!p) return <div className="p-8 text-slate-500">{erro || 'Carregando...'}</div>

  const plano = p.plano?.plano
  const videosOk = p.videos_detalhe.filter((v) => v.status === 'ok')
  const escolhido = p.videos_detalhe.find((v) => v.prediction_id === p.video_escolhido)
  const arquivoFinal = escolhido ? escolhido.avaliacao?.video_texto?.arquivo || escolhido.arquivo_1080 || escolhido.arquivo : ''
  const ordem = ['estrategia', 'referencia', 'midias', 'gerar', 'revisar', 'postar']
  const atualIdx = {
    estrategia: 0,
    midias: 2,
    gerar: 3,
    gerando: 3,
    revisar: 4,
    postar: 5,
    postado: 5,
    medido: 5,
  }[p.etapa]
  const restante = config.teto_usd - config.gasto_semana_usd
  const rejeitado = aprendizado?.rejeicoes_kling.find((r) => r.movimento === p.movimento)

  function trocarMidia(pasta: Pasta, selecionados: string[]) {
    if (!p?.plano) return
    const chave = {
      persona: 'persona',
      pecas: 'peca',
      cenarios: 'cenario',
      base: 'imagem_base',
    }[pasta as string]
    if (!chave) return
    const valor = chave === 'persona' ? selecionados : (selecionados[0] ?? '')
    void executar('midia', async () => {
      await api.editarPlano(p.plano!.id, { usar: { [chave]: valor } })
    })
  }

  function slot(pasta: Pasta, titulo: string, nomes: string[], multiplo = false) {
    return (
      <div className="space-y-2 rounded-xl border border-slate-200 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-800">{titulo}</span>
          <button
            type="button"
            onClick={() => setTrocando(trocando === pasta ? '' : pasta)}
            className="text-xs font-medium text-rose-600 underline"
          >
            {trocando === pasta ? 'fechar' : 'trocar ou ✨ criar com IA'}
          </button>
        </div>
        <div className="flex gap-2 overflow-x-auto">
          {nomes.length ? (
            nomes.map((n) => <Miniatura key={n} pasta={pasta} nome={n} />)
          ) : (
            <span className="text-xs text-slate-400">nenhuma</span>
          )}
        </div>
        {trocando === pasta && (
          <SeletorAsset
            pasta={pasta}
            itens={assets[pasta]}
            selecionados={nomes}
            multiplo={multiplo}
            videos={assets.movimentos}
            videoPadrao={p?.movimento}
            semRosto={Boolean(p?.sem_rosto)}
            onMudar={(s) => trocarMidia(pasta, s)}
            onEnviado={async (nome) => {
              await recarregarAssets()
              trocarMidia(pasta, multiplo ? [...nomes, nome] : [nome])
            }}
          />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onVoltar} className="text-sm text-slate-600 hover:text-slate-900">
          ← Todos os projetos
        </button>
        <div className="flex items-center gap-2 text-sm">
          <span className="rounded-full bg-rose-50 px-3 py-1 font-medium text-rose-700">{p.nome_etapa}</span>
          <button
            type="button"
            onClick={() => {
              if (window.confirm('Arquivar este projeto? Os vídeos e as mídias continuam salvos.'))
                void salvar({ arquivado: true }).then(onVoltar)
            }}
            className="text-xs text-slate-400 hover:text-red-600"
          >
            arquivar
          </button>
        </div>
      </div>
      <h1 className="text-2xl font-bold text-slate-900">{p.titulo || 'Novo vídeo'}</h1>
      {erro && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{erro}</p>}

      {/* 1. Estratégia */}
      <Etapa n={1} titulo="Estratégia: o porquê, o gancho e a legenda" feito={Boolean(p.gancho_en)} atual={atualIdx === 0}>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            defaultValue={p.titulo}
            onBlur={(e) => e.target.value !== p.titulo && void salvar({ titulo: e.target.value })}
            placeholder="Título"
            className={campo}
          />
          <div className="flex gap-2">
            <select value={p.pilar} onChange={(e) => void salvar({ pilar: e.target.value })} className={campo}>
              {Object.entries(NOME_PILAR).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select value={p.formato} onChange={(e) => void salvar({ formato: e.target.value as Projeto['formato'] })} className={campo}>
              {Object.entries(NOME_FORMATO).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        </div>
        <textarea
          rows={2}
          defaultValue={p.ideia}
          onBlur={(e) => e.target.value !== p.ideia && void salvar({ ideia: e.target.value })}
          placeholder="A ideia em português"
          className={campo}
        />
        <button
          type="button"
          onClick={() => void executar('estrategia', () => api.estrategia(id))}
          disabled={Boolean(ocupado)}
          className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300"
        >
          {ocupado === 'estrategia'
            ? 'Pensando na estratégia (20 a 60s)...'
            : p.gancho_en
              ? '🧠 Refazer estratégia'
              : '🧠 Montar estratégia com IA'}
        </button>
        {p.porque_pt && <p className="rounded-lg bg-sky-50 p-3 text-sm text-sky-900">{p.porque_pt}</p>}
        {p.ideia_visual_pt && (
          <p className="text-sm text-slate-700">
            <span className="font-medium">O vídeo mostra:</span> {p.ideia_visual_pt}
          </p>
        )}
        {p.ganchos?.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium text-slate-800">Gancho (texto na tela): escolha um</div>
            {p.ganchos.map((g) => (
              <label
                key={g.en}
                className={`flex cursor-pointer gap-3 rounded-lg border p-2.5 text-sm ${p.gancho_en === g.en ? 'border-rose-400 bg-rose-50' : 'border-slate-200'}`}
              >
                <input
                  type="radio"
                  checked={p.gancho_en === g.en}
                  onChange={() => void salvar({ gancho_en: g.en, gancho_pt: g.pt })}
                  className="mt-1 accent-rose-600"
                />
                <span>
                  <span className="font-medium text-slate-900">{g.en}</span>
                  <span className="block text-slate-500">{g.pt}</span>
                </span>
              </label>
            ))}
          </div>
        )}
        {p.legenda_en && (
          <div className="text-sm">
            <span className="font-medium text-slate-800">Legenda:</span> <span className="text-slate-900">{p.legenda_en}</span>
            <span className="block text-slate-500">{p.legenda_pt}</span>
          </div>
        )}
      </Etapa>

      {/* 2. Referência */}
      {p.formato !== 'lugar' && (
        <Etapa
          n={2}
          titulo="Vídeo de referência"
          feito={Boolean(p.movimento) || p.formato === 'fotos'}
          atual={atualIdx === 0 && Boolean(p.gancho_en)}
        >
          <p className="text-sm text-slate-600">
            {p.formato === 'movimento'
              ? 'Escolha ou suba o vídeo cujo movimento a Ellie vai copiar.'
              : 'Opcional: um vídeo de referência só se quiser copiar um movimento ou uma câmera.'}
          </p>
          <SeletorAsset
            pasta="movimentos"
            itens={assets.movimentos}
            selecionados={p.movimento ? [p.movimento] : []}
            onMudar={(s) => void salvar({ movimento: s[0] ?? null })}
            onEnviado={async (nome) => {
              await recarregarAssets()
              await salvar({ movimento: nome })
            }}
          />
          {rejeitado && (
            <p className="text-sm text-amber-700">O Kling já rejeitou este vídeo {rejeitado.vezes}x: o plano vai usar o Seedance.</p>
          )}
          {p.movimento && (
            <div className="space-y-2 rounded-xl border border-rose-200 bg-rose-50/40 p-3">
              <div className="text-sm font-medium text-slate-800">Criar a partir deste vídeo</div>
              <p className="text-xs text-slate-600">
                A IA olha quadros do vídeo e recria só o que você pedir (ignora a pessoa e o texto em cima). A mídia já entra no plano.
              </p>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ['pecas', '👗 A roupa do vídeo'],
                    ['cenarios', '🏠 O lugar do vídeo'],
                    ['base', '🧍 A Ellie com essa roupa (Kling)'],
                  ] as [Pasta, string][]
                ).map(([pasta, rotulo]) => (
                  <button
                    key={pasta}
                    type="button"
                    onClick={() =>
                      void executar(`dovideo-${pasta}`, async () => {
                        const { nome } = await api.midiaDoVideo(p.movimento!, pasta, '')
                        await recarregarAssets()
                        setCriadoDoVideo((atual) => ({
                          ...atual,
                          [pasta]: nome,
                        }))
                        if (p.plano) {
                          const chave = {
                            pecas: 'peca',
                            cenarios: 'cenario',
                            base: 'imagem_base',
                          }[pasta as 'pecas' | 'cenarios' | 'base']
                          await api.editarPlano(p.plano.id, {
                            usar: { [chave]: nome },
                          })
                        }
                      })
                    }
                    disabled={Boolean(ocupado)}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:border-rose-400 disabled:opacity-50"
                  >
                    {ocupado === `dovideo-${pasta}` ? 'Criando (30s a 1,5 min)...' : rotulo}
                  </button>
                ))}
              </div>
              {Object.keys(criadoDoVideo).length > 0 && (
                <div className="flex gap-2">
                  {Object.entries(criadoDoVideo).map(([pasta, nome]) => (
                    <Miniatura key={pasta} pasta={pasta} nome={nome} />
                  ))}
                </div>
              )}
            </div>
          )}
        </Etapa>
      )}

      {/* 3. Plano e mídias */}
      <Etapa n={3} titulo="Plano e mídias" feito={Boolean(p.plano?.pronto)} atual={atualIdx === 2}>
        {p.formato === 'lugar' ? (
          <div className="space-y-2 text-sm">
            <p className="text-slate-600">Clipes de lugar são montados no Criar, no modo Lugar (foto do lugar e câmera).</p>
            <button
              type="button"
              onClick={() =>
                onAbrirCriar(
                  normalizarEstado({
                    modo: 'lugar',
                    tipo: 'lugar',
                    nome: p.titulo,
                    cena: p.ideia_visual_pt,
                    pilar: 'lugar',
                  }),
                )
              }
              className="rounded-lg bg-slate-900 px-4 py-2 font-medium text-white"
            >
              Abrir no Criar (Lugar)
            </button>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void executar('planejar', () => api.planejarProjeto(id))}
              disabled={Boolean(ocupado) || (p.formato === 'movimento' && !p.movimento)}
              className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300"
            >
              {ocupado === 'planejar'
                ? 'A IA está estudando o vídeo e a biblioteca (30s a 2 min)...'
                : plano
                  ? '🧠 Refazer o plano'
                  : '🧠 Planejar com IA'}
            </button>
            {p.formato === 'movimento' && !p.movimento && (
              <p className="text-sm text-amber-700">Escolha o vídeo de referência no passo 2.</p>
            )}

            {plano && p.plano && (
              <div className="space-y-4">
                {plano.analise.resumo_pt && <p className="text-sm text-slate-700">{plano.analise.resumo_pt}</p>}
                <div className="rounded-lg bg-sky-50 p-3 text-sm text-sky-900">
                  <span className="font-semibold">
                    {plano.motor === 'kling' ? 'Kling' : 'Seedance'} · {plano.modelo}:
                  </span>{' '}
                  {plano.porque_pt}
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-800">
                  <input
                    type="checkbox"
                    checked={Boolean(p.sem_rosto)}
                    onChange={(e) => void salvar({ sem_rosto: e.target.checked })}
                    className="accent-rose-600"
                  />
                  Sem mostrar o rosto (do queixo para baixo): só usa fotos da Ellie sem rosto
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  {plano.motor === 'kling' ? (
                    slot('base', 'Imagem base da Ellie', plano.usar.imagem_base ? [plano.usar.imagem_base] : [])
                  ) : (
                    <>
                      {slot('persona', 'Fotos da Ellie', plano.usar.persona, true)}
                      {slot('pecas', 'Peça', plano.usar.peca ? [plano.usar.peca] : [])}
                      {slot('cenarios', 'Cenário', plano.usar.cenario ? [plano.usar.cenario] : [])}
                    </>
                  )}
                </div>
                {plano.criar.filter((c) => !c.arquivo).length > 0 && (
                  <div className="space-y-2">
                    <div className="text-sm font-medium text-slate-800">A IA sugere criar</div>
                    {plano.criar.map((c, i) =>
                      c.arquivo ? null : (
                        <div key={c.nome + i} className="space-y-2 rounded-xl border border-rose-200 bg-rose-50/40 p-3">
                          <div className="text-sm font-medium text-slate-900">{c.nome}</div>
                          {c.porque_pt && <p className="text-xs text-slate-600">{c.porque_pt}</p>}
                          <textarea
                            rows={3}
                            value={prompts[i] ?? c.prompt}
                            onChange={(e) => setPrompts({ ...prompts, [i]: e.target.value })}
                            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 font-mono text-xs outline-none"
                          />
                          <button
                            type="button"
                            onClick={() =>
                              void executar(`criar${i}`, async () => {
                                await api.criarMidia(p.plano!.id, i, prompts[i] ?? c.prompt)
                                await recarregarAssets()
                              })
                            }
                            disabled={Boolean(ocupado)}
                            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300"
                          >
                            {ocupado === `criar${i}` ? 'Criando a imagem (30s a 1,5 min)...' : '✨ Criar imagem'}
                          </button>
                        </div>
                      ),
                    )}
                  </div>
                )}
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-slate-800">Cena (inglês)</span>
                  <textarea
                    rows={2}
                    defaultValue={plano.video.cena}
                    onBlur={(e) =>
                      e.target.value !== plano.video.cena &&
                      void executar('cena', async () => {
                        await api.editarPlano(p.plano!.id, {
                          video: { cena: e.target.value },
                        })
                      })
                    }
                    className={`${campo} font-mono text-xs`}
                  />
                </label>
                {plano.riscos_pt.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800">
                    {plano.riscos_pt.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                )}
                {p.plano.falta && <p className="text-sm text-amber-700">Falta: {p.plano.falta}</p>}
              </div>
            )}
          </>
        )}
      </Etapa>

      {/* 4. Gerar */}
      <Etapa n={4} titulo="Gerar" feito={videosOk.length > 0} atual={atualIdx === 3}>
        {p.etapa === 'gerando' && (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">⏳ Gerando... o vídeo aparece no passo 5 em 1 a 4 minutos.</p>
        )}
        {!p.pedido || !p.plano?.pronto ? (
          <p className="text-sm text-slate-500">Termine o plano e as mídias (passo 3) para liberar.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {OPCOES_GERAR[motor].map((o, i) => {
              const custo = custos[o.id]
              return (
                <div key={o.id} className={`rounded-xl border-2 p-3 ${i === 1 ? 'border-rose-300' : 'border-slate-200'}`}>
                  <div className="font-semibold text-slate-900">{o.titulo}</div>
                  <div className="text-xs text-slate-500">
                    {o.modelo}
                    {motor === 'seedance' ? ` · ${o.resolucao}` : ''}
                  </div>
                  <p className="mt-1 text-sm text-slate-600">{o.dica}</p>
                  <button
                    type="button"
                    onClick={() =>
                      void executar(`gerar${o.id}`, async () => {
                        await api.gerar({
                          ...p.pedido!,
                          modelo: o.modelo,
                          resolucao: o.resolucao,
                          projeto_id: p.id,
                        })
                      })
                    }
                    disabled={Boolean(ocupado) || (Number.isFinite(custo) && custo > restante)}
                    className={`mt-2 w-full rounded-lg px-4 py-2 font-semibold text-white disabled:bg-slate-300 ${i === 1 ? 'bg-rose-600 hover:bg-rose-700' : 'bg-slate-900 hover:bg-slate-700'}`}
                  >
                    {ocupado === `gerar${o.id}`
                      ? 'Enviando...'
                      : `Gerar · ${Number.isFinite(custo) ? `${formatarUsd(custo)} (${formatarBrl(custo * config.cotacao)})` : '...'}`}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </Etapa>

      {/* 5. Revisar */}
      <Etapa n={5} titulo="Revisar, texto na tela e legenda" feito={Boolean(p.video_escolhido)} atual={atualIdx === 4}>
        {p.videos_detalhe
          .filter((v) => v.status === 'falhou')
          .map((v) => (
            <p key={v.prediction_id} className="text-sm text-red-600">
              ⚠️ Uma tentativa falhou (não cobrada): {v.erro}
            </p>
          ))}
        {videosOk.length === 0 ? (
          <p className="text-sm text-slate-500">Os vídeos gerados aparecem aqui.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {videosOk.map((v) => (
              <div key={v.prediction_id} className="space-y-2">
                <button
                  type="button"
                  onClick={() =>
                    void salvar({
                      video_escolhido: p.video_escolhido === v.prediction_id ? '' : v.prediction_id,
                    })
                  }
                  className={`w-full rounded-lg py-2 text-sm font-semibold ${p.video_escolhido === v.prediction_id ? 'bg-emerald-600 text-white' : 'border border-slate-300 text-slate-700 hover:border-emerald-500'}`}
                >
                  {p.video_escolhido === v.prediction_id ? '⭐ Este vai ser postado' : '⭐ Usar este para postar'}
                </button>
                <CartaoVideo
                  item={v}
                  nomesProblemas={aprendizado?.nomes_problemas ?? {}}
                  onReusar={onAbrirCriar}
                  onMudou={() => void carregar()}
                  projeto={p}
                  onUsarNoPost={(legenda_en, legenda_pt) => void salvar({ legenda_en, legenda_pt })}
                />
              </div>
            ))}
          </div>
        )}
      </Etapa>

      {/* 6. Postar */}
      <Etapa n={6} titulo="Postar e medir" feito={Boolean(p.postado_em)} atual={atualIdx === 5}>
        {!escolhido ? (
          <p className="text-sm text-slate-500">Escolha o vídeo que vai ser postado no passo 5.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <div className="space-y-2">
              <video
                src={`/saida/${encodeURIComponent(arquivoFinal)}`}
                controls
                loop
                playsInline
                className="aspect-[9/16] w-full rounded-xl bg-black"
              />
              <a
                href={`/saida/${encodeURIComponent(arquivoFinal)}`}
                download={arquivoFinal}
                className="block rounded-lg bg-rose-600 py-2 text-center text-sm font-semibold text-white hover:bg-rose-700"
              >
                ⬇ Baixar vídeo
              </a>
              {!escolhido.avaliacao?.video_texto && (
                <p className="text-xs text-amber-700">Sem texto na tela ainda: aplique no passo 5 (🅣 Texto na tela).</p>
              )}
            </div>
            <div className="space-y-3 text-sm">
              {(() => {
                const leg = escolhido.avaliacao?.legendas
                const recomendada = leg?.opcoes[leg.recomendada]
                const legenda = p.legenda_en || recomendada?.legenda_en || ''
                return legenda ? (
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Legenda para colar no TikTok</div>
                    <div className="font-medium text-slate-900">{legenda}</div>
                    <div className="text-slate-500">{p.legenda_pt || recomendada?.legenda_pt}</div>
                    <button
                      type="button"
                      onClick={() => void copiar(legenda, 'legenda')}
                      className="mt-2 rounded-md border border-slate-300 px-3 py-1 text-xs"
                    >
                      {copiado === 'legenda' ? 'Copiado!' : 'Copiar legenda'}
                    </button>
                  </div>
                ) : (
                  <p className="text-slate-500">Sem legenda: use ✍️ Sugerir legenda no vídeo (passo 5).</p>
                )
              })()}
              <div className="space-y-1">
                {[
                  ['texto', 'Texto na tela aplicado'],
                  ['rotulo', 'Rótulo "AI-generated content" marcado'],
                  ['vpn', 'VPN do UK ligada'],
                  ['som', 'Som escolhido no TikTok (opcional)'],
                ].map(([chave, rotulo]) => (
                  <label key={chave} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(checklist[chave])}
                      onChange={(e) =>
                        setChecklist({
                          ...checklist,
                          [chave]: e.target.checked,
                        })
                      }
                      className="accent-rose-600"
                    />
                    {rotulo}
                  </label>
                ))}
              </div>
              {p.postado_em ? (
                <p className="rounded-lg bg-emerald-50 p-3 text-emerald-800">
                  ✅ Postado em {p.postado_em.slice(8, 10)}/{p.postado_em.slice(5, 7)}. Daqui a 48h, coloque views, % até o fim e seguidores
                  em "Resultado no TikTok" no vídeo do passo 5: é isso que ensina a próxima pauta.
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    void salvar({
                      postado_em: new Date().toISOString().slice(0, 19),
                    })
                  }
                  className="rounded-lg bg-emerald-600 px-4 py-2 font-semibold text-white hover:bg-emerald-700"
                >
                  Marcar como postado
                </button>
              )}
            </div>
          </div>
        )}
      </Etapa>
      <p className="text-center text-xs text-slate-400">
        Etapas: {ordem.length} · Projeto {p.id}
      </p>
    </div>
  )
}
