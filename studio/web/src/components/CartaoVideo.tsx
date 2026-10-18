import { useState } from 'react'
import EditorTexto from '@/components/EditorTexto'
import { api } from '@/lib/api'
import { dePedido, ehKling } from '@/lib/estudioUtil'
import type { Avaliacao, EstadoEstudio, ItemHistorico, Projeto } from '@/types'

interface Props {
  item: ItemHistorico
  nomesProblemas: Record<string, string>
  onReusar: (estado: EstadoEstudio) => void
  onMudou: () => void
  // Dentro de um projeto: o gancho e a legenda da estratégia entram no editor e no post
  projeto?: Projeto
  onUsarNoPost?: (legenda_en: string, legenda_pt: string) => void
}

const NOME_PILAR: Record<string, string> = {
  outfit_clima: 'Outfit e clima',
  pov_london: 'POV London',
  lugar: 'Lugar',
}

// Um vídeo gerado: assistir, avaliar (é isso que ensina o sistema) e reaproveitar a configuração
export default function CartaoVideo({ item, nomesProblemas, onReusar, onMudou, projeto, onUsarNoPost }: Props) {
  const [av, setAv] = useState<Avaliacao>(item.avaliacao ?? {})
  const [comentario, setComentario] = useState(item.avaliacao?.comentario ?? '')
  const [tiktok, setTiktok] = useState({
    views: item.avaliacao?.tiktok?.views?.toString() ?? '',
    conclusao_pct: item.avaliacao?.tiktok?.conclusao_pct?.toString() ?? '',
    seguidores: item.avaliacao?.tiktok?.seguidores?.toString() ?? '',
  })
  const [salvo, setSalvo] = useState('')
  const [revisando, setRevisando] = useState(false)
  const [escrevendo, setEscrevendo] = useState(false)
  const [copiado, setCopiado] = useState('')
  // Editor de texto na tela (null = fechado; string = texto inicial)
  const [editor, setEditor] = useState<string | null>(null)
  const [erro, setErro] = useState('')

  const arquivo = item.arquivo_1080 || item.arquivo
  const custo = Number(item.custo_real_usd || item.custo_estimado_usd || 0)
  const pedido = item.pedido
  // Ganchos da estratégia do projeto primeiro, depois os sugeridos para este vídeo
  const sugestoesTela = [
    ...(projeto?.gancho_en ? [projeto.gancho_en] : []),
    ...(projeto?.ganchos ?? []).map((g) => g.en),
    ...(av.legendas?.opcoes ?? []).map((o) => o.texto_tela_en),
  ].filter((t, i, todos) => t && todos.indexOf(t) === i)
  const ehRascunhoBarato = pedido && !ehKling(pedido.modelo) && (pedido.modelo === '2.0-mini' || pedido.resolucao === '480p')

  async function salvar(campos: Partial<Avaliacao>, aviso = 'Salvo') {
    setErro('')
    try {
      const r = await api.avaliar(item.prediction_id, campos)
      setAv(r.avaliacao)
      setSalvo(aviso)
      setTimeout(() => setSalvo(''), 1500)
      onMudou()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui salvar')
    }
  }

  async function revisarComIa() {
    setErro('')
    setRevisando(true)
    try {
      const r = await api.revisar(item.prediction_id)
      setAv(r.avaliacao)
      onMudou()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'A revisão com IA falhou')
    } finally {
      setRevisando(false)
    }
  }

  async function sugerirLegenda() {
    setErro('')
    setEscrevendo(true)
    try {
      setAv((await api.legenda(item.prediction_id)).avaliacao)
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'A sugestão de legenda falhou')
    } finally {
      setEscrevendo(false)
    }
  }

  async function virarReferencia() {
    setErro('')
    try {
      const r = await api.paraReferencia(item.prediction_id)
      setAv(r.avaliacao)
      setSalvo(`Virou vídeo de referência: ${r.nome}`)
      onMudou()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui copiar o vídeo')
    }
  }

  async function copiar(texto: string, chave: string) {
    try {
      await navigator.clipboard.writeText(texto)
      setCopiado(chave)
      setTimeout(() => setCopiado(''), 1500)
    } catch {
      setErro('Não consegui copiar. Selecione o texto e copie à mão.')
    }
  }

  function alternarProblema(p: string) {
    const atuais = av.problemas ?? []
    void salvar({
      problemas: atuais.includes(p) ? atuais.filter((x) => x !== p) : [...atuais, p],
    })
  }

  function salvarTiktok() {
    const numero = (v: string) => (v.trim() === '' ? undefined : Number(v.replace(',', '.')))
    void salvar(
      {
        tiktok: {
          views: numero(tiktok.views),
          conclusao_pct: numero(tiktok.conclusao_pct),
          seguidores: numero(tiktok.seguidores),
        },
      },
      'Números salvos',
    )
  }

  const botaoNota = (nota: 'bom' | 'ruim', rotulo: string) => (
    <button
      type="button"
      onClick={() => void salvar({ nota: av.nota === nota ? '' : nota })}
      className={`flex-1 rounded-lg border-2 py-2 text-lg transition ${
        av.nota === nota
          ? nota === 'bom'
            ? 'border-emerald-500 bg-emerald-50'
            : 'border-red-400 bg-red-50'
          : 'border-slate-200 bg-white hover:border-slate-400'
      }`}
      aria-pressed={av.nota === nota}
    >
      {rotulo}
    </button>
  )

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <video
        src={`/saida/${encodeURIComponent(arquivo)}`}
        controls
        loop
        playsInline
        preload="metadata"
        className="aspect-[9/16] max-h-[420px] w-full bg-black"
      />
      <div className="space-y-3 p-3 text-sm">
        <div>
          <div className="truncate font-semibold text-slate-900">{arquivo}</div>
          <div className="text-xs text-slate-500">
            {item.modelo} · {item.duracao}s · US$ {custo.toFixed(2)}
            {item.pilar ? ` · ${NOME_PILAR[item.pilar] ?? item.pilar}` : ''} · {item.data.slice(8, 10)}/{item.data.slice(5, 7)}
          </div>
        </div>

        <div className="flex gap-2">
          {botaoNota('bom', '👍')}
          {botaoNota('ruim', '👎')}
        </div>

        {(av.nota === 'ruim' || (av.problemas ?? []).length > 0) && (
          <div>
            <div className="mb-1 text-xs font-medium text-slate-600">O que deu errado?</div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(nomesProblemas).map(([chave, nome]) => {
                const ativo = (av.problemas ?? []).includes(chave)
                return (
                  <button
                    key={chave}
                    type="button"
                    onClick={() => alternarProblema(chave)}
                    className={`rounded-full border px-2.5 py-1 text-xs transition ${
                      ativo ? 'border-red-400 bg-red-50 text-red-700' : 'border-slate-200 text-slate-600 hover:border-slate-400'
                    }`}
                  >
                    {nome}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {av.analise_ia && (av.analise_ia.comentario || av.analise_ia.problemas.length > 0) && (
          <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
            <span className="font-medium">
              Análise da IA
              {av.analise_ia.nota_sugerida ? ` (sugere ${av.analise_ia.nota_sugerida === 'bom' ? '👍' : '👎'})` : ''}:
            </span>{' '}
            {av.analise_ia.comentario}
            {av.analise_ia.problemas.length > 0 && ` (${av.analise_ia.problemas.map((p) => nomesProblemas[p] ?? p).join(', ')})`}
          </div>
        )}

        <button
          type="button"
          onClick={() => void revisarComIa()}
          disabled={revisando}
          className="w-full rounded-lg border border-slate-300 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-500 disabled:opacity-60"
        >
          {revisando ? 'A IA está olhando o vídeo (10 a 40s)...' : av.analise_ia ? '🔍 Revisar de novo com IA' : '🔍 Revisar com IA'}
        </button>

        <button
          type="button"
          onClick={() => void sugerirLegenda()}
          disabled={escrevendo}
          className="w-full rounded-lg border border-slate-300 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-500 disabled:opacity-60"
        >
          {escrevendo ? 'Escrevendo a legenda (10 a 40s)...' : av.legendas ? '✍️ Sugerir outras legendas' : '✍️ Sugerir legenda'}
        </button>

        {av.legendas && (
          <div className="space-y-2">
            {av.legendas.opcoes.map((o, i) => (
              <div
                key={i}
                className={`space-y-1.5 rounded-lg border p-2 text-xs ${i === av.legendas!.recomendada ? 'border-rose-300 bg-rose-50/60' : 'border-slate-200'}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-rose-700">
                    {o.origem === 'projeto' ? 'Da estratégia do projeto' : i === av.legendas!.recomendada ? 'Recomendada' : ''}
                  </span>
                  {onUsarNoPost && o.legenda_en && (
                    <button
                      type="button"
                      onClick={() => onUsarNoPost(o.legenda_en, o.legenda_pt)}
                      disabled={projeto?.legenda_en === o.legenda_en}
                      className="rounded-md border border-emerald-500 px-2 py-0.5 text-[11px] font-medium text-emerald-700 disabled:border-transparent disabled:bg-emerald-50"
                    >
                      {projeto?.legenda_en === o.legenda_en ? '✓ Legenda do post' : 'Usar no post'}
                    </button>
                  )}
                </div>
                {[
                  ['tela', 'Texto na tela', o.texto_tela_en, o.texto_tela_pt],
                  ['legenda', 'Legenda', o.legenda_en, o.legenda_pt],
                ].map(([chave, rotulo, en, pt]) => (
                  <div key={chave} className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[11px] text-slate-500">{rotulo}</div>
                      <div className="font-medium text-slate-900">{en}</div>
                      <div className="text-slate-500">{pt}</div>
                    </div>
                    <div className="flex shrink-0 flex-col gap-1">
                      <button
                        type="button"
                        onClick={() => void copiar(en, `${i}-${chave}`)}
                        className="rounded-md border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:border-slate-500"
                      >
                        {copiado === `${i}-${chave}` ? 'Copiado!' : 'Copiar'}
                      </button>
                      {chave === 'tela' && (
                        <button
                          type="button"
                          onClick={() => setEditor(en)}
                          className="rounded-md bg-slate-900 px-2 py-0.5 text-[11px] text-white hover:bg-slate-700 disabled:bg-slate-300"
                        >
                          No vídeo
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ))}
            {av.legendas.porque_pt && <p className="text-[11px] text-slate-500">{av.legendas.porque_pt}</p>}
            <p className="text-[11px] text-slate-500">Ao postar, marque o rótulo "AI-generated content".</p>
          </div>
        )}

        <div className="space-y-2 rounded-lg border border-slate-200 p-2">
          <button
            type="button"
            onClick={() => setEditor(av.video_texto?.texto ?? projeto?.gancho_en ?? '')}
            className="w-full rounded-lg bg-slate-900 py-1.5 text-xs font-medium text-white hover:bg-slate-700"
          >
            {av.video_texto ? '🅣 Editar texto na tela' : '🅣 Colocar texto na tela'}
          </button>
          {av.video_texto && (
            <div className="space-y-1">
              <video
                src={`/saida/${encodeURIComponent(av.video_texto.arquivo)}`}
                controls
                loop
                playsInline
                className="aspect-[9/16] max-h-[360px] w-full rounded-lg bg-black"
              />
              <a
                href={`/saida/${encodeURIComponent(av.video_texto.arquivo)}`}
                download={av.video_texto.arquivo}
                className="block rounded-md bg-rose-600 py-1.5 text-center text-xs font-semibold text-white hover:bg-rose-700"
              >
                ⬇ Baixar vídeo com texto
              </a>
            </div>
          )}
        </div>
        {editor !== null && (
          <EditorTexto
            item={{ ...item, avaliacao: av }}
            textoInicial={editor}
            sugestoes={sugestoesTela}
            onFechar={() => setEditor(null)}
            onAplicado={(nova) => {
              setAv(nova)
              onMudou()
            }}
          />
        )}

        <input
          value={comentario}
          onChange={(e) => setComentario(e.target.value)}
          onBlur={() => comentario !== (av.comentario ?? '') && void salvar({ comentario })}
          placeholder="Comentário (opcional)"
          className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm outline-none focus:border-rose-400"
        />

        <details className="rounded-lg border border-slate-200 p-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-700">
            Resultado no TikTok (48h)
            {av.tiktok?.views ? ` · ${av.tiktok.views} views` : ''}
          </summary>
          <div className="mt-2 grid grid-cols-3 gap-2">
            {(
              [
                ['views', 'Views'],
                ['conclusao_pct', '% até o fim'],
                ['seguidores', 'Seguidores'],
              ] as const
            ).map(([chave, rotulo]) => (
              <label key={chave} className="text-xs text-slate-600">
                {rotulo}
                <input
                  inputMode="decimal"
                  value={tiktok[chave]}
                  onChange={(e) => setTiktok({ ...tiktok, [chave]: e.target.value })}
                  className="mt-0.5 w-full rounded-md border border-slate-200 px-2 py-1 text-sm outline-none focus:border-rose-400"
                />
              </label>
            ))}
          </div>
          <button type="button" onClick={salvarTiktok} className="mt-2 rounded-md bg-slate-900 px-3 py-1 text-xs text-white">
            Salvar números
          </button>
        </details>

        {pedido && (
          <div className="flex flex-wrap gap-2">
            {ehRascunhoBarato && (
              <button
                type="button"
                onClick={() =>
                  onReusar({
                    ...dePedido(pedido),
                    modelo: '2.0-fast',
                    resolucao: '720p',
                    rascunhoId: '',
                  })
                }
                className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
              >
                Fazer versão para postar
              </button>
            )}
            <button
              type="button"
              onClick={() => onReusar({ ...dePedido(pedido), rascunhoId: '' })}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:border-slate-500"
            >
              Reusar configuração
            </button>
          </div>
        )}

        <button
          type="button"
          onClick={() => void virarReferencia()}
          disabled={Boolean(av.virou_referencia)}
          className="w-full rounded-lg border border-slate-300 py-1.5 text-xs text-slate-700 hover:border-slate-500 disabled:border-emerald-300 disabled:text-emerald-700"
        >
          {av.virou_referencia ? `♻️ Já é referência (${av.virou_referencia})` : '♻️ Usar como referência de movimento'}
        </button>
        {salvo && <p className="text-xs text-emerald-600">{salvo}</p>}
        {erro && <p className="text-xs text-red-600">{erro}</p>}
      </div>
    </div>
  )
}
