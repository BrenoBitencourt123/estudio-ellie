import { useEffect, useState } from 'react'
import { naFaixa, processo, urlMidia, urlResultado } from '@/lib/processo'
import CartaoNarracao from '@/components/CartaoNarracao'
import type { Bloco, Producao, Tomada } from '@/types/processo'

function estadoTomada(s: Tomada): { chave: string; rotulo: string } {
  if (s.arquivo) return { chave: 'pronta', rotulo: 'Pronta ✓' }
  if (s.submit_id && ['failed', 'canceled', 'cancelled'].includes(s.estado ?? '')) return { chave: 'falhou', rotulo: 'Falhou' }
  if (s.submit_id) return { chave: 'gerando', rotulo: 'Gerando…' }
  return { chave: 'nova', rotulo: 'Ainda não gerada' }
}

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
  const ready = producao.tomadas.length > 0 && producao.tomadas.every(s => s.arquivo)
  // Só cotação/geração/montagem em curso travam estes botões; imagem e narração em paralelo não travam
  const active = busy || naFaixa(producao, 'producao')
  // Lote da próxima cotação: no modo teste, só uma tomada (no lado a lado, a da esquerda)
  const lote = teste && pending.length > 1 ? [pending.find(s => s.lado === 'esquerda') ?? pending[0]] : pending
  // Só mostra a cotação se ela é deste lote e ainda não foi usada
  const cotacaoAtual = producao.cotacao && !producao.cotacao.executada
    && (producao.cotacao.tomadas ?? []).every(id => pending.some(s => s.id === id)) ? producao.cotacao : null
  useEffect(() => { setTeto('') }, [cotacaoAtual?.id])
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
      {/* Situação de cada tomada: o que já está pronto aparece aqui mesmo, para assistir antes de gastar mais */}
      <ul className="shot-status">{producao.tomadas.map(s => {
        const st = estadoTomada(s)
        return <li key={s.id} className={`shot-${st.chave}`}>
          <div className="shot-head"><strong>{s.titulo}</strong><span className={`chip chip-${st.chave}`}>{st.rotulo}</span></div>
          <small>{s.lado === 'esquerda' ? 'Lado esquerdo' : s.lado === 'direita' ? 'Lado direito' : 'Tela cheia'} · {s.duracao}s{typeof s.creditos_registrados === 'number' ? ` · ${s.creditos_registrados} créditos gastos` : ''}</small>
          {s.arquivo && <video className="shot-video" src={`${urlMidia(s.arquivo.pasta, s.arquivo.nome)}#t=0.8`} controls playsInline preload="metadata" />}
        </li>
      })}</ul>
      {waiting && <p className="progress-note" role="status">Gerando no Dreamina. O Estúdio confere sozinho a cada poucos segundos e baixa quando ficar pronto.</p>}
      {ready && <div className="next-step"><p><strong>Todas as tomadas prontas.</strong> Agora é montar o vídeo final, sem gastar créditos.</p>
        <button className="primary-button" disabled={active} onClick={() => void action(() => processo.montar(producao.id))}>{active ? 'Montando…' : 'Montar vídeo · sem créditos'}</button></div>}
      {!ready && !waiting && pending.length > 0 && <div className="next-step">
        <div className="cost-heading"><span>Próximo lote: {lote.map(s => s.titulo).join(' + ')}</span>
          <strong>{cotacaoAtual ? `${cotacaoAtual.total.toLocaleString('pt-BR')} créditos` : 'Ainda não cotado'}</strong></div>
        {pending.length > 1 && <label className="pilot-choice"><input type="checkbox" checked={teste} disabled={active} onChange={e => setTeste(e.target.checked)} />
          Testar primeiro só uma tomada, antes de pagar as outras.</label>}
        {cotacaoAtual && <label className="field">Meu teto para este lote (créditos)
          <input type="number" min={cotacaoAtual.total} placeholder={String(cotacaoAtual.total)} value={teto} onChange={e => setTeto(e.target.value)} /></label>}
        <div className="card-buttons">
          <button className="secondary-button" disabled={active} onClick={() => void action(() => processo.cotar(producao.id, lote.map(s => s.id)))}>
            {active ? 'Aguarde…' : cotacaoAtual ? 'Consultar de novo' : 'Consultar custo real'}</button>
          {cotacaoAtual && <button className="primary-button" disabled={active || Number(teto) < cotacaoAtual.total}
            onClick={() => void action(() => processo.gerar(producao, Number(teto)))}>Autorizar e gerar · {cotacaoAtual.total} créditos</button>}
        </div>
        {cotacaoAtual && Number(teto) < cotacaoAtual.total && <small>Digite um teto de pelo menos {cotacaoAtual.total} para liberar a geração.</small>}
      </div>}
      {waiting && <div className="card-buttons"><button className="secondary-button" disabled={active} onClick={() => void action(() => processo.acompanhar(producao.id))}>{active ? 'Conferindo…' : 'Conferir agora'}</button></div>}
      <small>Consultar o preço não gera vídeo nem gasta créditos. Só "Autorizar e gerar" gasta, até o teto que você digitar.</small>
    </>}
    {bloco.tipo === 'edicao' && <><p>Texto, faixa e cortes mudam localmente, aproveitando os vídeos.</p><div className="card-buttons">
      <button className="secondary-button" onClick={() => abrir(bloco)}>Editar texto e faixa</button>
      <button className="primary-button" disabled={active || !ready} onClick={() => void action(() => processo.montar(producao.id))}>{active ? 'Montando…' : 'Montar vídeo · sem créditos'}</button></div>
      {!ready && <small>As tomadas precisam estar baixadas antes de montar.</small>}</>}
    {bloco.tipo === 'resultado' && (producao.resultado ? <><video className="result-video" src={`${urlResultado(producao.id)}?v=${producao.resultado.nome}`} controls playsInline preload="metadata" />
      <div className="card-buttons"><a className="primary-button" href={urlResultado(producao.id)} download>Baixar vídeo</a>
        <button className="secondary-button" onClick={() => void navigator.clipboard.writeText(producao.legenda)}>Copiar legenda</button></div>
      <p className="caption-preview">{producao.legenda}</p></> : <p>A montagem ainda não foi concluída.</p>)}
    {bloco.tipo === 'imagem' && bloco.referencias && bloco.pasta === 'referencias' && <div className="reference-grid">
      {bloco.nomes?.map(nome => <figure key={nome}>
        <a href={urlMidia('referencias', nome)} target="_blank" rel="noreferrer"><img src={urlMidia('referencias', nome)} alt={`Referência do Pinterest: ${bloco.termo ?? ''}`} loading="lazy" /></a>
        <figcaption><button className="secondary-button" disabled={active} onClick={() => void action(() => processo.usarImagem(producao.id, { pasta: 'referencias', nome }, 'quadro'))}>Usar como quadro</button>
          <button className="secondary-button" disabled={active} onClick={() => void action(() => processo.usarImagem(producao.id, { pasta: 'referencias', nome }, 'recriar'))}>GPT recria</button></figcaption>
      </figure>)}</div>}
    {bloco.tipo === 'imagem' && bloco.pasta && !bloco.referencias && (bloco.descartado ? <p className="discarded-note">Imagem descartada (está na pasta lixeira).</p> : <>
      <div className="generated-images">{bloco.nomes?.map(nome => <a key={nome} href={urlMidia(bloco.pasta!, nome)} target="_blank" rel="noreferrer">
        <img src={urlMidia(bloco.pasta!, nome)} alt="Imagem gerada" /></a>)}</div>
      {bloco.gerada && <div className="card-buttons"><button className="secondary-button" disabled={active} onClick={() => responder('gera outra versão')}>Outra versão</button>
        {bloco.nomes?.map(nome => <button key={nome} className="secondary-button" disabled={active}
          onClick={() => void action(() => processo.descartar(producao.id, { pasta: bloco.pasta!, nome }))}>Descartar</button>)}</div>}
      {bloco.gerada && <small>Salva em {bloco.pasta} na biblioteca.</small>}</>)}
    {bloco.tipo === 'narracao' && <CartaoNarracao producao={producao} atualizar={atualizar} />}
    {bloco.tipo === 'conexao' && <p>Abra o OpenClaw com a assinatura conectada. Depois, envie sua mensagem novamente. A produção está salva.</p>}
    {erro && <p role="alert" className="error-message">{erro}</p>}
  </section>
}
