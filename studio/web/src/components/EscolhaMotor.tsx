import { ehKling } from '@/lib/estudioUtil'
import type { Aprendizado, EstadoEstudio } from '@/types'

interface Props {
  estado: EstadoEstudio
  mudar: (parcial: Partial<EstadoEstudio>) => void
  aprendizado: Aprendizado | null
}

// No caminho "Ellie copiando um vídeo": Seedance (várias fotos) ou Kling (1 imagem base, movimento mais fiel)
export default function EscolhaMotor({ estado, mudar, aprendizado }: Props) {
  const kling = ehKling(estado.modelo)
  const rejeitado = aprendizado?.rejeicoes_kling.find((r) => r.movimento === estado.movimento)

  const opcoes = [
    {
      ativo: !kling,
      titulo: 'Seedance',
      texto: 'Usa as fotos de rosto + peça + cenário. Aceita vídeo de referência sem cabeça. Mais barato para testar.',
      aoClicar: () => mudar({ modelo: '2.0-fast', resolucao: '720p', promptManual: null }),
    },
    {
      ativo: kling,
      titulo: 'Kling',
      texto: 'Copia o movimento com mais fidelidade. Usa 1 imagem base (Ellie já vestida). O vídeo precisa mostrar cabeça e tronco.',
      aoClicar: () => mudar({ modelo: 'kling-2.6-std', promptManual: null }),
    },
  ]

  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">Como gerar</div>
      <div className="grid gap-3 sm:grid-cols-2">
        {opcoes.map((o) => (
          <button
            key={o.titulo}
            type="button"
            onClick={o.aoClicar}
            className={`rounded-xl border-2 p-3 text-left transition ${
              o.ativo ? 'border-rose-500 bg-rose-50' : 'border-slate-200 bg-white hover:border-slate-400'
            }`}
          >
            <div className="font-semibold text-slate-900">{o.titulo}</div>
            <div className="mt-1 text-xs text-slate-600">{o.texto}</div>
          </button>
        ))}
      </div>
      {rejeitado && (
        <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-800">
          O Kling já rejeitou este vídeo de referência {rejeitado.vezes}x. {kling ? 'Use o Seedance ou outro vídeo.' : 'No Seedance ele funciona.'}
        </p>
      )}
    </div>
  )
}
