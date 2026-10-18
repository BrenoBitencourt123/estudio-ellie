import EscolhaMotor from '@/components/EscolhaMotor'
import PassoCena from '@/components/PassoCena'
import PassoFinal from '@/components/PassoFinal'
import PassoIdentidade from '@/components/PassoIdentidade'
import PassoMovimento from '@/components/PassoMovimento'
import PassoReferencias from '@/components/PassoReferencias'
import Receitas from '@/components/Receitas'
import { useRevisao } from '@/hooks/useRevisao'
import { ehKling, formatarBrl, formatarUsd, problemaDoEstado } from '@/lib/estudioUtil'
import type { Aprendizado, EstadoEstudio, Modo, PropsPasso, Receitas as TipoReceitas } from '@/types'

interface Props extends PropsPasso {
  setEstado: (e: EstadoEstudio) => void
  passo: number
  setPasso: (p: number) => void
  receitas: TipoReceitas
  recarregarReceitas: () => Promise<void>
  aprendizado: Aprendizado | null
  onGerado: () => void
}

type ModoAtivo = Exclude<Modo, ''>

const CAMINHOS: { modo: ModoAtivo; titulo: string; texto: string; icone: string }[] = [
  {
    modo: 'movimento',
    titulo: 'Ellie copiando um vídeo',
    texto: 'Você tem um vídeo (seu ou de referência) e quer a Ellie fazendo o mesmo movimento.',
    icone: '🎬',
  },
  {
    modo: 'fotos',
    titulo: 'Ellie a partir das fotos',
    texto: 'Sem vídeo de referência: a Ellie, uma roupa e um lugar, e você descreve a cena.',
    icone: '📸',
  },
  {
    modo: 'lugar',
    titulo: 'Lugar do UK',
    texto: 'Um clipe de um lugar (a partir de uma foto) para os edits de lugar.',
    icone: '🏰',
  },
]

const PASSOS: Record<ModoAtivo, { id: string; nome: string }[]> = {
  movimento: [
    { id: 'movimento', nome: 'Vídeo de referência' },
    { id: 'ellie', nome: 'Ellie' },
    { id: 'cena', nome: 'Cena' },
    { id: 'final', nome: 'Gerar' },
  ],
  fotos: [
    { id: 'ellie', nome: 'Ellie' },
    { id: 'roupa', nome: 'Roupa e lugar' },
    { id: 'cena', nome: 'Cena' },
    { id: 'final', nome: 'Gerar' },
  ],
  lugar: [
    { id: 'ellie', nome: 'Foto do lugar' },
    { id: 'movimento', nome: 'Câmera (opcional)' },
    { id: 'cena', nome: 'Câmera e clima' },
    { id: 'final', nome: 'Gerar' },
  ],
}

export const ultimoPasso = (modo: Modo) => (modo ? PASSOS[modo].length - 1 : 0)

// Criar um vídeo: escolhe o caminho e segue passos que se adaptam a ele
export default function Criar(props: Props) {
  const { estado, mudar, setEstado, config, passo, setPasso, receitas, recarregarReceitas, aprendizado, onGerado } = props
  const revisao = useRevisao(estado)
  const problema = problemaDoEstado(estado, config)

  function escolherCaminho(modo: ModoAtivo) {
    // Lugar e "a partir das fotos" usam só o Seedance
    const seedance = ehKling(estado.modelo) && modo !== 'movimento' ? { modelo: '2.0-fast', resolucao: '720p' as const } : {}
    mudar({
      modo,
      tipo: modo === 'lugar' ? 'lugar' : 'ellie',
      ...(modo === 'fotos' ? { movimento: null } : {}),
      ...seedance,
      promptManual: null,
    })
    setPasso(0)
  }

  if (!estado.modo) {
    return (
      <div className="space-y-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">O que vamos criar?</h1>
          <p className="mt-1 text-slate-600">Escolha o caminho. Os passos se ajustam a ele.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {CAMINHOS.map((c) => (
            <button
              key={c.modo}
              type="button"
              onClick={() => escolherCaminho(c.modo)}
              className="rounded-2xl border-2 border-slate-200 bg-white p-6 text-left transition hover:border-rose-400 hover:shadow-sm"
            >
              <div className="text-3xl">{c.icone}</div>
              <div className="mt-3 text-lg font-semibold text-slate-900">{c.titulo}</div>
              <p className="mt-1 text-sm text-slate-600">{c.texto}</p>
            </button>
          ))}
        </div>
        {Object.keys(receitas).length > 0 && (
          <div className="max-w-sm">
            <Receitas receitas={receitas} estado={estado} onCarregar={(e) => setEstado(e)} onMudou={recarregarReceitas} />
          </div>
        )}
      </div>
    )
  }

  const passos = PASSOS[estado.modo]
  const atual = passos[Math.min(passo, passos.length - 1)]
  const caminho = CAMINHOS.find((c) => c.modo === estado.modo)!
  const kling = ehKling(estado.modelo)

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <span className="text-xl">{caminho.icone}</span>
            <span className="font-semibold text-slate-900">{caminho.titulo}</span>
            <button type="button" onClick={() => mudar({ modo: '' })} className="ml-2 text-rose-600 underline">
              trocar
            </button>
          </div>
          <nav className="flex gap-1 overflow-x-auto">
            {passos.map((p, i) => (
              <button
                key={p.id + i}
                type="button"
                onClick={() => setPasso(i)}
                className={`shrink-0 rounded-full px-3 py-1.5 text-sm transition ${
                  i === passo ? 'bg-rose-600 font-semibold text-white' : 'bg-white text-slate-600 hover:bg-slate-100'
                }`}
              >
                {i + 1}. {p.nome}
              </button>
            ))}
          </nav>
        </div>

        <main className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
          {atual.id === 'movimento' && <PassoMovimento {...props} />}
          {atual.id === 'ellie' && (
            <div className="space-y-8">
              {estado.modo === 'movimento' && <EscolhaMotor estado={estado} mudar={mudar} aprendizado={aprendizado} />}
              <PassoIdentidade {...props} />
              {estado.modo === 'movimento' && !kling && <PassoReferencias {...props} />}
            </div>
          )}
          {atual.id === 'roupa' && <PassoReferencias {...props} />}
          {atual.id === 'cena' && <PassoCena {...props} />}
          {atual.id === 'final' && <PassoFinal {...props} {...revisao} problema={problema} onGerado={onGerado} />}

          {atual.id !== 'final' && (
            <footer className="mt-8 flex justify-between border-t border-slate-100 pt-4">
              <button
                type="button"
                onClick={() => setPasso(Math.max(0, passo - 1))}
                disabled={passo === 0}
                className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-30"
              >
                ← Voltar
              </button>
              <button
                type="button"
                onClick={() => setPasso(Math.min(passos.length - 1, passo + 1))}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white"
              >
                Próximo →
              </button>
            </footer>
          )}
        </main>
      </div>

      <aside className="space-y-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm">
          <div className="font-semibold text-slate-800">Resumo</div>
          <ul className="mt-2 space-y-1 text-slate-600">
            {estado.modo === 'lugar' ? (
              <li>Lugar: {estado.cenario ?? '—'}</li>
            ) : kling ? (
              <li>Imagem base: {estado.imagemBase ?? '—'}</li>
            ) : (
              <>
                <li>{estado.persona.length} foto(s) da Ellie</li>
                <li>Peça: {estado.peca ?? '—'}</li>
                <li>Cenário: {estado.cenario ?? '—'}</li>
              </>
            )}
            <li>Vídeo: {estado.movimento ?? '—'}</li>
            <li>
              {kling ? estado.modelo.replace('kling-', 'Kling ') : `Seedance ${estado.modelo} · ${estado.resolucao}`} · {estado.duracao}s
            </li>
            <li className="pt-1 font-medium text-slate-900">
              {revisao.estimativa
                ? `${formatarUsd(revisao.estimativa.custo_usd)} (${formatarBrl(revisao.estimativa.custo_brl)})`
                : 'Custo: —'}
            </li>
          </ul>
          {problema && <p className="mt-2 text-xs text-amber-700">Falta: {problema}</p>}
        </div>
        <Receitas
          receitas={receitas}
          estado={estado}
          onCarregar={(e) => {
            setEstado(e)
            setPasso(ultimoPasso(e.modo))
          }}
          onMudou={recarregarReceitas}
        />
      </aside>
    </div>
  )
}
