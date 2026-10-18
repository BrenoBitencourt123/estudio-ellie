import Secao from '@/components/Secao'
import { ehKling, formatarBrl, formatarUsd, presets, presetsKling } from '@/lib/estudioUtil'
import type { Estimativa, PropsPasso } from '@/types'

interface Props extends PropsPasso {
  estimativa: Estimativa | null
  promptAuto: string
  erro: string
}

const campo =
  'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-rose-500 focus:ring-2 focus:ring-rose-100'

export default function PassoRevisao({ estado, mudar, config, estimativa, promptAuto, erro }: Props) {
  const kling = ehKling(estado.modelo)
  const lista = kling ? presetsKling : presets
  const presetAtivo = lista.find(
    (p) => p.modelo === estado.modelo && (kling || ('resolucao' in p && p.resolucao === estado.resolucao)),
  )
  const promptAtual = estado.promptManual ?? promptAuto
  const restante = config.teto_usd - config.gasto_semana_usd

  return (
    <Secao
      titulo="Ajustes avançados"
      descricao="Escolha outro modelo ou resolução, ou edite o prompt final à mão. Os botões de gerar ficam acima."
    >
      <div className="grid gap-3 sm:grid-cols-4">
        {lista.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => mudar('resolucao' in p ? { modelo: p.modelo, resolucao: p.resolucao } : { modelo: p.modelo })}
            className={`rounded-xl border-2 p-3 text-left transition ${
              presetAtivo?.id === p.id ? 'border-rose-500 bg-rose-50' : 'border-slate-200 bg-white hover:border-slate-400'
            }`}
          >
            <div className="font-semibold text-slate-900">{p.nome}</div>
            <div className="text-xs text-slate-500">
              {'resolucao' in p ? `Seedance ${p.modelo} · ${p.resolucao}` : p.modelo.replace('kling-', 'Kling ')}
            </div>
            <div className="mt-1 text-xs text-slate-600">{p.dica}</div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-800">Modelo</span>
          <select className={`${campo} block`} value={estado.modelo} onChange={(e) => mudar({ modelo: e.target.value })}>
            {(kling ? config.modelos_kling : config.modelos).map((m) => (
              <option key={m} value={m}>
                {kling ? m.replace('kling-', 'Kling ') : `Seedance ${m}`}
              </option>
            ))}
          </select>
        </label>
        {kling ? (
          <>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-800">Orientação do corpo</span>
              <select
                className={`${campo} block`}
                value={estado.orientacao}
                onChange={(e) => mudar({ orientacao: e.target.value as typeof estado.orientacao })}
              >
                <option value="video">Segue o vídeo (movimentos amplos)</option>
                <option value="image">Segue a imagem (mantém a pose da foto)</option>
              </select>
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={estado.manterSom}
                onChange={(e) => mudar({ manterSom: e.target.checked })}
                className="accent-rose-600"
              />
              Manter o som do vídeo
            </label>
          </>
        ) : (
          <label className="space-y-1 text-sm">
            <span className="font-medium text-slate-800">Resolução</span>
            <select
              className={`${campo} block`}
              value={estado.resolucao}
              onChange={(e) => mudar({ resolucao: e.target.value as typeof estado.resolucao })}
            >
              <option value="480p">480p</option>
              <option value="720p">720p</option>
            </select>
          </label>
        )}
        <label className="min-w-48 flex-1 space-y-1 text-sm">
          <span className="font-medium text-slate-800">
            {kling ? 'Trecho do movimento' : 'Duração'}: {estado.duracao}s
          </span>
          <input
            type="range"
            min={4}
            max={15}
            value={estado.duracao}
            onChange={(e) => mudar({ duracao: Number(e.target.value) })}
            className="block w-full accent-rose-600"
          />
          <span className="text-xs text-slate-500">
            {kling
              ? 'No Kling o vídeo gerado tem a duração do trecho, e o custo é por segundo.'
              : 'Para TikTok da Ellie, 7 a 9s costuma render mais conclusão.'}
          </span>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={estado.aumentar1080}
            onChange={(e) => mudar({ aumentar1080: e.target.checked })}
            className="accent-rose-600"
          />
          Aumentar para 1080p no PC (grátis)
        </label>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
        {estimativa ? (
          <div className="flex flex-wrap gap-x-8 gap-y-1">
            <span>
              Custo estimado:{' '}
              <strong>
                {formatarUsd(estimativa.custo_usd)} ({formatarBrl(estimativa.custo_brl)})
              </strong>
            </span>
            <span className="text-slate-600">
              Resta no teto da semana: {formatarUsd(Math.max(0, restante))}
            </span>
            {estimativa.custo_usd > restante && (
              <span className="font-medium text-red-600">Passa do teto semanal, o servidor vai recusar.</span>
            )}
          </div>
        ) : (
          <span className="text-slate-500">Calculando custo...</span>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-800">Prompt final enviado ao {kling ? 'Kling' : 'Seedance'}</span>
          {estado.promptManual !== null && (
            <button
              type="button"
              onClick={() => mudar({ promptManual: null })}
              className="text-sm text-rose-600 underline"
            >
              Voltar ao automático
            </button>
          )}
        </div>
        {erro && <p className="text-sm text-amber-700">{erro}</p>}
        <textarea
          rows={9}
          value={promptAtual}
          onChange={(e) => mudar({ promptManual: e.target.value })}
          className={`${campo} w-full font-mono text-xs leading-relaxed`}
        />
        <p className="text-xs text-slate-500">
          {estado.promptManual !== null
            ? 'Editado à mão: mexer na cena ou nas referências depois disso não atualiza este texto.'
            : 'Montado automaticamente a partir das suas escolhas. Pode editar se quiser.'}
        </p>
      </div>
    </Secao>
  )
}
