import { useState } from 'react'
import { api } from '@/lib/api'
import { paraPedido } from '@/lib/estudioUtil'
import type { ConfigEstudio, EstadoEstudio, RespostaAssistente, ResultadoAssistente } from '@/types'

interface Props {
  estado: EstadoEstudio
  mudar: (parcial: Partial<EstadoEstudio>) => void
  config: ConfigEstudio
}

const campo =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-rose-500 focus:ring-2 focus:ring-rose-100'

export default function AssistentePrompt({ estado, mudar, config }: Props) {
  const [ideia, setIdeia] = useState('')
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState('')
  const [resposta, setResposta] = useState<RespostaAssistente | null>(null)
  const [colada, setColada] = useState('')
  const [resultado, setResultado] = useState<ResultadoAssistente | null>(null)
  const [copiado, setCopiado] = useState(false)

  function aplicar(r: ResultadoAssistente) {
    setResultado(r)
    mudar({
      cena: r.cena,
      camera: estado.movimento ? '' : r.camera,
      objeto: r.objeto,
      mao: r.mao,
      nome: estado.nome || r.nome,
      promptManual: null,
    })
  }

  async function pedir() {
    setErro('')
    setCarregando(true)
    try {
      const nova = await api.assistente(paraPedido(estado), ideia)
      setResposta(nova)
      setResultado(null)
      if (nova.resultado) aplicar(nova.resultado)
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao pedir o prompt')
    } finally {
      setCarregando(false)
    }
  }

  async function lerColada() {
    setErro('')
    try {
      aplicar((await api.interpretar(colada)).resultado)
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui ler a resposta')
    }
  }

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2000)
    } catch {
      setErro('Não consegui copiar. Selecione o texto e copie à mão.')
    }
  }

  const manual = resposta?.provedor === 'manual' && resposta?.briefing

  return (
    <div className="space-y-3 rounded-xl border border-rose-200 bg-rose-50/50 p-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-900">Assistente de prompt (IA)</h3>
        <p className="text-xs text-slate-600">
          Conte a ideia em português. A IA olha as suas referências e o vídeo de movimento e escreve a cena em inglês.
          {config.provedor_prompt === 'openclaw'
            ? ' Usa o OpenClaw pela sua assinatura, sem sair daqui.'
            : config.provedor_prompt === 'manual'
              ? ' Modo manual: você cola o pedido no ChatGPT e traz a resposta de volta.'
              : ''}
        </p>
      </div>

      <textarea
        rows={2}
        value={ideia}
        onChange={(e) => setIdeia(e.target.value)}
        placeholder="Ex.: ela gira mostrando o conjunto azul, meio tímida, luz de fim de tarde"
        className={campo}
      />
      <button
        type="button"
        onClick={pedir}
        disabled={carregando}
        className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:bg-slate-300"
      >
        {carregando
          ? config.provedor_prompt === 'openclaw'
            ? 'A IA está olhando as referências (10 a 40s)...'
            : 'Preparando...'
          : config.provedor_prompt === 'manual'
            ? 'Preparar pedido para a IA'
            : 'Gerar cena com IA'}
      </button>
      {erro && <p className="text-sm text-red-600">{erro}</p>}
      {resposta?.aviso && <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-800">{resposta.aviso}</p>}

      {manual && resposta && (
        <div className="space-y-3 rounded-lg bg-white p-3 text-sm">
          <ol className="list-decimal space-y-1 pl-5 text-slate-700">
            <li>Copie o pedido abaixo e cole no ChatGPT.</li>
            <li>
              Anexe a(s) imagem(ns):{' '}
              {resposta.folhas.map((f, i) => (
                <a key={f} href={f} target="_blank" rel="noreferrer" className="mr-2 text-rose-600 underline">
                  folha {i + 1}
                </a>
              ))}
              (abra, clique com o botão direito e copie a imagem, ou arraste para o chat).
            </li>
            <li>Cole a resposta do ChatGPT aqui embaixo e clique em Aplicar.</li>
          </ol>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => copiar(resposta.briefing ?? '')}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-white"
            >
              {copiado ? 'Copiado!' : 'Copiar pedido'}
            </button>
            <span className="text-xs text-slate-500">{(resposta.briefing ?? '').length} caracteres</span>
          </div>
          <textarea
            rows={5}
            readOnly
            value={resposta.briefing}
            className={`${campo} font-mono text-xs`}
          />
          <textarea
            rows={5}
            value={colada}
            onChange={(e) => setColada(e.target.value)}
            placeholder="Cole aqui a resposta do ChatGPT (o JSON inteiro)"
            className={`${campo} font-mono text-xs`}
          />
          <button
            type="button"
            onClick={lerColada}
            disabled={!colada.trim()}
            className="rounded-lg bg-rose-600 px-4 py-2 font-semibold text-white disabled:bg-slate-300"
          >
            Aplicar resposta
          </button>
        </div>
      )}

      {resultado && (
        <div className="space-y-2 rounded-lg bg-white p-3 text-sm">
          <p className="font-medium text-emerald-700">Aplicado nos campos abaixo. Revise e ajuste se quiser.</p>
          {resultado.resumo_pt && <p className="text-slate-700">{resultado.resumo_pt}</p>}
          {resultado.avisos.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-amber-700">
              {resultado.avisos.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
