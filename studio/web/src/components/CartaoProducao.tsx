import { useState } from 'react'
import { processo, urlResultado } from '@/lib/processo'
import type { Bloco, Producao } from '@/types/processo'

export default function CartaoProducao({ bloco, producao, abrir, responder, atualizar }: {
  bloco: Bloco; producao: Producao; abrir: (b: Bloco) => void; responder: (texto: string) => void; atualizar: () => Promise<void>
}) {
  const [erro, setErro] = useState('')
  const [busy, setBusy] = useState(false)
  const [teto, setTeto] = useState('')
  const [teste, setTeste] = useState(true)
  const action = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErro('')
    try { await fn(); await atualizar() } catch (e) { setErro(e instanceof Error ? e.message : 'A operação não concluiu.') }
    finally { setBusy(false) }
  }
  const pending = producao.tomadas.filter(s => !s.arquivo && !s.submit_id)
  const waiting = producao.tomadas.some(s => s.submit_id && !s.arquivo)
  const ready = producao.tomadas.every(s => s.arquivo)
  const active = busy || producao.ocupado
  return <section className={`conversation-card card-${bloco.tipo}`}>
    {bloco.titulo && <h3>{bloco.titulo}</h3>}
    {bloco.tipo === 'quiz' && <><p>{bloco.pergunta}</p><div className="quiz-options">{bloco.opcoes?.map(o =>
      <button className="secondary-button" key={o} onClick={() => responder(o)}>{o}</button>)}</div><small>Ou responda com suas palavras no chat.</small></>}
    {['galeria', 'upload'].includes(bloco.tipo) && <><p>Veja os arquivos da sua biblioteca e escolha o que faz sentido para esta ideia.</p>
      <button className="secondary-button" onClick={() => abrir(bloco)}>Abrir referências ↗</button></>}
    {bloco.tipo === 'plano' && <><p>{producao.tomadas.length} tomadas · {producao.duracao_final}s no vídeo final</p>
      <ol>{producao.tomadas.map(s => <li key={s.id}><strong>{s.titulo}</strong><span>{s.duracao}s · {s.arquivo ? 'arquivo disponível' : s.modelo.replaceAll('_', ' ')}</span></li>)}</ol>
      <button className="secondary-button" onClick={() => abrir(bloco)}>Ver e ajustar a estrutura</button></>}
    {bloco.tipo === 'custo' && <>
      <div className="cost-heading"><span>Custo desta geração</span><strong>{producao.cotacao ? `${producao.cotacao.total.toLocaleString('pt-BR')} créditos` : 'Ainda não cotado'}</strong></div>
      <p>{pending.length} tomadas novas. Arquivos prontos serão reaproveitados.</p>
      {pending.length > 1 && <label className="pilot-choice"><input type="checkbox" checked={teste} onChange={e => setTeste(e.target.checked)} />
        Testar primeiro só a transformação, antes de pagar as outras tomadas.</label>}
      {producao.cotacao?.executada && <p className="success-note">Este lote já foi enviado. Acompanhe o resultado antes de cotar outra tomada.</p>}
      {producao.cotacao && <><details><summary>O que entra nesta cotação</summary>{producao.cotacao.itens.map((q, i) =>
        <p key={q.nodeId}>Tomada {i + 1}<strong className="cost-number">{q.maxCredits} créditos</strong></p>)}</details>
        <label className="field">Meu teto para este lote (créditos)<input type="number" min={producao.cotacao.total} placeholder={String(producao.cotacao.total)} value={teto} onChange={e => setTeto(e.target.value)} /></label>
      </>}
      <div className="card-buttons"><button className="secondary-button" disabled={active || !pending.length || waiting} onClick={() => void action(() => processo.cotar(producao.id,
        teste && pending.length > 1 ? [pending.find(s => s.lado === 'esquerda')?.id ?? pending[0].id] : pending.map(s => s.id)))}>Consultar custo real</button>
        {producao.cotacao && !producao.cotacao.executada && <button className="primary-button" disabled={active || Number(teto) < producao.cotacao.total || !pending.length}
          onClick={() => void action(() => processo.gerar(producao, Number(teto)))}>Autorizar e gerar · {producao.cotacao.total} créditos</button>}
        {waiting && <button className="secondary-button" disabled={active} onClick={() => void action(() => processo.acompanhar(producao.id))}>Acompanhar e baixar</button>}</div>
      <small>Consulta de preço não gera vídeo. A assinatura do chat e os créditos Dreamina são separados.</small>
    </>}
    {bloco.tipo === 'edicao' && <><p>Texto, faixa e cortes mudam localmente, aproveitando os vídeos.</p><div className="card-buttons">
      <button className="secondary-button" onClick={() => abrir(bloco)}>Editar texto e faixa</button>
      <button className="primary-button" disabled={active || !ready} onClick={() => void action(() => processo.montar(producao.id))}>{active ? 'Montando…' : 'Montar vídeo · sem créditos'}</button></div>
      {!ready && <small>As tomadas precisam estar baixadas antes de montar.</small>}</>}
    {bloco.tipo === 'resultado' && (producao.resultado ? <><video className="result-video" src={`${urlResultado(producao.id)}?v=${producao.resultado.nome}`} controls playsInline preload="metadata" />
      <div className="card-buttons"><a className="primary-button" href={urlResultado(producao.id)} download>Baixar vídeo</a>
        <button className="secondary-button" onClick={() => void navigator.clipboard.writeText(producao.legenda)}>Copiar legenda</button></div>
      <p className="caption-preview">{producao.legenda}</p></> : <p>A montagem ainda não foi concluída.</p>)}
    {bloco.tipo === 'conexao' && <p>Abra o OpenClaw com a assinatura conectada. Depois, envie sua mensagem novamente. A produção está salva.</p>}
    {erro && <p role="alert" className="error-message">{erro}</p>}
  </section>
}
