import { useEffect, useRef, useState } from 'react'
import { naFaixa, processo, urlNarracao } from '@/lib/processo'
import type { Producao } from '@/types/processo'

// Narração de qualquer vídeo: texto em inglês, voz do ElevenLabs (com tempo por palavra) ou áudio enviado.
export default function CartaoNarracao({ producao, atualizar }: { producao: Producao; atualizar: () => Promise<void> }) {
  const n = producao.narracao
  const [texto, setTexto] = useState(n?.texto ?? '')
  const [voz, setVoz] = useState(n?.voz ?? '')
  const [setas, setSetas] = useState(n?.setas ?? true)
  const [cta, setCta] = useState(n?.cta ?? '')
  const [eleven, setEleven] = useState<boolean | null>(null)
  const [erro, setErro] = useState('')
  const [busy, setBusy] = useState(false)
  const arquivo = useRef<HTMLInputElement>(null)
  useEffect(() => { setTexto(n?.texto ?? '') }, [n?.texto])
  useEffect(() => { setCta(n?.cta ?? '') }, [n?.cta])
  useEffect(() => {
    void processo.narracaoStatus().then(s => { setEleven(s.elevenlabs); if (!voz) setVoz(s.voz_padrao) }).catch(() => setEleven(false))
  }, [])
  // Só a própria narração em curso trava este cartão; imagem e montagem seguem em paralelo
  const ativo = busy || naFaixa(producao, 'voz')
  const palavras = texto.trim() ? texto.trim().split(/\s+/).length : 0
  const acao = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErro('')
    try { await fn(); await atualizar() } catch (e) { setErro(e instanceof Error ? e.message : 'Não concluiu.') }
    finally { setBusy(false) }
  }
  const textoMudou = !!n?.audio && texto.trim() !== (n?.texto ?? '').trim()
  return <>
    <label className="field">Texto da narração (inglês)
      <textarea className="narration-text" value={texto} maxLength={800} onChange={e => setTexto(e.target.value)} disabled={ativo} />
    </label>
    <small>{palavras} palavras · ~{Math.max(1, Math.round(palavras / 2.6))}s de fala.</small>
    <label className="field">Frase do CTA (as setas entram quando ela começa; vazio = sem setas)
      <input type="text" value={cta} maxLength={200} onChange={e => setCta(e.target.value)} disabled={ativo} placeholder="ex.: Type Yes if you receive it." />
    </label>
    <div className="narration-row">
      <input type="text" placeholder="voice_id do ElevenLabs" value={voz} onChange={e => setVoz(e.target.value)} disabled={ativo} aria-label="Voz do ElevenLabs" />
      <label className="pilot-choice"><input type="checkbox" checked={setas} onChange={e => setSetas(e.target.checked)} disabled={ativo} /> Setas no CTA</label>
    </div>
    <div className="card-buttons">
      <button className="primary-button" disabled={ativo || !eleven || !texto.trim() || !voz.trim()}
        onClick={() => void acao(() => processo.gerarVoz(producao.id, { texto, voz, setas, cta }))}>{ativo ? 'Aguarde…' : 'Gerar voz · ElevenLabs'}</button>
      <button className="secondary-button" disabled={ativo} onClick={() => arquivo.current?.click()}>Enviar áudio pronto</button>
      <input ref={arquivo} type="file" accept="audio/mpeg,audio/wav,audio/x-m4a,audio/mp4,audio/ogg,.mp3,.wav,.m4a,.ogg" hidden
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void acao(() => processo.enviarAudio(producao.id, f, texto, setas)) }} />
    </div>
    {eleven === false && <small>Para gerar daqui, coloque ELEVENLABS_API_KEY no .env (usa os créditos do seu plano). Ou gere no site e use "Enviar áudio pronto".</small>}
    {n?.audio && <>
      <audio className="narration-audio" controls src={urlNarracao(producao.id, n.audio)} />
      <small>{n.palavras.length} palavras sincronizadas{n.origem === 'arquivo' ? ' (áudio enviado)' : ' (ElevenLabs)'}.</small>
      {textoMudou && <p className="field-note">O texto mudou depois da voz. Gere a voz de novo para a legenda bater com a fala.</p>}
      <div className="word-preview">{n.palavras.slice(0, 40).map((w, i) => <span key={i} title={`${w.ini.toFixed(2)}s`}>{w.p}</span>)}</div>
    </>}
    {erro && <p role="alert" className="error-message">{erro}</p>}
  </>
}
