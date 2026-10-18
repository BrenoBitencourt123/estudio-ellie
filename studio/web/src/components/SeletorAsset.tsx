import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Pasta } from '@/types'

const NOMES_PASTA: Record<string, string> = {
  persona: 'foto da Ellie',
  pecas: 'peça',
  cenarios: 'cenário',
  base: 'imagem base',
}
const EXEMPLOS: Record<string, string> = {
  persona: 'Ex.: Ellie de perfil sorrindo, luz de janela, cabelo solto',
  pecas: 'Ex.: casaco de lã cor caramelo, comprido, botões dourados',
  cenarios: 'Ex.: rua de Notting Hill com casas coloridas num dia nublado de outono',
  base: 'Ex.: Ellie de corpo inteiro com trench coat bege e jeans, na frente do espelho do quarto, enquadrada do queixo para baixo',
}

// Lê uma imagem colada ou anexada e reduz para no máximo 1600px (manda menos dados para a IA)
function lerImagem(arquivo: File): Promise<string> {
  return new Promise((resolver, rejeitar) => {
    const leitor = new FileReader()
    leitor.onerror = () => rejeitar(new Error('Não consegui ler a imagem'))
    leitor.onload = () => {
      const img = new Image()
      img.onerror = () => rejeitar(new Error('Imagem inválida'))
      img.onload = () => {
        const escala = Math.min(1, 1600 / Math.max(img.width, img.height))
        const tela = document.createElement('canvas')
        tela.width = Math.round(img.width * escala)
        tela.height = Math.round(img.height * escala)
        tela.getContext('2d')?.drawImage(img, 0, 0, tela.width, tela.height)
        resolver(tela.toDataURL('image/jpeg', 0.9))
      }
      img.src = String(leitor.result)
    }
    leitor.readAsDataURL(arquivo)
  })
}

interface Props {
  pasta: Pasta
  itens: string[]
  selecionados: string[]
  multiplo?: boolean
  onMudar: (selecionados: string[]) => void
  onEnviado: (nome: string) => Promise<void> | void
  // Vídeos de referência disponíveis para "criar a partir do vídeo" (roupa, cenário ou imagem base)
  videos?: string[]
  videoPadrao?: string | null
  // Vídeo sem rosto: avisa quando uma foto escolhida da Ellie mostra o rosto
  semRosto?: boolean
}

export default function SeletorAsset({
  pasta,
  itens,
  selecionados,
  multiplo = false,
  onMudar,
  onEnviado,
  videos = [],
  videoPadrao = null,
  semRosto = false,
}: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')
  const ehVideo = pasta === 'movimentos'
  // Criar com IA: sempre disponível nas pastas de imagem, sem depender do plano
  const [criandoIa, setCriandoIa] = useState(false)
  const [painelIa, setPainelIa] = useState(false)
  const [descricao, setDescricao] = useState('')
  const [usarFotos, setUsarFotos] = useState(pasta === 'base' || pasta === 'persona')
  const aceitaVideo = pasta === 'pecas' || pasta === 'cenarios' || pasta === 'base'
  const [videoBase, setVideoBase] = useState<string>(aceitaVideo && videoPadrao ? videoPadrao : '')
  // Imagens de referência coladas (Ctrl+V), anexadas ou arrastadas
  const [coladas, setColadas] = useState<string[]>([])
  const [escopo, setEscopo] = useState<'look' | 'peca'>('look')
  const anexoRef = useRef<HTMLInputElement>(null)
  // Só nas fotos da Ellie: quais mostram o rosto
  const [rostos, setRostos] = useState<Record<string, boolean>>({})
  const [recortando, setRecortando] = useState('')

  useEffect(() => {
    if (pasta !== 'persona') return
    api
      .rostos()
      .then(setRostos)
      .catch(() => undefined)
  }, [pasta, itens.length])

  async function corrigirRosto(nome: string, rosto: boolean) {
    try {
      setRostos(await api.marcarRosto(nome, rosto))
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui salvar')
    }
  }

  async function recortar(nome: string) {
    setErro('')
    setRecortando(nome)
    try {
      const r = await api.recortarSemRosto(nome)
      setRostos(r.rostos)
      await onEnviado(r.nome)
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui recortar')
    } finally {
      setRecortando('')
    }
  }

  const comRostoEscolhidas = pasta === 'persona' && semRosto ? selecionados.filter((n) => rostos[n]) : []

  async function adicionarImagens(arquivos: File[]) {
    const imagens = arquivos.filter((a) => a.type.startsWith('image/'))
    if (!imagens.length) return
    try {
      const novas = await Promise.all(imagens.map(lerImagem))
      setColadas((atuais) => [...atuais, ...novas].slice(0, 4))
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui ler a imagem')
    }
  }

  // Com o painel aberto, Ctrl+V em qualquer lugar da página cola a imagem como referência
  useEffect(() => {
    if (!painelIa) return
    const aoColar = (e: ClipboardEvent) => {
      const arquivos = Array.from(e.clipboardData?.files ?? [])
      if (arquivos.some((a) => a.type.startsWith('image/'))) {
        e.preventDefault()
        void adicionarImagens(arquivos)
      }
    }
    window.addEventListener('paste', aoColar)
    return () => window.removeEventListener('paste', aoColar)
  }, [painelIa])

  async function criarComIa() {
    if (!descricao.trim() && !videoBase && !coladas.length) return
    setErro('')
    setCriandoIa(true)
    try {
      // Imagem colada tem prioridade sobre o vídeo: é a referência mais direta do que você quer
      const { nome } = coladas.length
        ? await api.gerarMidia(pasta, descricao, usarFotos, coladas, escopo)
        : videoBase
          ? await api.midiaDoVideo(videoBase, pasta, descricao)
          : await api.gerarMidia(pasta, descricao, usarFotos)
      await onEnviado(nome)
      setPainelIa(false)
      setDescricao('')
      setColadas([])
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'A IA não conseguiu criar a imagem')
    } finally {
      setCriandoIa(false)
    }
  }

  function alternar(nome: string) {
    if (multiplo) {
      onMudar(selecionados.includes(nome) ? selecionados.filter((n) => n !== nome) : [...selecionados, nome])
    } else {
      onMudar(selecionados.includes(nome) ? [] : [nome])
    }
  }

  async function enviar(arquivos: FileList | null) {
    if (!arquivos?.length) return
    setEnviando(true)
    setErro('')
    try {
      for (const arquivo of Array.from(arquivos)) {
        const { nome } = await api.enviarArquivo(pasta, arquivo)
        await onEnviado(nome)
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha no envio')
    } finally {
      setEnviando(false)
      if (entrada.current) entrada.current.value = ''
    }
  }

  return (
    <div>
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-5">
        {comRostoEscolhidas.length > 0 && (
          <p className="col-span-full rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
            ⚠️ O vídeo é sem rosto, mas {comRostoEscolhidas.length === 1 ? 'uma foto escolhida mostra' : 'fotos escolhidas mostram'} o
            rosto. Troque por uma "sem rosto" ou use ✂️ para criar a versão recortada.
          </p>
        )}
        {itens.map((nome) => {
          const ativo = selecionados.includes(nome)
          const url = `/files/${pasta}/${encodeURIComponent(nome)}`
          const temRosto = pasta === 'persona' ? rostos[nome] : undefined
          return (
            <div key={nome} className="relative min-w-0">
              <button
                type="button"
                onClick={() => alternar(nome)}
                className={`group relative w-full overflow-hidden rounded-xl border-2 bg-white text-left transition ${
                  ativo ? 'border-rose-500 ring-2 ring-rose-200' : 'border-slate-200 hover:border-slate-400'
                }`}
              >
                <div className="aspect-[3/4] w-full bg-slate-100">
                  {ehVideo ? (
                    <video src={url} muted preload="metadata" className="h-full w-full object-cover" />
                  ) : (
                    <img src={url} alt={nome} loading="lazy" className="h-full w-full object-cover" />
                  )}
                </div>
                <div className="truncate px-2 py-1 text-xs text-slate-600">{nome}</div>
                {ativo && (
                  <span className="absolute right-1.5 top-1.5 rounded-full bg-rose-500 px-2 py-0.5 text-xs font-semibold text-white">
                    ✓
                  </span>
                )}
              </button>
              {temRosto !== undefined && (
                <div className="absolute left-1 top-1 flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={() => void corrigirRosto(nome, !temRosto)}
                    title="Clique para corrigir se estiver errado"
                    className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${temRosto ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}`}
                  >
                    {temRosto ? 'com rosto' : 'sem rosto'}
                  </button>
                  {temRosto && (
                    <button
                      type="button"
                      onClick={() => void recortar(nome)}
                      disabled={Boolean(recortando)}
                      title="Corta logo abaixo do queixo e salva uma cópia sem rosto"
                      className="rounded-full bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-slate-700 shadow disabled:opacity-50"
                    >
                      {recortando === nome ? 'recortando...' : '✂️ versão sem rosto'}
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
        <button
          type="button"
          onClick={() => entrada.current?.click()}
          disabled={enviando}
          className="flex aspect-[3/4] flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-slate-300 text-sm text-slate-500 transition hover:border-rose-400 hover:text-rose-600 disabled:opacity-50"
        >
          <span className="text-2xl leading-none">＋</span>
          {enviando ? 'Enviando...' : ehVideo ? 'Subir vídeo' : 'Subir imagem'}
        </button>
        {!ehVideo && (
          <button
            type="button"
            onClick={() => setPainelIa(!painelIa)}
            className={`flex aspect-[3/4] flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed text-sm transition ${
              painelIa ? 'border-rose-500 bg-rose-50 text-rose-700' : 'border-rose-200 text-rose-600 hover:border-rose-400'
            }`}
          >
            <span className="text-2xl leading-none">✨</span>
            Criar com IA
          </button>
        )}
      </div>
      {painelIa && !ehVideo && (
        <div
          className="mt-3 space-y-2 rounded-xl border border-rose-200 bg-rose-50/60 p-3"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            void adicionarImagens(Array.from(e.dataTransfer.files))
          }}
        >
          <div className="text-sm font-semibold text-slate-800">Criar {NOMES_PASTA[pasta] ?? 'imagem'} com IA</div>
          <div className="space-y-1.5 rounded-lg border-2 border-dashed border-rose-200 bg-white p-2.5">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span>
                <span className="font-medium">Imagem de referência:</span> cole com{' '}
                <kbd className="rounded border border-slate-300 px-1">Ctrl</kbd>+
                <kbd className="rounded border border-slate-300 px-1">V</kbd>, arraste aqui ou
              </span>
              <button
                type="button"
                onClick={() => anexoRef.current?.click()}
                className="rounded-md border border-slate-300 px-2 py-0.5 text-slate-700 hover:border-rose-400"
              >
                📎 anexar
              </button>
            </div>
            {coladas.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {coladas.map((src, i) => (
                  <div key={i} className="relative">
                    <img src={src} alt={`Referência ${i + 1}`} className="h-20 w-16 rounded-md border border-slate-200 object-cover" />
                    <button
                      type="button"
                      onClick={() => setColadas(coladas.filter((_, j) => j !== i))}
                      className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-slate-900 text-[10px] text-white"
                      aria-label="Remover referência"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
            <input
              ref={anexoRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="hidden"
              onChange={(e) => {
                void adicionarImagens(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
            />
          </div>
          {pasta === 'pecas' && (
            <div className="flex flex-wrap gap-3 text-xs text-slate-700">
              <label className="flex items-center gap-1.5">
                <input type="radio" checked={escopo === 'look'} onChange={() => setEscopo('look')} className="accent-rose-600" />
                Look completo (todas as peças, sapato e bolsa)
              </label>
              <label className="flex items-center gap-1.5">
                <input type="radio" checked={escopo === 'peca'} onChange={() => setEscopo('peca')} className="accent-rose-600" />
                Só a peça principal
              </label>
            </div>
          )}
          {aceitaVideo && videos.length > 0 && coladas.length === 0 && (
            <label className="block space-y-1 text-xs text-slate-700">
              <span className="font-medium">Basear em</span>
              <select
                value={videoBase}
                onChange={(e) => setVideoBase(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
              >
                <option value="">Só na descrição</option>
                {videos.map((v) => (
                  <option key={v} value={v}>
                    {pasta === 'pecas' ? 'A roupa do vídeo' : pasta === 'cenarios' ? 'O lugar do vídeo' : 'A Ellie com a roupa do vídeo'}:{' '}
                    {v}
                  </option>
                ))}
              </select>
            </label>
          )}
          <textarea
            rows={3}
            value={descricao}
            onChange={(e) => setDescricao(e.target.value)}
            placeholder={
              coladas.length || videoBase
                ? 'Detalhes extras (opcional): ex. sem o salto, cor um pouco mais clara'
                : (EXEMPLOS[pasta] ?? 'Descreva a imagem')
            }
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-rose-500"
          />
          {(!videoBase || coladas.length > 0) && (
            <label className="flex items-center gap-2 text-xs text-slate-700">
              <input type="checkbox" checked={usarFotos} onChange={(e) => setUsarFotos(e.target.checked)} className="accent-rose-600" />
              Usar as fotos da Ellie como referência (para manter a mesma pessoa)
            </label>
          )}
          <button
            type="button"
            onClick={() => void criarComIa()}
            disabled={criandoIa || (!descricao.trim() && !videoBase && !coladas.length)}
            className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:bg-slate-300"
          >
            {criandoIa ? 'Criando (30s a 1,5 min)...' : '✨ Criar imagem'}
          </button>
          <p className="text-xs text-slate-500">
            Pode escrever em português. Usa a sua assinatura pelo OpenClaw e a imagem já entra nesta pasta.
          </p>
        </div>
      )}
      <input
        ref={entrada}
        type="file"
        multiple={multiplo}
        accept={ehVideo ? 'video/*' : 'image/png,image/jpeg,image/webp'}
        className="hidden"
        onChange={(e) => enviar(e.target.files)}
      />
      {erro && <p className="mt-2 text-sm text-red-600">{erro}</p>}
      {itens.length === 0 && <p className="mt-2 text-sm text-slate-500">Nada aqui ainda. Suba o primeiro arquivo.</p>}
    </div>
  )
}
