import { useEffect, useRef, useState } from 'react'
import CartaoProducao from '@/components/CartaoProducao'
import EdicaoConversa from '@/components/EdicaoConversa'
import GaleriaConversa from '@/components/GaleriaConversa'
import PlanoConversa from '@/components/PlanoConversa'
import ConversaModal from '@/components/ConversaModal'
import { useConversa } from '@/hooks/useConversa'
import { urlMidia } from '@/lib/processo'
import type { Bloco } from '@/types/processo'
import './conversa.css'

export default function App() {
  const chat = useConversa()
  const [texto, setTexto] = useState('')
  const [modal, setModal] = useState<Bloco | null>(null)
  const [painel, setPainel] = useState<Bloco | null>(null)
  const [historico, setHistorico] = useState(false)
  const [conectar, setConectar] = useState(false)
  const fim = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const p = chat.producao
  useEffect(() => { fim.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [p?.mensagens.length, chat.pensando, painel])
  const abrir = (block: Bloco) => {
    if (['galeria', 'upload', 'plano', 'edicao'].includes(block.tipo)) setModal(block)
    else setPainel(block)
  }
  const enviar = async (value: string) => { if (!value.trim()) return; setTexto(''); await chat.enviar(value); input.current?.focus() }
  const refs = [p?.master, p?.referencia].filter(a => !!a)
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
        <span>{chat.ia ? 'OpenClaw conectado' : chat.ia === null ? 'Verificando conexão…' : 'OpenClaw desconectado'}<small>Conversa pela sua assinatura</small></span></div>
    </aside>
    <main className="conversation-main">
      <header className="chat-header"><div><span className="eyebrow">PRODUÇÃO EM CONVERSA</span><h1>{p?.nome ?? 'O que vamos criar hoje?'}</h1></div>
        <div className="header-actions"><button className="secondary-button" onClick={() => setConectar(true)}>{chat.ia ? 'OpenClaw ✓' : 'Conectar IA'}</button>
        <button className="secondary-button" onClick={() => setModal({ tipo: 'galeria', titulo: 'Sua biblioteca', pasta: 'movimentos' })}>Biblioteca ↗</button></div></header>
      <div className="chat-layout"><section className="chat-column" aria-label="Chat com a diretora de produção">
        <div className="chat-feed" aria-busy={chat.pensando || chat.carregando}>
          {chat.carregando && <p className="loading-message">Abrindo suas conversas…</p>}
          {!chat.carregando && !p?.mensagens.length && <div className="chat-welcome"><span className="eyebrow">COMECE PELA IDEIA</span>
            <h2>Você imagina.<br /><em>A gente constrói.</em></h2><p>Me conte o vídeo que quer fazer. Quando precisar de uma referência ou de uma escolha sua, eu mostro aqui.</p>
            <div className="starter-prompts">{['Quero transformar um look de verão em outono.', 'Tenho uma referência de movimento para usar.', 'Quero mudar o texto de um vídeo pronto.'].map(value =>
              <button key={value} onClick={() => void enviar(value)}>{value} <span>↗</span></button>)}</div></div>}
          {p?.mensagens.map(message => <article className={`chat-message ${message.papel}`} key={message.id}>
            <span className="message-author">{message.papel === 'user' ? 'Você' : 'Direção Ellie'}</span><p>{message.texto}</p>
            {message.blocos?.map((block, index) => card(block, `${message.id}-${index}`))}</article>)}
          {chat.pensando && <p className="thinking-message" role="status">A diretora está montando a próxima parte…</p>}
          {p?.ocupado && <p className="thinking-message" role="status">Processando sua produção. Pode acompanhar por aqui.</p>}
          {p?.erro && !chat.pensando && <p className="error-message" role="alert">{p.erro}</p>}
          {chat.erro && <p className="error-message" role="alert">{chat.erro}</p>}
          {painel && card(painel, 'painel-atual')}
          {p?.resultado && card({ tipo: 'resultado', titulo: 'Seu vídeo' }, `resultado-${p.resultado.nome}`)}
          <div ref={fim} />
        </div>
        <div className="composer-wrap">
          {p && <nav className="context-actions" aria-label="Controles da conversa">
            <button onClick={() => setModal({ tipo: 'galeria', titulo: 'Escolher referência', pasta: 'movimentos' })}>+ Referência</button>
            <button onClick={() => abrir({ tipo: 'plano' })}>Estrutura</button><button onClick={() => abrir({ tipo: 'custo', titulo: 'Orçamento da produção' })}>Custo e geração</button>
            <button onClick={() => { setPainel({ tipo: 'edicao', titulo: 'Montagem local' }); abrir({ tipo: 'edicao' }) }}>Texto e montagem</button></nav>}
          <form className="chat-composer" onSubmit={e => { e.preventDefault(); void enviar(texto) }}>
            <label className="sr-only" htmlFor="chat-message">Sua mensagem para a IA</label><textarea id="chat-message" ref={input} rows={2}
              placeholder="Me conta sua ideia, manda uma referência ou pede um ajuste…" value={texto} maxLength={6000}
              onChange={e => setTexto(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!chat.pensando && !p?.ocupado) void enviar(texto) } }} />
            <button className="send-button" type="submit" aria-label="Enviar mensagem" disabled={!texto.trim() || chat.pensando || p?.ocupado}>↑</button>
          </form><p className="composer-note">Conversa pela assinatura do OpenClaw. Geração de vídeo só com seu custo aprovado.</p>
        </div>
      </section>
      <aside className="production-context" aria-label="Contexto da produção"><span className="eyebrow">O QUE JÁ TEMOS</span>
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
