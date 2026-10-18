import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import type { Assets, Pasta } from '@/types'

interface Props {
  assets: Assets
  recarregarAssets: () => Promise<void>
  onCriado: (projetoId: string) => void
}

type Espaco = 'movimento' | 'roupa' | 'cenario'

// Converte a imagem colada (data URL) em arquivo para subir como está
async function dataUrlParaArquivo(dataUrl: string, nome: string): Promise<File> {
  const blob = await (await fetch(dataUrl)).blob()
  return new File([blob], nome, { type: blob.type || 'image/png' })
}

function lerComoDataUrl(arquivo: File): Promise<string> {
  return new Promise((ok, falha) => {
    const leitor = new FileReader()
    leitor.onload = () => ok(String(leitor.result))
    leitor.onerror = () => falha(new Error('Não consegui ler a imagem'))
    leitor.readAsDataURL(arquivo)
  })
}

const ETAPAS_PROGRESSO: [number, string][] = [
  [0, 'Criando o projeto...'],
  [4, 'A IA está escrevendo o gancho e a legenda...'],
  [28, 'A IA está estudando o vídeo e montando o plano...'],
  [90, 'Quase lá, conferindo as mídias...'],
]

const botaoAcao = 'rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 hover:border-rose-400 disabled:opacity-50'

function Vazio({ texto }: { texto: string }) {
  return <p className="px-6 text-center text-sm text-slate-400">{texto}</p>
}

interface PropsCartao {
  espaco: Espaco
  titulo: string
  opcional?: boolean
  ativo: boolean
  selecionado: ReactNode
  children: ReactNode
  onAtivar: () => void
  onSoltar: (arquivos: File[]) => void
}

function Cartao({ titulo, opcional, ativo, selecionado, children, onAtivar, onSoltar }: PropsCartao) {
  return (
    <section
      onClick={onAtivar}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        onSoltar(Array.from(e.dataTransfer.files))
      }}
      className={`flex flex-col gap-3 rounded-2xl border-2 bg-white p-4 transition ${ativo ? 'border-rose-400 shadow-sm' : 'border-slate-200'}`}
    >
      <header className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-900">{titulo}</h2>
        {opcional && <span className="text-xs text-slate-400">opcional</span>}
      </header>
      <div className="flex h-48 items-center justify-center overflow-hidden rounded-xl bg-slate-100">{selecionado}</div>
      {children}
    </section>
  )
}

function Faixa({ pasta, itens, atual, onEscolher }: { pasta: Pasta; itens: string[]; atual: string | null; onEscolher: (n: string | null) => void }) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {itens.map((n) => (
        <button
          key={n}
          type="button"
          title={n}
          onClick={() => onEscolher(atual === n ? null : n)}
          className={`h-20 w-14 shrink-0 overflow-hidden rounded-lg border-2 ${atual === n ? 'border-rose-500' : 'border-transparent hover:border-slate-300'}`}
        >
          {pasta === 'movimentos' ? (
            <video src={`/files/${pasta}/${encodeURIComponent(n)}#t=1`} muted preload="metadata" className="h-full w-full object-cover" />
          ) : (
            <img src={`/files/${pasta}/${encodeURIComponent(n)}`} alt={n} loading="lazy" className="h-full w-full object-cover" />
          )}
        </button>
      ))}
    </div>
  )
}

interface PropsColada {
  srcs: string[]
  lugar: boolean
  ocupado: string
  onUsar: (modo: 'look' | 'peca' | 'como-esta') => void
  onDescartar: () => void
}

function PainelColada({ srcs, lugar, ocupado, onUsar, onDescartar }: PropsColada) {
  const principal = 'rounded-lg bg-rose-600 px-2.5 py-1.5 text-xs font-semibold text-white disabled:bg-slate-300'
  return (
    <div className="space-y-2 rounded-xl border border-rose-200 bg-rose-50/60 p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {srcs.map((src, i) => (
          <img key={i} src={src} alt={`Referência ${i + 1}`} className="h-16 w-12 rounded-md object-cover" />
        ))}
        <p className="text-xs text-slate-700">
          {srcs.length > 1 ? `${srcs.length} referências: a IA junta tudo num look só.` : 'Imagem colada.'} Cole mais com Ctrl+V (até 4).
        </p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {lugar ? (
          <button type="button" onClick={() => onUsar('peca')} disabled={Boolean(ocupado)} className={principal}>
            {ocupado === 'colada-peca' ? 'Limpando (cerca de 1 min)...' : '✨ Deixar só o lugar (IA)'}
          </button>
        ) : (
          <>
            <button type="button" onClick={() => onUsar('look')} disabled={Boolean(ocupado)} className={principal}>
              {ocupado === 'colada-look' ? 'Montando o look (cerca de 1 min)...' : '✨ Look completo (todas as peças)'}
            </button>
            <button type="button" onClick={() => onUsar('peca')} disabled={Boolean(ocupado)} className={botaoAcao}>
              {ocupado === 'colada-peca' ? 'Recriando (cerca de 1 min)...' : '✨ Só a peça principal'}
            </button>
          </>
        )}
        {srcs.length === 1 && (
          <button type="button" onClick={() => onUsar('como-esta')} disabled={Boolean(ocupado)} className={botaoAcao}>
            Usar como está
          </button>
        )}
        <button type="button" onClick={onDescartar} className="px-1 text-xs text-slate-400">
          descartar
        </button>
      </div>
    </div>
  )
}

// Tela principal: vídeo de referência + roupa (+ cenário) e um botão. O resto a IA resolve.
export default function NovoVideo({ assets, recarregarAssets, onCriado }: Props) {
  const [movimento, setMovimento] = useState<string | null>(null)
  const [peca, setPeca] = useState<string | null>(null)
  const [cenario, setCenario] = useState<string | null>(null)
  const [ideia, setIdeia] = useState('')
  const [semRosto, setSemRosto] = useState(true)
  const [ativo, setAtivo] = useState<Espaco>('roupa')
  // Imagens coladas no espaço ativo (até 4): várias referências viram um look só
  const [colada, setColada] = useState<{ espaco: Espaco; srcs: string[] } | null>(null)
  const [ocupado, setOcupado] = useState('')
  const [erro, setErro] = useState('')
  const [segundos, setSegundos] = useState(0)
  const entradaVideo = useRef<HTMLInputElement>(null)

  // Ctrl+V com imagem cola no espaço ativo (roupa por padrão)
  useEffect(() => {
    const aoColar = (e: ClipboardEvent) => {
      const imagem = Array.from(e.clipboardData?.files ?? []).find((a) => a.type.startsWith('image/'))
      if (!imagem || ativo === 'movimento') return
      e.preventDefault()
      void lerComoDataUrl(imagem).then((src) => adicionarColada(ativo, src))
    }
    window.addEventListener('paste', aoColar)
    return () => window.removeEventListener('paste', aoColar)
  }, [ativo])

  // Contador para mostrar em que parte a montagem está
  useEffect(() => {
    if (ocupado !== 'montar') return
    setSegundos(0)
    const timer = setInterval(() => setSegundos((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [ocupado])

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

  function adicionarColada(espaco: Espaco, src: string) {
    setColada((atual) =>
      atual && atual.espaco === espaco ? { espaco, srcs: [...atual.srcs, src].slice(0, 4) } : { espaco, srcs: [src] },
    )
  }

  const definir = (espaco: Espaco, nome: string) =>
    espaco === 'movimento' ? setMovimento(nome) : espaco === 'roupa' ? setPeca(nome) : setCenario(nome)
  const pastaDo = (espaco: Espaco): Pasta => (espaco === 'movimento' ? 'movimentos' : espaco === 'roupa' ? 'pecas' : 'cenarios')

  const usarColada = (modo: 'look' | 'peca' | 'como-esta') =>
    colada &&
    executar(`colada-${modo}`, async () => {
      const pasta = pastaDo(colada.espaco)
      const { nome } =
        modo === 'como-esta'
          ? await api.enviarArquivo(pasta, await dataUrlParaArquivo(colada.srcs[0], `colada_${Date.now()}.png`))
          : await api.gerarMidia(pasta, '', false, colada.srcs, modo)
      await recarregarAssets()
      definir(colada.espaco, nome)
      setColada(null)
    })

  const doVideo = (espaco: 'roupa' | 'cenario') =>
    movimento &&
    executar(`dovideo-${espaco}`, async () => {
      const { nome } = await api.midiaDoVideo(movimento, pastaDo(espaco), '')
      await recarregarAssets()
      definir(espaco, nome)
    })

  async function soltar(espaco: Espaco, arquivos: File[]) {
    setAtivo(espaco)
    if (espaco === 'movimento') {
      const video = arquivos.find((a) => a.type.startsWith('video/'))
      if (video) await executar('subir-video', async () => {
        const { nome } = await api.enviarArquivo('movimentos', video)
        await recarregarAssets()
        setMovimento(nome)
      })
      return
    }
    const imagem = arquivos.find((a) => a.type.startsWith('image/'))
    if (imagem) adicionarColada(espaco, await lerComoDataUrl(imagem))
  }

  const montar = () =>
    executar('montar', async () => {
      const projeto = await api.videoRapido({ movimento, peca, cenario, ideia, sem_rosto: semRosto })
      onCriado(projeto.id)
    })

  const progresso = [...ETAPAS_PROGRESSO].reverse().find(([s]) => segundos >= s)?.[1] ?? ''





  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Novo vídeo</h1>
        <p className="text-sm text-slate-600">
          Escolha o movimento, a roupa e, se quiser, o cenário. Para usar um print, clique no espaço e aperte <kbd className="rounded border border-slate-300 px-1">Ctrl</kbd>+
          <kbd className="rounded border border-slate-300 px-1">V</kbd>, ou arraste o arquivo.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Cartao
          espaco="movimento"
          ativo={ativo === 'movimento'}
          onAtivar={() => setAtivo('movimento')}
          onSoltar={(arquivos) => void soltar('movimento', arquivos)}
          titulo="🎬 Movimento"
          selecionado={
            movimento ? (
              <video src={`/files/movimentos/${encodeURIComponent(movimento)}`} muted loop autoPlay playsInline className="h-full w-full object-cover" />
            ) : (
              <Vazio texto='O vídeo que a Ellie vai copiar' />
            )
          }
        >
          <Faixa pasta="movimentos" itens={assets.movimentos} atual={movimento} onEscolher={setMovimento} />
          <div className="flex flex-wrap gap-1.5">
            <button type="button" onClick={() => entradaVideo.current?.click()} disabled={Boolean(ocupado)} className={botaoAcao}>
              {ocupado === 'subir-video' ? 'Enviando...' : '＋ Subir vídeo'}
            </button>
          </div>
          <input
            ref={entradaVideo}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => {
              void soltar('movimento', Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
        </Cartao>

        <Cartao
          espaco="roupa"
          ativo={ativo === 'roupa'}
          onAtivar={() => setAtivo('roupa')}
          onSoltar={(arquivos) => void soltar('roupa', arquivos)}
          titulo="👗 Roupa"
          selecionado={peca ? <img src={`/files/pecas/${encodeURIComponent(peca)}`} alt={peca} className="h-full w-full object-contain" /> : <Vazio texto='Cole um print (Ctrl+V), escolha abaixo ou pegue do vídeo' />}
        >
          <Faixa pasta="pecas" itens={assets.pecas} atual={peca} onEscolher={setPeca} />
          {colada?.espaco === 'roupa' && (
            <PainelColada
              srcs={colada.srcs}
              lugar={false}
              ocupado={ocupado}
              onUsar={(modo) => void usarColada(modo)}
              onDescartar={() => setColada(null)}
            />
          )}
          <div className="flex flex-wrap gap-1.5">
            <button type="button" onClick={() => void doVideo('roupa')} disabled={!movimento || Boolean(ocupado)} className={botaoAcao}>
              {ocupado === 'dovideo-roupa' ? 'Pegando a roupa (cerca de 1 min)...' : '👗 Pegar a roupa do vídeo'}
            </button>
          </div>
        </Cartao>

        <Cartao
          espaco="cenario"
          ativo={ativo === 'cenario'}
          onAtivar={() => setAtivo('cenario')}
          onSoltar={(arquivos) => void soltar('cenario', arquivos)}
          titulo="🏠 Cenário"
          opcional
          selecionado={cenario ? <img src={`/files/cenarios/${encodeURIComponent(cenario)}`} alt={cenario} className="h-full w-full object-cover" /> : <Vazio texto='Vazio: a IA escolhe o melhor' />}
        >
          <Faixa pasta="cenarios" itens={assets.cenarios} atual={cenario} onEscolher={setCenario} />
          {colada?.espaco === 'cenario' && (
            <PainelColada
              srcs={colada.srcs}
              lugar={true}
              ocupado={ocupado}
              onUsar={(modo) => void usarColada(modo)}
              onDescartar={() => setColada(null)}
            />
          )}
          <div className="flex flex-wrap gap-1.5">
            <button type="button" onClick={() => void doVideo('cenario')} disabled={!movimento || Boolean(ocupado)} className={botaoAcao}>
              {ocupado === 'dovideo-cenario' ? 'Pegando o lugar (cerca de 1 min)...' : '🏠 Usar o lugar do vídeo'}
            </button>
          </div>
        </Cartao>
      </div>

      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:flex-row md:items-end">
        <label className="block flex-1 space-y-1">
          <span className="text-sm font-medium text-slate-800">Algo a mais? (opcional)</span>
          <input
            value={ideia}
            onChange={(e) => setIdeia(e.target.value)}
            placeholder="Ex.: clima de dia frio, luz de fim de tarde, ela ajeita a alça no final"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-rose-500"
          />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
          <input type="checkbox" checked={semRosto} onChange={(e) => setSemRosto(e.target.checked)} className="accent-rose-600" />
          Sem mostrar o rosto
        </label>
        <button
          type="button"
          onClick={() => void montar()}
          disabled={Boolean(ocupado) || (!movimento && !peca && !ideia.trim())}
          className="rounded-xl bg-rose-600 px-6 py-3 text-base font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300"
        >
          {ocupado === 'montar' ? `${progresso} (${segundos}s)` : '🎬 Montar o vídeo'}
        </button>
      </div>
      {ocupado === 'montar' && (
        <p className="text-center text-xs text-slate-500">A IA escreve o gancho e a legenda e monta o plano com as suas escolhas. Leva de 1 a 2 minutos. Depois é só gerar.</p>
      )}
      {erro && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{erro}</p>}
    </div>
  )
}
