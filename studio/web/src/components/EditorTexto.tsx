import { useCallback, useEffect, useRef, useState, type PointerEvent } from 'react'
import { api } from '@/lib/api'
import type { Avaliacao, ItemHistorico } from '@/types'

// Editor do texto na tela: a prévia é desenhada num canvas 1080x1920 por cima do vídeo e é exatamente
// essa camada que vai para o vídeo final (o que você vê é o que sai).

export type FonteTexto = 'classico' | 'forte' | 'maquina' | 'manuscrito' | 'serifa' | 'moderna' | 'impacto'
export type FundoTexto = 'nenhum' | 'sombra' | 'contorno' | 'caixa_branca' | 'caixa_preta' | 'caixa_translucida'

export interface ConfigTexto {
  texto: string
  fonte: FonteTexto
  fundo: FundoTexto
  tamanho: number
  cor: string
  x: number // centro do bloco, de 0 a 1
  y: number // topo do bloco, de 0 a 1
  largura: number // largura máxima do bloco em px (vídeo de 1080)
}

const LARGURA = 1080
const ALTURA = 1920

const FONTES: Record<FonteTexto, { nome: string; css: (t: number) => string }> = {
  classico: { nome: 'Clássico (TikTok)', css: (t) => `700 ${t}px "Segoe UI", Arial, sans-serif` },
  forte: { nome: 'Forte', css: (t) => `900 ${t}px "Arial Black", Arial, sans-serif` },
  maquina: { nome: 'Máquina de escrever', css: (t) => `700 ${t}px "Courier New", monospace` },
  manuscrito: { nome: 'Manuscrito', css: (t) => `400 ${t}px "Ink Free", "Segoe Script", cursive` },
  serifa: { nome: 'Serifada itálica', css: (t) => `italic 400 ${t}px Georgia, serif` },
  moderna: { nome: 'Moderna', css: (t) => `600 ${t}px Bahnschrift, "Segoe UI", sans-serif` },
  impacto: { nome: 'Impacto', css: (t) => `400 ${t}px Impact, sans-serif` },
}

const FUNDOS: { id: FundoTexto; nome: string; cor: string }[] = [
  { id: 'nenhum', nome: 'Só a letra', cor: '' },
  { id: 'sombra', nome: 'Sombra suave', cor: '' },
  { id: 'contorno', nome: 'Contorno', cor: '' },
  { id: 'caixa_branca', nome: 'Caixa branca', cor: '#000000' },
  { id: 'caixa_preta', nome: 'Caixa preta', cor: '#ffffff' },
  { id: 'caixa_translucida', nome: 'Caixa translúcida', cor: '#ffffff' },
]

const CORES = ['#ffffff', '#000000', '#221e1c', '#f5ead6', '#fe2c55', '#25f4ee', '#ffd60a', '#e8b4b8']

// Zonas que a interface do TikTok cobre (abas no topo, ícones à direita, legenda e música embaixo)
const ZONAS: [number, number, number, number][] = [
  [0, 0, LARGURA, 150],
  [LARGURA - 150, 760, 150, 760],
  [0, ALTURA - 400, LARGURA, 400],
]

export const configPadrao = (texto = ''): ConfigTexto => ({
  texto,
  fonte: 'classico',
  fundo: 'caixa_branca',
  tamanho: 62,
  cor: '#000000',
  x: 0.5,
  y: 0.2,
  largura: 820,
})

function quebrarLinhas(ctx: CanvasRenderingContext2D, texto: string, largura: number): string[] {
  const linhas: string[] = []
  for (const paragrafo of texto.split('\n')) {
    let atual = ''
    for (const palavra of paragrafo.split(/\s+/).filter(Boolean)) {
      const teste = atual ? `${atual} ${palavra}` : palavra
      if (ctx.measureText(teste).width <= largura || !atual) atual = teste
      else {
        linhas.push(atual)
        atual = palavra
      }
    }
    linhas.push(atual)
  }
  return linhas.filter((l, _i, todas) => l || todas.length === 1)
}

function caixaArredondada(ctx: CanvasRenderingContext2D, x: number, y: number, l: number, a: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + l, y, x + l, y + a, r)
  ctx.arcTo(x + l, y + a, x, y + a, r)
  ctx.arcTo(x, y + a, x, y, r)
  ctx.arcTo(x, y, x + l, y, r)
  ctx.closePath()
  ctx.fill()
}

// Desenha o texto; devolve o retângulo ocupado (para arrastar e para pedir a posição automática)
export function desenharTexto(ctx: CanvasRenderingContext2D, c: ConfigTexto) {
  ctx.save()
  ctx.font = FONTES[c.fonte].css(c.tamanho)
  ctx.textBaseline = 'top'
  ctx.textAlign = 'center'
  const linhas = quebrarLinhas(ctx, c.texto, c.largura)
  const entrelinha = Math.round(c.tamanho * 1.28)
  const cx = c.x * LARGURA
  const topo = c.y * ALTURA
  const padX = Math.round(c.tamanho * 0.38)
  const padY = Math.round(c.tamanho * 0.14)
  let maior = 0
  linhas.forEach((linha, i) => {
    const w = ctx.measureText(linha).width
    maior = Math.max(maior, w)
    const y = topo + i * entrelinha
    if (c.fundo.startsWith('caixa') && linha) {
      ctx.fillStyle = c.fundo === 'caixa_branca' ? '#ffffff' : c.fundo === 'caixa_preta' ? '#000000' : 'rgba(0,0,0,0.55)'
      caixaArredondada(ctx, cx - w / 2 - padX, y - padY, w + padX * 2, entrelinha - padY * 0.2, c.tamanho * 0.22)
    }
  })
  const clara = parseInt(c.cor.replace('#', '').slice(0, 2), 16) + parseInt(c.cor.replace('#', '').slice(2, 4), 16) + parseInt(c.cor.replace('#', '').slice(4, 6), 16) > 380
  linhas.forEach((linha, i) => {
    const y = topo + i * entrelinha
    if (c.fundo === 'sombra') {
      ctx.shadowColor = clara ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.75)'
      ctx.shadowBlur = c.tamanho * 0.3
      ctx.shadowOffsetY = 3
    }
    if (c.fundo === 'contorno') {
      ctx.lineWidth = Math.max(4, c.tamanho * 0.12)
      ctx.lineJoin = 'round'
      ctx.strokeStyle = clara ? '#000000' : '#ffffff'
      ctx.strokeText(linha, cx, y)
    }
    ctx.fillStyle = c.cor
    ctx.fillText(linha, cx, y)
    ctx.shadowColor = 'transparent'
  })
  ctx.restore()
  const altura = linhas.length * entrelinha
  return { x: cx - maior / 2 - padX, y: topo - padY, largura: maior + padX * 2, altura: altura + padY * 2 }
}

interface Props {
  item: ItemHistorico
  textoInicial: string
  sugestoes: string[]
  onFechar: () => void
  onAplicado: (avaliacao: Avaliacao) => void
}

export default function EditorTexto({ item, textoInicial, sugestoes, onFechar, onAplicado }: Props) {
  const [c, setC] = useState<ConfigTexto>(() =>
    textoInicial
      ? { ...((item.avaliacao?.video_texto?.config as unknown as ConfigTexto | undefined) ?? configPadrao()), texto: textoInicial }
      : ((item.avaliacao?.video_texto?.config as unknown as ConfigTexto | undefined) ?? configPadrao()),
  )
  const [zonas, setZonas] = useState(true)
  const [ocupado, setOcupado] = useState('')
  const [erro, setErro] = useState('')
  const [porque, setPorque] = useState('')
  const canvas = useRef<HTMLCanvasElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const arrasto = useRef<{ dx: number; dy: number } | null>(null)
  const caixa = useRef({ x: 0, y: 0, largura: 0, altura: 0 })
  const arquivo = item.arquivo_1080 || item.arquivo

  const mudar = (parcial: Partial<ConfigTexto>) => setC((atual) => ({ ...atual, ...parcial }))

  // Redesenha a prévia sempre que algo muda (e quando a fonte do sistema termina de carregar)
  const redesenhar = useCallback(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, LARGURA, ALTURA)
    if (zonas) {
      ctx.fillStyle = 'rgba(254,44,85,0.14)'
      ZONAS.forEach(([x, y, l, a]) => ctx.fillRect(x, y, l, a))
    }
    caixa.current = desenharTexto(ctx, c)
    ctx.strokeStyle = 'rgba(254,44,85,0.7)'
    ctx.setLineDash([12, 10])
    ctx.lineWidth = 3
    ctx.strokeRect(caixa.current.x, caixa.current.y, caixa.current.largura, caixa.current.altura)
    ctx.setLineDash([])
  }, [c, zonas])

  useEffect(() => {
    redesenhar()
    void document.fonts.load(FONTES[c.fonte].css(c.tamanho)).then(redesenhar)
  }, [redesenhar, c.fonte, c.tamanho])

  function ponto(e: PointerEvent<HTMLCanvasElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    return { x: ((e.clientX - r.left) / r.width) * LARGURA, y: ((e.clientY - r.top) / r.height) * ALTURA }
  }

  function aoPressionar(e: PointerEvent<HTMLCanvasElement>) {
    const p = ponto(e)
    e.currentTarget.setPointerCapture(e.pointerId)
    arrasto.current = { dx: p.x - c.x * LARGURA, dy: p.y - c.y * ALTURA }
  }

  function aoMover(e: PointerEvent<HTMLCanvasElement>) {
    if (!arrasto.current) return
    const p = ponto(e)
    mudar({
      x: Math.min(0.95, Math.max(0.05, (p.x - arrasto.current.dx) / LARGURA)),
      y: Math.min(0.92, Math.max(0.02, (p.y - arrasto.current.dy) / ALTURA)),
    })
  }

  async function executar(rotulo: string, acao: () => Promise<void>) {
    setErro('')
    setOcupado(rotulo)
    try {
      await acao()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Algo deu errado')
    } finally {
      setOcupado('')
    }
  }

  const sugerirIa = () =>
    executar('ia', async () => {
      const s = await api.sugerirTextoTela(item.prediction_id, c.texto)
      const fundo = s.fundo as FundoTexto
      mudar({
        texto: s.texto,
        fonte: s.fonte as FonteTexto,
        fundo,
        tamanho: s.tamanho,
        x: s.x,
        y: s.y,
        cor: s.cor || FUNDOS.find((f) => f.id === fundo)?.cor || '#ffffff',
      })
      setPorque(s.porque_pt)
    })

  const posicaoAutomatica = () =>
    executar('posicao', async () => {
      const r = await api.posicaoTexto(item.prediction_id, Math.round(caixa.current.altura), Math.round(Math.max(300, caixa.current.largura)))
      mudar({ x: r.x, y: r.y, ...(['nenhum', 'sombra', 'contorno'].includes(c.fundo) ? { cor: r.cor } : {}) })
    })

  const aplicar = () =>
    executar('aplicar', async () => {
      const tela = document.createElement('canvas')
      tela.width = LARGURA
      tela.height = ALTURA
      const ctx = tela.getContext('2d')
      if (!ctx) throw new Error('Seu navegador não conseguiu desenhar o texto.')
      await document.fonts.load(FONTES[c.fonte].css(c.tamanho))
      desenharTexto(ctx, c)
      const r = await api.camadaTexto(item.prediction_id, tela.toDataURL('image/png'), c.texto, c)
      onAplicado(r.avaliacao)
      onFechar()
    })

  const botao = 'rounded-lg border px-2.5 py-1.5 text-xs transition'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3" role="dialog" aria-modal="true">
      <div className="grid max-h-[96vh] w-full max-w-5xl gap-4 overflow-auto rounded-2xl bg-white p-4 md:grid-cols-[minmax(260px,380px)_1fr]">
        <div className="space-y-2">
          <div className="relative mx-auto aspect-[9/16] w-full max-w-[380px] overflow-hidden rounded-xl bg-black">
            <video ref={video} src={`/saida/${encodeURIComponent(arquivo)}`} muted loop playsInline preload="auto" className="absolute inset-0 h-full w-full" />
            <canvas
              ref={canvas}
              width={LARGURA}
              height={ALTURA}
              onPointerDown={aoPressionar}
              onPointerMove={aoMover}
              onPointerUp={() => (arrasto.current = null)}
              className="absolute inset-0 h-full w-full cursor-move touch-none"
            />
          </div>
          <div className="flex items-center justify-center gap-3 text-xs text-slate-600">
            <button type="button" onClick={() => (video.current?.paused ? void video.current.play() : video.current?.pause())} className={`${botao} border-slate-300`}>
              ▶︎ / ❚❚
            </button>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={zonas} onChange={(e) => setZonas(e.target.checked)} className="accent-rose-600" />
              Mostrar zonas que o TikTok cobre
            </label>
          </div>
          <p className="text-center text-[11px] text-slate-500">Arraste o texto na prévia para posicionar.</p>
        </div>

        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg font-semibold text-slate-900">Texto na tela</h2>
            <button type="button" onClick={onFechar} className="text-slate-400 hover:text-slate-800" aria-label="Fechar">
              ✕
            </button>
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void sugerirIa()} disabled={Boolean(ocupado)} className="rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300">
              {ocupado === 'ia' ? 'A IA está pensando (10 a 40s)...' : c.texto.trim() ? '🧠 IA: estilo e posição para este texto' : '🧠 IA: sugerir texto, estilo e posição'}
            </button>
            <button type="button" onClick={() => void posicaoAutomatica()} disabled={Boolean(ocupado)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:border-slate-500 disabled:opacity-50">
              {ocupado === 'posicao' ? 'Analisando o vídeo...' : '📍 Posição automática'}
            </button>
          </div>
          {porque && <p className="rounded-lg bg-sky-50 p-2 text-xs text-sky-900">{porque}</p>}

          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-700">Texto (Enter quebra a linha)</span>
            <textarea rows={3} value={c.texto} onChange={(e) => mudar({ texto: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-rose-500" />
          </label>
          {sugestoes.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {sugestoes.map((s) => (
                <button key={s} type="button" onClick={() => mudar({ texto: s })} className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:border-rose-400">
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="space-y-1">
            <span className="text-xs font-medium text-slate-700">Fonte</span>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(FONTES) as FonteTexto[]).map((f) => (
                <button key={f} type="button" onClick={() => mudar({ fonte: f })} className={`${botao} ${c.fonte === f ? 'border-rose-500 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-700'}`}>
                  {FONTES[f].nome}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <span className="text-xs font-medium text-slate-700">Estilo</span>
            <div className="flex flex-wrap gap-1.5">
              {FUNDOS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => mudar({ fundo: f.id, ...(f.cor ? { cor: f.cor } : {}) })}
                  className={`${botao} ${c.fundo === f.id ? 'border-rose-500 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-700'}`}
                >
                  {f.nome}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1">
            <span className="text-xs font-medium text-slate-700">Cor da letra</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {CORES.map((cor) => (
                <button
                  key={cor}
                  type="button"
                  onClick={() => mudar({ cor })}
                  aria-label={`Cor ${cor}`}
                  className={`h-7 w-7 rounded-full border-2 ${c.cor === cor ? 'border-rose-500' : 'border-slate-200'} ${COR_CLASSE[cor]}`}
                />
              ))}
              <input type="color" value={c.cor} onChange={(e) => mudar({ cor: e.target.value })} className="h-7 w-10 cursor-pointer rounded border border-slate-200" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs text-slate-700">
            <label className="space-y-1">
              <span className="font-medium">Tamanho: {c.tamanho}</span>
              <input type="range" min={36} max={110} value={c.tamanho} onChange={(e) => mudar({ tamanho: Number(e.target.value) })} className="w-full accent-rose-600" />
            </label>
            <label className="space-y-1">
              <span className="font-medium">Largura do bloco: {c.largura}</span>
              <input type="range" min={360} max={960} step={20} value={c.largura} onChange={(e) => mudar({ largura: Number(e.target.value) })} className="w-full accent-rose-600" />
            </label>
          </div>

          {erro && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{erro}</p>}
          <div className="flex gap-2 border-t border-slate-100 pt-3">
            <button type="button" onClick={() => void aplicar()} disabled={Boolean(ocupado) || !c.texto.trim()} className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300">
              {ocupado === 'aplicar' ? 'Aplicando no vídeo (5 a 20s)...' : 'Aplicar no vídeo'}
            </button>
            <button type="button" onClick={onFechar} className="rounded-lg px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-100">
              Cancelar
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Classes fixas das bolinhas de cor (Tailwind precisa das classes escritas por extenso)
const COR_CLASSE: Record<string, string> = {
  '#ffffff': 'bg-white',
  '#000000': 'bg-black',
  '#221e1c': 'bg-stone-900',
  '#f5ead6': 'bg-amber-50',
  '#fe2c55': 'bg-rose-500',
  '#25f4ee': 'bg-cyan-300',
  '#ffd60a': 'bg-yellow-400',
  '#e8b4b8': 'bg-rose-200',
}
