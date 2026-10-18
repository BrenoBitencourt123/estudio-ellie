import { useEffect, useRef, useState } from 'react'
import Secao from '@/components/Secao'
import { ehKling } from '@/lib/estudioUtil'
import SeletorAsset from '@/components/SeletorAsset'
import type { PropsPasso } from '@/types'

export default function PassoMovimento({ estado, mudar, assets, recarregarAssets }: PropsPasso) {
  const video = useRef<HTMLVideoElement>(null)
  const [total, setTotal] = useState(0)

  // Ao trocar o vídeo, zera o ponto de início e mede a duração
  useEffect(() => setTotal(0), [estado.movimento])

  function aoCarregar() {
    if (video.current) setTotal(video.current.duration)
  }

  const fim = estado.movimentoInicio + estado.duracao

  return (
    <Secao
      titulo="Movimento (motion control)"
      descricao={
        estado.tipo === 'lugar'
          ? 'Opcional. Um vídeo de referência de câmera (travelling, aproximação, giro) faz o clipe do lugar se mover do mesmo jeito. Pessoas e texto do vídeo são ignorados.'
          : 'Grave você mesmo fazendo o movimento, de corpo inteiro e com a câmera onde quer. O Seedance copia só o movimento do corpo e da câmera e coloca a Ellie no lugar. Rosto, roupa e texto do vídeo original são ignorados.'
      }
    >
      <SeletorAsset
        pasta="movimentos"
        itens={assets.movimentos}
        selecionados={estado.movimento ? [estado.movimento] : []}
        onMudar={(s) => mudar({ movimento: s[0] ?? null, movimentoInicio: 0 })}
        onEnviado={async (nome) => {
          await recarregarAssets()
          mudar({ movimento: nome, movimentoInicio: 0 })
        }}
      />

      {estado.movimento ? (
        <div className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-[180px_1fr]">
          <video
            ref={video}
            src={`/files/movimentos/${encodeURIComponent(estado.movimento)}#t=${estado.movimentoInicio}`}
            controls
            muted
            onLoadedMetadata={aoCarregar}
            className="w-full rounded-lg bg-black"
          />
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="font-medium text-slate-800">Ponto de início: {estado.movimentoInicio.toFixed(1)}s</span>
              <input
                type="range"
                min={0}
                max={Math.max(0, total - 2)}
                step={0.1}
                value={estado.movimentoInicio}
                onChange={(e) => mudar({ movimentoInicio: Number(e.target.value) })}
                className="mt-2 w-full accent-rose-600"
              />
            </label>
            <p className="text-slate-600">
              Vai usar de {estado.movimentoInicio.toFixed(1)}s até {Math.min(fim, total || fim).toFixed(1)}s do vídeo
              (a duração do vídeo final é {estado.duracao}s). O áudio é removido e a faixa de baixo é cortada
              (aviso de direitos do TikTok).
            </p>
            {total > 0 && total < estado.duracao && (
              <p className="text-amber-700">
                Seu vídeo tem {total.toFixed(1)}s e o final pede {estado.duracao}s. A Ellie pode parar de se mexer no fim.
              </p>
            )}
            <button
              type="button"
              onClick={() => mudar({ movimento: null, movimentoInicio: 0 })}
              className="text-slate-500 underline hover:text-slate-800"
            >
              Não usar movimento
            </button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Sem vídeo escolhido: a Ellie se move só pelo que a cena descrever.</p>
      )}

      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>Filme na vertical, corpo inteiro visível, fundo simples e boa luz.</li>
        <li>Movimentos simples e contínuos (giro, caminhada, balançar) saem melhor que ações complexas.</li>
        <li>Evite texto ou logo em cima do corpo: não dá para remover automaticamente.</li>
        {ehKling(estado.modelo) && (
          <li className="font-medium text-amber-700">
            Kling: já rejeitou um vídeo com a cabeça cortada ("No complete upper body detected"). Não está confirmado se
            o motivo foi a cabeça ou a diferença de enquadramento com a imagem base. Rejeição não cobra.
          </li>
        )}
      </ul>
    </Secao>
  )
}
