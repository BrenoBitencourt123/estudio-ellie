import { useEffect, useRef, useState } from 'react'
import CartaoProducao from '@/components/CartaoProducao'
import Cronometro, { duracao } from '@/components/Cronometro'
import EtapasProducao from '@/components/EtapasProducao'
import EdicaoConversa from '@/components/EdicaoConversa'
import GaleriaConversa from '@/components/GaleriaConversa'
import PlanoConversa from '@/components/PlanoConversa'
import ConversaModal from '@/components/ConversaModal'
import { useConversa } from '@/hooks/useConversa'
import { useAnexos } from '@/hooks/useAnexos'
import { processo, urlMidia } from '@/lib/processo'
import type { Bloco, MensagemChat, Trabalho, UsoIA } from '@/types/processo'
import './conversa.css'

// Linha discreta sob cada resposta: qual modelo respondeu, quanto do contexto foi enviado e quanto demorou
function medidor(ia: UsoIA) {
  const u = (ia.usage ?? {}) as Record<string, unknown>
  const num = (k: string) => typeof u[k] === 'number' ? (u[k] as number) : 0
  const entrada = num('input') || num('inputTokens') || num('prompt_tokens')
  const saida = num('output') || num('outputTokens') || num('completion_tokens')
  const cache = num('cacheRead') || num('cache_read') || num('cacheReadTokens')
  const k = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
  const partes = [ia.modelo?.split('/').pop(), ia.modo === 'delta' ? 'só o que mudou' : ia.modo === 'completo' ? 'contexto completo' : '',
    entrada || saida ? `${k(entrada)} → ${k(saida)} tokens${cache ? ` (${k(cache)} em cache)` : ''}` : ia.caracteres ? `${k(ia.caracteres)} caracteres enviados` : '',
    ia.segundos ? `${ia.segundos.toFixed(1)}s` : '', ia.tentativas ? 'reserva assumiu' : '']
  return partes.filter(Boolean).join(' · ')
}

// Hora de cada mensagem e, nas respostas, quanto tempo levou desde a mensagem anterior do Breno
const hora = (iso: string) => new Date(iso).toLocaleTimeString('pt-BR')
function tempoResposta(mensagens: MensagemChat[], i: number) {
  if (mensagens[i].papel !== 'assistant') return ''
  for (let j = i - 1; j >= 0; j--) {
    if (mensagens[j].papel === 'user') {
      const s = (new Date(mensagens[i].criado).getTime() - new Date(mensagens[j].criado).getTime()) / 1000
      return s >= 0 ? ` · respondeu em ${duracao(s)}` : ''
    }
  }
  return ''
}

// O que está sendo feito agora, em paralelo: cada faixa aparece com o próprio relógio e o chat segue livre.
function TrabalhosEmCurso({ trabalhos }: { trabalhos: Trabalho[] }) {
  const visiveis = trabalhos.filter(t => t.faixa !== 'conversa')
  if (!visiveis.length) return null
  return <div className="running-jobs" role="status" aria-live="polite">
    {visiveis.map(t => <span key={t.id} className={`job-chip job-${t.faixa}`}>
      <span className="job-pulse" aria-hidden="true" />{t.rotulo}… <Cronometro desde={Date.parse(t.iniciado)} />
    </span>)}
  </div>
}

export default function App() {
  const chat = useConversa()
  const [avisoAudio, setAvisoAudio] = useState('')
  // Áudio arrastado/colado vira a narração do vídeo (sincroniza a legenda com o texto do roteiro)
  const colados = useAnexos(file => {
    const atual = chat.producao
    if (!atual) { setAvisoAudio('Comece a conversa do vídeo antes de enviar o áudio da narração.'); return }
    setAvisoAudio('Enviando e sincronizando o áudio…')
    void processo.enviarAudio(atual.id, file, atual.narracao?.texto ?? '', atual.narracao?.setas ?? true)
      .then(() => { setAvisoAudio(''); void chat.atualizar() })
      .catch(e => setAvisoAudio(e instanceof Error ? e.message : 'O áudio não foi enviado.'))
  })
  const [abrindoPainel, setAbrindoPainel] = useState(false)
  // Abre a aba já no clique (senão o navegador bloqueia o pop-up) e depois aponta para o link de uso único do OpenClaw
  const abrirPainel = async () => {
    const aba = window.open('', '_blank')
    if (aba) aba.document.write('<p style="font:16px system-ui;padding:24px">Abrindo o painel do OpenClaw…</p>')
    setAbrindoPainel(true); setAvisoAudio('Abrindo o painel do OpenClaw…')
    try {
      const { url, aviso } = await processo.painelOpenclaw()
      if (aba && !aba.closed) aba.location.replace(url); else window.open(url, '_blank')
      setAvisoAudio(aviso ?? '')
    } catch (e) {
      // Mesmo se o Estúdio falhar, tenta o endereço padrão do painel em vez de deixar a aba vazia
      if (aba && !aba.closed) aba.location.replace('http://127.0.0.1:18789/')
      setAvisoAudio(e instanceof Error ? e.message : 'O painel do OpenClaw não abriu.')
    }
    finally { setAbrindoPainel(false) }
  }
  const [arrastando, setArrastando] = useState(false)
  const arquivo = useRef<HTMLInputElement>(null)
  // O texto digitado sobrevive a uma recarga automática (atualização do sistema)
  const [texto, setTexto] = useState(() => { try { return sessionStorage.getItem('ellie-rascunho') ?? '' } catch { return '' } })
  const [modal, setModal] = useState<Bloco | null>(null)
  const [painel, setPainel] = useState<Bloco | null>(null)
  const [historico, setHistorico] = useState(false)
  const [conectar, setConectar] = useState(false)
  const fim = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const p = chat.producao
  useEffect(() => { fim.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [p?.mensagens.length, chat.pensando, chat.aoVivo, painel])
  const abrir = (block: Bloco) => {
    if (['galeria', 'upload', 'plano', 'edicao'].includes(block.tipo)) setModal(block)
    else setPainel(block)
  }
  const enviar = async (value: string) => {
    const anexos = colados.prontos
    if ((!value.trim() && !anexos.length) || colados.enviando) return
    setTexto(''); colados.limpar()
    await chat.enviar(value.trim(), undefined, anexos); input.current?.focus()
  }
  // Atualização sem reiniciar: quando a interface compilada muda, recarrega assim que estiver livre
  const versao = useRef(0)
  const livre = useRef(true)
  livre.current = !chat.pensando && !p?.ocupado && !modal && !colados.anexos.length
  useEffect(() => {
    try { sessionStorage.removeItem('ellie-rascunho') } catch { /* sem armazenamento */ }
    const timer = setInterval(() => {
      void fetch('/api/versao').then(r => r.ok ? r.json() : null).then((v: { interface?: number } | null) => {
        if (!v?.interface) return
        if (!versao.current) { versao.current = v.interface; return }
        if (v.interface !== versao.current && livre.current) {
          try { sessionStorage.setItem('ellie-rascunho', input.current?.value ?? '') } catch { /* segue */ }
          location.reload()
        }
      }).catch(() => undefined)
    }, 4000)
    return () => clearInterval(timer)
  }, [])
  // Só a resposta anterior ainda chegando impede enviar: imagem, voz e montagem correm em paralelo
  const podeEnviar = (!!texto.trim() || colados.prontos.length > 0) && !colados.enviando && !chat.pensando
  const refs = [p?.master, p?.referencia, ...(p?.tomadas ?? []).map(s => s.imagens[0]).filter(a => a && a.pasta !== 'base')].filter(a => !!a).slice(0, 4)
  const card = (block: Bloco, key: string) => p && <CartaoProducao key={key} bloco={block} producao={p} abrir={abrir}
    responder={value => void enviar(value)} atualizar={chat.atualizar} />
  return <div className="studio-chat">
    <aside className="conversation-sidebar" aria-label="Conversas de produção">
      <a className="studio-brand" href="#" onClick={e => { e.preventDefault(); chat.nova() }}>estúdio <em>ellie.</em></a>
      <p className="brand-note">Da referência ao vídeo,<br />numa conversa.</p>
      <button className="primary-button new-conversation" onClick={chat.nova}>+ Novo vídeo</button>
      <button className="secondary-button mobile-history" onClick={() => setHistorico(true)}>Conversas</button>
      <span className="eyebrow history-label">SUAS PRODUÇÕES</span>
      <nav className="conversation-list">{chat.producoes.map(item => <button key={item.id} aria-current={p?.id === item.id ? 'page' : undefined}
        onClick={() => { void chat.abrir(item.id); setPainel(null) }}><span>{item.nome}</span><small>{item.resultado ? 'Vídeo disponível' : 'Conversa salva'}</small></button>)}</nav>
      <div className="sidebar-footer"><span className={`connection-dot ${chat.ia ? 'online' : ''}`} />
        <span>{chat.ia ? 'OpenClaw conectado' : chat.ia === null ? 'Verificando conexão…' : 'OpenClaw desconectado'}<small>{chat.modelos.length ? chat.modelos.map(m => m.split('/').pop()).join(' → ') : 'Conversa pela sua assinatura'}</small></span></div>
    </aside>
    <main className="conversation-main">
      <header className="chat-header"><div><span className="eyebrow">PRODUÇÃO EM CONVERSA</span><h1>{p?.nome ?? 'O que vamos criar hoje?'}</h1></div>
        <div className="header-actions"><button className="secondary-button" onClick={() => setConectar(true)}>{chat.ia ? 'OpenClaw ✓' : 'Conectar IA'}</button>
        <button className="secondary-button" disabled={abrindoPainel} title="Conectores, agentes e sessões do OpenClaw" onClick={() => void abrirPainel()}>{abrindoPainel ? 'Abrindo…' : 'Painel OpenClaw ↗'}</button>
        <button className="secondary-button" onClick={() => setModal({ tipo: 'galeria', titulo: 'Sua biblioteca', pasta: 'movimentos' })}>Biblioteca ↗</button></div></header>
      <div className="chat-layout"><section className="chat-column" aria-label="Chat com a diretora de produção">
        <div className="chat-feed" aria-busy={chat.pensando || chat.carregando}>
          {chat.carregando && <p className="loading-message">Abrindo suas conversas…</p>}
          {!chat.carregando && !p?.mensagens.length && <div className="chat-welcome"><span className="eyebrow">COMECE PELA IDEIA</span>
            <h2>Você imagina.<br /><em>A gente constrói.</em></h2><p>Me conte o vídeo que quer fazer. Quando precisar de uma referência ou de uma escolha sua, eu mostro aqui.</p>
            <div className="starter-prompts">{['Tenho uma ideia de vídeo, me ajuda a montar.', 'Me sugere 3 ideias diferentes das últimas que fizemos.', 'Vou colar uma imagem de referência para a cena.'].map(value =>
              <button key={value} onClick={() => void enviar(value)}>{value} <span>↗</span></button>)}</div></div>}
          {p?.mensagens.map((message, i) => <article className={`chat-message ${message.papel}`} key={message.id}>
            <span className="message-author">{message.papel === 'user' ? 'Você' : 'Direção Ellie'}<time className="message-time">{hora(message.criado)}{tempoResposta(p.mensagens, i)}</time></span>{message.texto && <p>{message.texto}</p>}
            {!!message.anexos?.length && <div className="message-attachments">{message.anexos.map(a =>
              <img key={a.nome} src={urlMidia(a.pasta, a.nome)} alt="Imagem colada" />)}</div>}
            {message.blocos?.map((block, index) => card(block, `${message.id}-${index}`))}
            {message.ia && <small className="usage-meter">{medidor(message.ia)}</small>}</article>)}
          {chat.pensando && (chat.aoVivo
            ? <article className="chat-message assistant live"><span className="message-author">Direção Ellie<time className="message-time"><Cronometro desde={chat.inicio} /></time></span><p>{chat.aoVivo}<span className="caret" /></p></article>
            : <p className="thinking-message" role="status">A diretora está montando a próxima parte… <Cronometro desde={chat.inicio} /></p>)}
          <TrabalhosEmCurso trabalhos={p?.trabalhos ?? []} />
          {p?.erro && !chat.pensando && <p className="error-message" role="alert">{p.erro}</p>}
          {chat.erro && <p className="error-message" role="alert">{chat.erro}</p>}
          {avisoAudio && <p className="thinking-message" role="status">{avisoAudio}</p>}
          {painel && card(painel, 'painel-atual')}
          {p?.resultado && card({ tipo: 'resultado', titulo: 'Seu vídeo' }, `resultado-${p.resultado.nome}`)}
          <div ref={fim} />
        </div>
        <div className="composer-wrap">
          {p && <nav className="context-actions" aria-label="Controles da conversa">
            <button onClick={() => setModal({ tipo: 'galeria', titulo: 'Escolher referência', pasta: 'movimentos' })}>+ Referência</button>
            <button onClick={() => abrir({ tipo: 'narracao', titulo: 'Narração' })}>Narração</button>
            <button onClick={() => { setTexto('busca no pinterest '); input.current?.focus() }}>Pinterest</button>
            <button onClick={() => abrir({ tipo: 'plano' })}>Estrutura</button><button onClick={() => abrir({ tipo: 'custo', titulo: 'Orçamento da produção' })}>Custo e geração</button>
            <button onClick={() => { setPainel({ tipo: 'edicao', titulo: 'Montagem local' }); abrir({ tipo: 'edicao' }) }}>Texto e montagem</button></nav>}
          {!!colados.anexos.length && <div className="attachment-chips" aria-label="Imagens coladas">{colados.anexos.map(a =>
            <div className={`attachment-chip ${a.erro ? 'failed' : a.asset ? '' : 'uploading'}`} key={a.id} title={a.erro ?? a.asset?.nome ?? 'Enviando…'}>
              <img src={a.url} alt="" /><button type="button" aria-label="Remover imagem" onClick={() => colados.remover(a.id)}>×</button></div>)}
            <small>{colados.enviando ? 'Subindo…' : 'Diga o que fazer com a imagem (quadro, cenário, roupa…) ou só envie.'}</small></div>}
          <form className={`chat-composer ${arrastando ? 'dragging' : ''}`} onSubmit={e => { e.preventDefault(); void enviar(texto) }}
            onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setArrastando(true) } }}
            onDragLeave={() => setArrastando(false)}
            onDrop={e => { e.preventDefault(); setArrastando(false); colados.adicionar([...e.dataTransfer.files]) }}>
            <button type="button" className="attach-button" aria-label="Anexar imagem" onClick={() => arquivo.current?.click()}>+</button>
            <input ref={arquivo} type="file" accept="image/png,image/jpeg,image/webp,audio/*,.mp3,.wav,.m4a" multiple hidden onChange={e => { colados.adicionar([...(e.target.files ?? [])]); e.target.value = '' }} />
            <label className="sr-only" htmlFor="chat-message">Sua mensagem para a IA</label><textarea id="chat-message" ref={input} rows={2}
              placeholder='Me conta a ideia, cola uma imagem (Ctrl+V) ou arrasta o áudio da narração…' value={texto} maxLength={6000}
              onChange={e => setTexto(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (podeEnviar) void enviar(texto) } }} />
            <button className="send-button" type="submit" aria-label="Enviar mensagem" disabled={!podeEnviar}>↑</button>
          </form><p className="composer-note">Conversa pela assinatura do OpenClaw. Geração de vídeo só com seu custo aprovado.</p>
        </div>
      </section>
      <aside className="production-context" aria-label="Contexto da produção">
        {p && <EtapasProducao producao={p} />}
        <span className="eyebrow">O QUE JÁ TEMOS</span>
        <h2>{p ? 'Nossa base' : 'Tudo no contexto'}</h2><p>As escolhas ficam salvas junto da conversa.</p>
        {refs.map((asset, i) => <div className="context-reference" key={`${asset.pasta}-${asset.nome}`}>
          {asset.pasta === 'movimentos' ? <video src={urlMidia(asset.pasta, asset.nome)} controls preload="metadata" /> : <img src={urlMidia(asset.pasta, asset.nome)} alt="Modelo aprovada para esta produção" />}
          <div><span>{i === 0 && p?.master ? 'Modelo' : 'Movimento'}</span><small>{asset.nome}</small></div></div>)}
        {!refs.length && <div className="context-empty">As referências aparecem aqui conforme a gente escolhe.</div>}
        {p && <><dl className="production-facts"><div><dt>Vídeo final</dt><dd>{p.duracao_final}s · vertical</dd></div>
          <div><dt>Tomadas</dt><dd>{p.tomadas.length} · {p.tomadas.reduce((sum, shot) => sum + shot.duracao, 0)}s brutos</dd></div>
          <div><dt>Cotação atual</dt><dd>{p.cotacao ? `${p.cotacao.total} créditos` : 'Não consultada'}</dd></div></dl>
          {p.canvas_url && <a className="text-link" href={p.canvas_url} target="_blank" rel="noreferrer">Abrir canvas Dreamina ↗</a>}
          <p className="context-small">Dreamina: {chat.dreamina ? 'conectado' : 'conexão pendente'}. Edição de textos e cortes não consome créditos de vídeo.</p></>}
      </aside></div>
    </main>
    {modal && ['galeria', 'upload'].includes(modal.tipo) && <GaleriaConversa bloco={modal} biblioteca={chat.biblioteca} producao={p}
      fechar={() => setModal(null)} atualizar={chat.atualizarBiblioteca} escolher={async selection => {
        await chat.enviar(`Vamos usar ${selection.asset.nome} como ${selection.papel}.`, selection)
      }} />}
    {modal?.tipo === 'plano' && p && <PlanoConversa producao={p} biblioteca={chat.biblioteca} fechar={() => setModal(null)} salvar={chat.salvar} />}
    {modal?.tipo === 'edicao' && p && <EdicaoConversa producao={p} fechar={() => setModal(null)} salvar={chat.salvar} />}
    {conectar && <ConversaModal titulo="Conectar o OpenClaw" fechar={() => setConectar(false)}><div className="connection-guide">
      <p>O OpenClaw precisa estar instalado e aberto no computador que vai executar a IA.</p>
      <ol><li><strong>Entre na sua assinatura no OpenClaw.</strong> No assistente oficial, escolha o login ChatGPT/Codex ou Claude CLI. Se ele detectar uma chave de API, confira a opção antes de continuar.</li>
      <li><strong>Registre o agente do Estúdio.</strong> Na pasta do projeto, execute <code>python configurar_openclaw.py --executar</code>. Ele preserva os outros agentes e contas.</li>
      <li><strong>Confira a conta do agente.</strong> Use <code>openclaw models status --agent ellie-studio</code>. Se faltar o login ChatGPT, use <code>openclaw models auth login --provider openai --agent ellie-studio</code> e conclua o acesso no navegador.</li>
      <li><strong>Claude no chat (opcional).</strong> <code>claude auth login</code>, depois <code>openclaw models auth login --provider anthropic --method cli --agent ellie-studio</code>. No <code>.env</code>, defina <code>OPENCLAW_MODELO_CHAT</code> (Claude) e <code>OPENCLAW_MODELO_RESERVA</code> (GPT) com os IDs de <code>openclaw models list</code>.</li>
      <li><strong>Deixe o Gateway aberto e verifique aqui.</strong> Depois envie uma mensagem no chat para testar a resposta real da assinatura.</li></ol>
      <p className="field-note">Se o OpenClaw estiver numa VPS ou no WSL, é preciso configurar a ponte e o acesso ao Gateway desse ambiente. Não cole tokens na conversa.</p>
      <a className="text-link" href="https://docs.openclaw.ai/start/getting-started" target="_blank" rel="noreferrer">Instalação e login oficiais ↗</a>
      <p className={chat.ia ? 'success-note' : 'field-note'} role="status">{chat.conexaoDetalhe || 'Verifique a conexão depois de abrir o Gateway.'}</p>
      <button className="primary-button" disabled={chat.verificandoConexao} onClick={() => void chat.verificarConexao()}>{chat.verificandoConexao ? 'Verificando…' : 'Verificar conexão'}</button>
      <p className="field-note">Gateway conectado confirma a comunicação. A assinatura é confirmada quando o modelo responde; créditos de vídeo são separados.</p>
    </div></ConversaModal>}
    {historico && <ConversaModal titulo="Suas conversas" fechar={() => setHistorico(false)}><nav className="history-modal-list">
      {chat.producoes.map(item => <button className="secondary-button" key={item.id} onClick={() => {
        void chat.abrir(item.id); setHistorico(false); setPainel(null)
      }}>{item.nome}</button>)}
      {!chat.producoes.length && <p>A primeira conversa aparece aqui assim que você começar um vídeo.</p>}
    </nav></ConversaModal>}
  </div>
}
