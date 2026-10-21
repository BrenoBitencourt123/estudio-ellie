import { useEffect, useRef, useState } from 'react'
import { naFaixa, processo, urlNarracao, urlTrilha } from '@/lib/processo'
import type { AjustesNarracao, Producao } from '@/types/processo'

// Narração de qualquer vídeo: texto em inglês, voz do ElevenLabs (com tempo por palavra) ou áudio enviado.
// Áudio primeiro: com a voz pronta, os cortes seguem as frases dela e o vídeo termina junto com a fala.
export default function CartaoNarracao({ producao, atualizar }: { producao: Producao; atualizar: () => Promise<void> }) {
  const n = producao.narracao
  const [texto, setTexto] = useState(n?.texto ?? '')
  const [voz, setVoz] = useState(n?.voz ?? '')
  const [setas, setSetas] = useState(n?.setas ?? true)
  const [cta, setCta] = useState(n?.cta ?? '')
  const [eleven, setEleven] = useState<boolean | null>(null)
  const [trilhas, setTrilhas] = useState<string[]>([])
  const [erro, setErro] = useState('')
  const [busy, setBusy] = useState(false)
  const arquivo = useRef<HTMLInputElement>(null)
  const arquivoTrilha = useRef<HTMLInputElement>(null)
  useEffect(() => { setTexto(n?.texto ?? '') }, [n?.texto])
  useEffect(() => { setCta(n?.cta ?? '') }, [n?.cta])
  useEffect(() => {
    void processo.narracaoStatus().then(s => { setEleven(s.elevenlabs); if (!voz) setVoz(s.voz_padrao) }).catch(() => setEleven(false))
    void processo.trilhas().then(setTrilhas).catch(() => setTrilhas([]))
  }, [])
  const ajustes: AjustesNarracao = {
    setas, cta, estilo_legenda: n?.estilo_legenda ?? 'karaoke', seguir_voz: n?.seguir_voz ?? true,
    trilha: n?.trilha ?? '', volume_trilha: n?.volume_trilha ?? 0.2, sfx: n?.sfx ?? false,
  }
  const ajustar = (mudanca: Partial<AjustesNarracao>) =>
    void acao(() => processo.ajustarNarracao(producao.id, { ...ajustes, ...mudanca }))
  const fala = n?.palavras.length ? n.palavras[n.palavras.length - 1].fim : 0
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
      <small>{n.palavras.length} palavras sincronizadas{n.origem === 'arquivo' ? ' (áudio enviado)' : ' (ElevenLabs)'} · {fala.toFixed(1)}s de fala.</small>
      {textoMudou && <p className="field-note">O texto mudou depois da voz. Gere a voz de novo para a legenda bater com a fala.</p>}
      <div className="word-preview">{n.palavras.slice(0, 40).map((w, i) => <span key={i} title={`${w.ini.toFixed(2)}s`}>{w.p}</span>)}</div>
    </>}
    <details className="narration-finish"><summary>Acabamento · legenda, música e ritmo</summary>
      <label className="pilot-choice"><input type="checkbox" checked={ajustes.seguir_voz} disabled={ativo}
        onChange={e => ajustar({ seguir_voz: e.target.checked })} /> Cortes seguem a voz (uma cena por frase, o vídeo acaba com a fala)</label>
      <label className="field">Estilo da legenda
        <select value={ajustes.estilo_legenda} disabled={ativo} onChange={e => ajustar({ estilo_legenda: e.target.value as AjustesNarracao['estilo_legenda'] })}>
          <option value="karaoke">Karaokê · maiúsculas, destaque amarelo</option>
          <option value="elegante">Elegante · serifa, destaque dourado (fé e reflexão)</option>
        </select></label>
      <label className="field">Música de fundo (abaixa sozinha quando a voz fala)
        <select value={ajustes.trilha} disabled={ativo} onChange={e => ajustar({ trilha: e.target.value })}>
          <option value="">Sem música</option>
          {trilhas.map(t => <option key={t} value={t}>{t}</option>)}
        </select></label>
      {ajustes.trilha && <>
        <audio className="narration-audio" controls src={urlTrilha(ajustes.trilha)} />
        <label className="field">Volume da música · {Math.round(ajustes.volume_trilha * 100)}%
          <input type="range" min="0.05" max="0.6" step="0.05" defaultValue={ajustes.volume_trilha} disabled={ativo}
            onMouseUp={e => ajustar({ volume_trilha: Number(e.currentTarget.value) })}
            onKeyUp={e => ajustar({ volume_trilha: Number(e.currentTarget.value) })} /></label>
      </>}
      <div className="card-buttons">
        <button className="secondary-button" disabled={ativo} onClick={() => arquivoTrilha.current?.click()}>Adicionar música</button>
        <input ref={arquivoTrilha} type="file" accept="audio/mpeg,audio/wav,audio/x-m4a,audio/mp4,audio/ogg,.mp3,.wav,.m4a,.ogg" hidden
          onChange={e => {
            const f = e.target.files?.[0]; e.target.value = ''
            if (f) void acao(async () => { const { nome } = await processo.enviarTrilha(f); setTrilhas(t => [...t, nome].sort())
              await processo.ajustarNarracao(producao.id, { ...ajustes, trilha: nome }) })
          }} />
      </div>
      <label className="pilot-choice"><input type="checkbox" checked={ajustes.sfx} disabled={ativo}
        onChange={e => ajustar({ sfx: e.target.checked })} /> Whoosh discreto nos cortes</label>
      <small>Tudo isso muda só a montagem local, sem créditos. O volume final sai no padrão das redes (-14 LUFS).</small>
    </details>
    {erro && <p role="alert" className="error-message">{erro}</p>}
  </>
}
