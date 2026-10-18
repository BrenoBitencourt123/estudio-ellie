import SeletorAsset from '@/components/SeletorAsset'
import type { Assets, Pasta } from '@/types'

interface Props {
  assets: Assets
  recarregarAssets: () => Promise<void>
}

const PASTAS: { pasta: Pasta; titulo: string; dica: string }[] = [
  { pasta: 'persona', titulo: 'Fotos da Ellie', dica: 'Rosto e corpo de referência (Seedance). Use 2 bem consistentes por vídeo.' },
  { pasta: 'pecas', titulo: 'Peças', dica: 'Roupa sozinha, fundo limpo, sem pessoa.' },
  { pasta: 'cenarios', titulo: 'Cenários', dica: 'O lugar vazio, vertical, luz natural.' },
  { pasta: 'base', titulo: 'Imagens base (Kling)', dica: 'A Ellie já vestida e no lugar, com o enquadramento do vídeo de referência.' },
  { pasta: 'movimentos', titulo: 'Vídeos de referência', dica: 'Movimentos para copiar. Para o Kling, cabeça e tronco precisam aparecer.' },
]

// Todas as mídias num lugar só, com subir e ✨ criar com IA em cada pasta
export default function Biblioteca({ assets, recarregarAssets }: Props) {
  return (
    <div className="space-y-6">
      {PASTAS.map((p) => (
        <section key={p.pasta} className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {p.titulo} <span className="text-sm font-normal text-slate-500">({assets[p.pasta].length})</span>
            </h2>
            <p className="text-sm text-slate-600">{p.dica}</p>
          </div>
          <SeletorAsset
            pasta={p.pasta}
            itens={assets[p.pasta]}
            selecionados={[]}
            onMudar={() => undefined}
            onEnviado={() => recarregarAssets()}
            videos={assets.movimentos}
          />
        </section>
      ))}
    </div>
  )
}
