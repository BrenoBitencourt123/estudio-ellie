import { useState } from 'react'
import { naFaixa, processo, urlMidia } from '@/lib/processo'
import type { Conferencia, Producao, SituacaoConferencia, Tomada } from '@/types/processo'

const SELO: Record<SituacaoConferencia, { rotulo: string; chave: string }> = {
  ok: { rotulo: 'Quadro conferido ✓', chave: 'pronta' }, aceita: { rotulo: 'Aceito por você', chave: 'pronta' },
  problema: { rotulo: 'Não atende', chave: 'falhou' }, indeterminada: { rotulo: 'Não conferido', chave: 'falhou' },
  pendente: { rotulo: 'Conferindo…', chave: 'gerando' }, sem_quadro: { rotulo: 'Falta o quadro', chave: 'nova' },
}

// Storyboard: o vídeo inteiro antes de gastar. Cada cena mostra o que acontece, o que o quadro precisa
// mostrar (exigências) e se o quadro atual passou na conferência.
export default function MapaCenas({ producao: p, editar, ajustar, atualizar }: {
  producao: Producao; editar: () => void; ajustar?: (id: string) => void; atualizar?: () => Promise<void>
}) {
  const [erro, setErro] = useState('')
  const [busy, setBusy] = useState(false)
  if (!p.tomadas.length) return <p>A sequência ainda está aberta. Desenvolva a direção no chat antes de preparar os quadros.</p>
  const ids = p.layout === 'lado_a_lado' ? p.tomadas.map(s => s.id) : [...new Set(p.cortes.map(c => c.tomada)), ...p.tomadas.filter(s => !p.cortes.some(c => c.tomada === s.id)).map(s => s.id)]
  const acao = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErro('')
    try { await fn(); await atualizar?.() } catch (e) { setErro(e instanceof Error ? e.message : 'Não concluiu.') }
    finally { setBusy(false) }
  }
  const situacao = (s: Tomada): SituacaoConferencia => p.situacoes?.[s.id]?.quadro ?? (s.imagens.length ? 'pendente' : 'sem_quadro')
  const conferindo = naFaixa(p, 'midia')
  const barradas = p.tomadas.filter(s => !s.arquivo && !['ok', 'aceita'].includes(situacao(s)))
  const audioIndefinido = (p.ficha?.audio ?? 'indefinido') === 'indefinido'
  return <div>
    <p className="scene-map-intro">{p.tomadas.length} {p.tomadas.length === 1 ? 'cena' : 'cenas'} · {Number(p.duracao_final.toFixed(1))}s de vídeo. Cada cena abaixo mostra uma parte da história.</p>
    <ol className="scene-map">{ids.map((id, i) => {
      const s = p.tomadas.find(s => s.id === id)!
      const cortes = p.cortes.filter(c => c.tomada === id)
      const tempo = cortes.length ? cortes.reduce((n, c) => n + c.duracao, 0) : s.duracao
      const sit = situacao(s)
      const c: Conferencia | undefined = p.conferencias?.[s.id]
      return <li key={s.id}>
        <div className="scene-map-head"><span className="scene-number">{i + 1}</span><h4>{s.titulo}</h4><small>{Number(tempo.toFixed(1))}s{s.lado !== 'cheia' ? ` · ${s.lado}` : ''}</small>
          {!s.arquivo && <span className={`chip chip-${SELO[sit].chave}`}>{sit === 'pendente' && !conferindo ? 'A conferir' : SELO[sit].rotulo}</span>}</div>
        <div className="scene-map-body">
          {s.imagens[0] && <img src={urlMidia(s.imagens[0].pasta, s.imagens[0].nome)} alt={`Quadro da cena ${i + 1}`} />}
          <div><p>{s.descricao || 'A descrição visual desta cena ainda está nos detalhes técnicos. Peça para desenvolvê-la no chat.'}</p>
            {s.intencao && <p className="scene-intent"><strong>Por que entra:</strong> {s.intencao}</p>}
            {!!s.exigencias?.length && <ul className="scene-requirements" aria-label="O quadro precisa mostrar">{s.exigencias.map(e => {
              const item = c?.itens.find(x => x.exigencia === e)
              return <li key={e} className={item ? (item.ok ? 'ok' : 'falhou') : ''} title={item?.observacao}>{item ? (item.ok ? '✓ ' : '✗ ') : '• '}{e}</li>
            })}</ul>}
            {s.fala && <blockquote>{s.fala}</blockquote>}
            {c && ['problema', 'indeterminada'].includes(sit) && <p className="scene-check">{c.resumo}</p>}
            <small className="scene-format">{s.tipo === 'imagem' ? 'Imagem com movimento de câmera' : 'Vídeo com ação'}{s.arquivo ? ' · material pronto' : ''}</small>
          </div>
        </div>
        <div className="scene-map-actions">
          {!s.arquivo && sit === 'problema' && <button className="primary-button" disabled={busy || conferindo}
            onClick={() => void acao(() => processo.refazerCena(p.id, s.id))}>Refazer com a correção</button>}
          {!s.arquivo && ['problema', 'indeterminada'].includes(sit) && <button className="secondary-button" disabled={busy}
            onClick={() => void acao(() => processo.aceitarCena(p.id, s.id))}>Usar mesmo assim</button>}
          {!s.arquivo && (sit === 'indeterminada' || (sit === 'pendente' && !conferindo)) && <button className="secondary-button" disabled={busy}
            onClick={() => void acao(() => processo.conferirCena(p.id, s.id))}>Conferir agora</button>}
          {ajustar && <button className="secondary-button" onClick={() => ajustar(s.id)}>Ajustar cena {i + 1}</button>}
          <details><summary>Prompt e detalhes técnicos</summary><p>{s.prompt}</p><small>{s.modelo.replaceAll('_', ' ')} · {s.duracao}s brutos</small></details></div>
      </li>
    })}</ol>
    <section className="storyboard-review">
      {p.revisao_atual?.atual
        ? <p className="success-note">Storyboard revisado nesta versão. A geração paga está liberada no cartão de produção.</p>
        : <>
          <p>{audioIndefinido ? 'Antes de revisar: decida o áudio do vídeo no caderno.'
            : barradas.length ? `Antes de revisar: resolva o quadro de ${barradas.map(s => `“${s.titulo}”`).join(', ')}.`
              : 'Tudo conferido. Assista mentalmente à sequência acima: se ela conta a história, marque como revisado.'}</p>
          <button className="primary-button" disabled={busy || audioIndefinido || barradas.length > 0 || conferindo}
            onClick={() => void acao(() => processo.revisarStoryboard(p))}>Revisei o storyboard</button></>}
    </section>
    {erro && <p role="alert" className="error-message">{erro}</p>}
    <button className="secondary-button" onClick={editar}>Editar tempos e configuração</button>
  </div>
}
