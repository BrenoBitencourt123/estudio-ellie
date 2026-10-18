import Secao from '@/components/Secao'
import SeletorAsset from '@/components/SeletorAsset'
import { ehKling } from '@/lib/estudioUtil'
import type { PropsPasso } from '@/types'

export default function PassoReferencias({ estado, mudar, assets, recarregarAssets }: PropsPasso) {
  if (estado.tipo === 'lugar') {
    return (
      <Secao titulo="Roupa e lugar" descricao="No tipo Lugar não há roupa nem pessoa. A foto do lugar já foi escolhida no passo 1.">
        <p className="rounded-xl bg-slate-100 p-4 text-sm text-slate-700">
          Foto do lugar atual: <strong>{estado.cenario ?? 'nenhuma escolhida'}</strong>
        </p>
      </Secao>
    )
  }

  if (ehKling(estado.modelo)) {
    return (
      <Secao
        titulo="Roupa e lugar"
        descricao="No Kling, a roupa e o lugar já vêm da imagem base do passo 1. Não há campos aqui. Para outra roupa ou outro cenário, escolha ou suba outra imagem base."
      >
        <p className="rounded-xl bg-slate-100 p-4 text-sm text-slate-700">
          Imagem base atual: <strong>{estado.imagemBase ?? 'nenhuma escolhida'}</strong>
        </p>
      </Secao>
    )
  }

  return (
    <Secao
      titulo="Roupa e lugar"
      descricao="Opcionais. A peça é copiada com a mesma cor, estampa e corte. O cenário trava o lugar, a luz e o clima. Foto limpa, só da roupa e sem pessoa, funciona melhor."
    >
      <div className="space-y-6">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-800">Peça de roupa (ou objeto)</h3>
          <SeletorAsset
            pasta="pecas"
            videos={assets.movimentos}
            videoPadrao={estado.movimento}
            itens={assets.pecas}
            selecionados={estado.peca ? [estado.peca] : []}
            onMudar={(s) => mudar({ peca: s[0] ?? null })}
            onEnviado={async (nome) => {
              await recarregarAssets()
              mudar({ peca: nome })
            }}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-800">Cenário</h3>
          <SeletorAsset
            pasta="cenarios"
            videos={assets.movimentos}
            videoPadrao={estado.movimento}
            itens={assets.cenarios}
            selecionados={estado.cenario ? [estado.cenario] : []}
            onMudar={(s) => mudar({ cenario: s[0] ?? null })}
            onEnviado={async (nome) => {
              await recarregarAssets()
              mudar({ cenario: nome })
            }}
          />
        </div>
      </div>
    </Secao>
  )
}
