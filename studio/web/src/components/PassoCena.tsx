import AssistentePrompt from '@/components/AssistentePrompt'
import Secao from '@/components/Secao'
import { ehKling } from '@/lib/estudioUtil'
import type { PropsPasso } from '@/types'

// Direções de câmera testadas como boas práticas do Seedance 2.0 (uma por vídeo)
const CAMERAS_ELLIE = [
  'static tripod shot, mirror selfie framing',
  'handheld selfie, slight natural sway',
  'slow dolly in',
  'slow dolly out',
  'slow pan right',
  'gentle orbit around her',
  'POV shot from her eyes',
]
const CAMERAS_LUGAR = ['slow push-in', 'slow pan right', 'gentle drift forward', 'slow tilt up', 'drone rise', 'static shot']

const campo =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-rose-500 focus:ring-2 focus:ring-rose-100'

export default function PassoCena({ estado, mudar, config }: PropsPasso) {
  const lugar = estado.tipo === 'lugar'
  return (
    <Secao
      titulo="Cena"
      descricao={
        lugar
          ? 'Descreva em inglês o movimento da câmera e a atmosfera (clima, luz, estação, vida pequena como folhas caindo ou vapor). Sem pessoas, a menos que você queira.'
          : ehKling(estado.modelo)
          ? 'No Kling o texto é opcional: o movimento vem do vídeo e o visual vem da imagem. Use só para pequenos ajustes, em inglês (expressão, iluminação, objeto na mão).'
          : 'Descreva em inglês o que acontece. Uma ação clara e simples vale mais que muitos detalhes. O servidor já adiciona as regras de consistência (mesmo rosto, mesma roupa, mãos normais).'
      }
    >
      <AssistentePrompt estado={estado} mudar={mudar} config={config} />

      {!estado.movimento && !ehKling(estado.modelo) && (
        <label className="block space-y-1">
          <span className="text-sm font-medium text-slate-800">Câmera (é o que mais muda o resultado no Seedance)</span>
          <input
            list="cameras"
            value={estado.camera}
            onChange={(e) => mudar({ camera: e.target.value, promptManual: null })}
            placeholder={lugar ? 'slow push-in' : 'static tripod shot, mirror selfie framing'}
            className={campo}
          />
          <datalist id="cameras">
            {(lugar ? CAMERAS_LUGAR : CAMERAS_ELLIE).map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <span className="text-xs text-slate-500">Uma direção só. Escolha da lista ou escreva em inglês.</span>
        </label>
      )}

      <label className="block space-y-1">
        <span className="text-sm font-medium text-slate-800">{lugar ? 'Câmera e atmosfera' : 'O que acontece'}</span>
        <textarea
          rows={4}
          value={estado.cena}
          onChange={(e) => mudar({ cena: e.target.value, promptManual: null })}
          placeholder="Mirror selfie in a bright London flat bedroom with a white bed, she does a slow turn to show the dress"
          className={campo}
        />
      </label>

      {!lugar && (
      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <label className="block space-y-1">
          <span className="text-sm font-medium text-slate-800">Ela segura algum objeto? (opcional)</span>
          <input
            value={estado.objeto}
            onChange={(e) => mudar({ objeto: e.target.value, promptManual: null })}
            placeholder="a beige phone"
            className={campo}
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium text-slate-800">Em qual mão</span>
          <select
            value={estado.mao}
            onChange={(e) => mudar({ mao: e.target.value as typeof estado.mao, promptManual: null })}
            className={campo}
          >
            <option value="">Escolha...</option>
            <option value="right">Mão direita</option>
            <option value="left">Mão esquerda</option>
          </select>
        </label>
      </div>
      )}
      {!lugar && estado.objeto.trim() && !estado.mao && (
        <p className="text-sm text-amber-700">Diga em qual mão, senão o objeto tende a flutuar ou trocar de mão.</p>
      )}

      <label className="block space-y-1">
        <span className="text-sm font-medium text-slate-800">Pilar de conteúdo (meta 70/20/10)</span>
        <select
          value={estado.pilar}
          onChange={(e) => mudar({ pilar: e.target.value as typeof estado.pilar })}
          className={campo}
        >
          <option value="">Escolha...</option>
          <option value="outfit_clima">Outfit e clima (70%)</option>
          <option value="pov_london">POV de London girl (20%)</option>
          <option value="lugar">Lugar com sentimento (10%)</option>
        </select>
      </label>

      <label className="block space-y-1">
        <span className="text-sm font-medium text-slate-800">Nome do vídeo (vira o nome do arquivo)</span>
        <input
          value={estado.nome}
          onChange={(e) => mudar({ nome: e.target.value })}
          placeholder="ex.: v07_vestido_azul"
          className={campo}
        />
      </label>

      <div className="rounded-xl bg-slate-100 p-4 text-sm text-slate-700">
        <p className="mb-1 font-semibold">Dicas de consistência</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>Cite a peça como PECA na cena (ex.: "holds the dress from PECA on a hanger") quando for cabide ou POV.</li>
          <li>Sem a palavra PECA, ela aparece vestindo a peça.</li>
          <li>Não repita o rosto na cena: as fotos de referência já cuidam disso.</li>
        </ul>
      </div>
    </Secao>
  )
}
