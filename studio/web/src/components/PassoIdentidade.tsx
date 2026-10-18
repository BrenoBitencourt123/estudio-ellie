import Secao from '@/components/Secao'
import SeletorAsset from '@/components/SeletorAsset'
import { ehKling } from '@/lib/estudioUtil'
import type { PropsPasso } from '@/types'

export default function PassoIdentidade({ estado, mudar, assets, config, recarregarAssets }: PropsPasso) {
  if (estado.tipo === 'lugar') {
    return (
      <Secao
        titulo="Foto do lugar"
        descricao="A foto trava o cenário: arquitetura, cores, clima e luz. Use uma foto nítida, vertical se possível, sem pessoas em primeiro plano. O vídeo vai animar essa foto."
      >
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
      </Secao>
    )
  }

  if (ehKling(estado.modelo)) {
    return (
      <Secao
        titulo="Imagem base da Ellie (Kling)"
        descricao="O Kling usa uma única imagem: a Ellie já vestida e, se quiser, já no cenário. Rosto, roupa e lugar saem dela, e só o movimento vem do seu vídeo. Use uma foto de corpo inteiro (ou meio corpo, igual ao seu vídeo), vertical, de até 10 MB."
      >
        <SeletorAsset
          pasta="base"
          videos={assets.movimentos}
          videoPadrao={estado.movimento}
          itens={assets.base}
          selecionados={estado.imagemBase ? [estado.imagemBase] : []}
          onMudar={(s) => mudar({ imagemBase: s[0] ?? null })}
          onEnviado={async (nome) => {
            await recarregarAssets()
            mudar({ imagemBase: nome })
          }}
        />
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>O enquadramento da imagem deve parecer com o do vídeo de movimento (corpo inteiro com corpo inteiro).</li>
          <li>Para trocar de roupa ou de lugar, é preciso uma imagem base nova.</li>
          <li>Mãos visíveis e sem objetos estranhos ajudam o Kling a não inventar dedos.</li>
        </ul>
      </Secao>
    )
  }

  return (
    <Secao
      titulo="Quem é a Ellie neste vídeo"
      descricao="As fotos de rosto travam a identidade. Use sempre as mesmas, de ângulos diferentes (frente, 3/4, perfil, sorriso). Quanto mais estável essa escolha entre vídeos, mais consistente fica a Ellie."
    >
      <SeletorAsset
        pasta="persona"
        itens={assets.persona}
        selecionados={estado.persona}
        multiplo
        onMudar={(persona) => mudar({ persona })}
        onEnviado={async (nome) => {
          await recarregarAssets()
          mudar({ persona: [...estado.persona, nome] })
        }}
      />
      <p className="text-sm text-slate-500">
        {estado.persona.length} foto(s) escolhida(s). O limite é {config.max_imagens} imagens no total, contando peça e cenário.
      </p>
    </Secao>
  )
}
