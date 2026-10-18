import { useCallback, useEffect, useRef, useState } from 'react'
import { processo } from '@/lib/processo'
import type { Biblioteca, Midia, Producao, Selecao } from '@/types/processo'

const vazia: Biblioteca = { persona: [], base: [], pecas: [], cenarios: [], movimentos: [], saida: [], anexos: [] }
export function useConversa() {
  const [producoes, setProducoes] = useState<Producao[]>([])
  const [producao, setProducao] = useState<Producao | null>(null)
  const [biblioteca, setBiblioteca] = useState<Biblioteca>(vazia)
  const [carregando, setCarregando] = useState(true)
  const [pensando, setPensando] = useState(false)
  const [erro, setErro] = useState('')
  const [aoVivo, setAoVivo] = useState('')
  const [inicio, setInicio] = useState(0)
  const [ia, setIa] = useState<boolean | null>(null)
  const [modelos, setModelos] = useState<string[]>([])
  const [conexaoDetalhe, setConexaoDetalhe] = useState('')
  const [verificandoConexao, setVerificandoConexao] = useState(false)
  const [dreamina, setDreamina] = useState<boolean | null>(null)
  const atual = useRef<Producao | null>(null)
  const ultimaConsulta = useRef(0)
  const salvar = useCallback((p: Producao) => {
    atual.current = p; setProducao(p)
    setProducoes(list => [p, ...list.filter(other => other.id !== p.id)])
  }, [])
  const abrir = useCallback(async (id: string) => {
    try { salvar(await processo.obter(id)); setErro('') }
    catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui abrir a conversa.') }
  }, [salvar])
  const atualizarBiblioteca = useCallback(async () => setBiblioteca(await processo.biblioteca()), [])
  const atualizar = useCallback(async () => { if (atual.current) salvar(await processo.obter(atual.current.id)) }, [salvar])
  const verificarConexao = useCallback(async () => {
    setVerificandoConexao(true)
    try {
      const response = await fetch('/api/ia/status')
      if (!response.ok) throw new Error('A ponte do Estúdio não respondeu.')
      const status = await response.json()
      setIa(!!status.conectado && !!status.existe)
      setModelos(Array.isArray(status.modelos) ? status.modelos : [])
      setConexaoDetalhe(status.conectado && !status.existe
        ? `O Gateway respondeu, mas o agente ${status.agente ?? 'ellie-studio'} ainda não foi registrado.`
        : status.erro || 'Gateway e agente encontrados. Envie uma mensagem para verificar o modelo e a assinatura.')
    } catch (error) {
      setIa(false)
      setConexaoDetalhe(error instanceof Error ? error.message : 'Não consegui verificar a conexão.')
    } finally { setVerificandoConexao(false) }
  }, [])
  useEffect(() => {
    void Promise.all([processo.listar(), processo.biblioteca()]).then(([ps, b]) => {
      setProducoes(ps); setBiblioteca(b)
      const id = localStorage.getItem('ellie-producao-atual')
      if (id && ps.some(p => p.id === id)) salvar(ps.find(p => p.id === id)!)
    }).catch(() => setErro('O Estúdio não respondeu. Abra o iniciar.ps1 e tente novamente.')).finally(() => setCarregando(false))
    void verificarConexao()
    void processo.status().then(v => setDreamina(v.dreamina.conectado)).catch(() => setDreamina(false))
  }, [salvar, verificarConexao])
  useEffect(() => { if (producao) localStorage.setItem('ellie-producao-atual', producao.id) }, [producao?.id])
  useEffect(() => {
    const timer = setInterval(() => {
      const p = atual.current
      if (!p || pensando) return
      if (p.ocupado || ['gerando', 'envio_incerto'].includes(p.status)) {
        void processo.obter(p.id).then(async fresh => {
          if (atual.current?.id !== fresh.id) return
          salvar(fresh)
          if (!fresh.ocupado && ['gerando', 'envio_incerto'].includes(fresh.status) && Date.now() - ultimaConsulta.current > 12000) {
            ultimaConsulta.current = Date.now(); await processo.acompanhar(fresh.id)
          }
        }).catch(() => undefined)
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [pensando, salvar])
  // Texto da resposta enquanto chega (streaming pela ponte); some quando a resposta final é salva
  useEffect(() => {
    if (!pensando) { setAoVivo(''); return }
    const timer = setInterval(() => {
      const p = atual.current
      if (p) void processo.rascunho(p.id).then(r => setAoVivo(r.texto)).catch(() => undefined)
    }, 500)
    return () => clearInterval(timer)
  }, [pensando])
  const nova = () => { atual.current = null; setProducao(null); setErro(''); localStorage.removeItem('ellie-producao-atual') }
  const enviar = async (texto: string, selecao?: Selecao, anexos: Midia[] = []) => {
    if (pensando || atual.current?.ocupado) return
    setPensando(true); setErro(''); setInicio(Date.now())
    try {
      let p = atual.current
      if (!p) { p = await processo.criar(texto.slice(0, 75) || (anexos.length ? 'Imagem colada' : 'Novo vídeo')); salvar(p) }
      // Mostra a mensagem na hora; a resposta do servidor substitui esta cópia local
      const local = { id: `local-${Date.now()}`, papel: 'user' as const, texto: texto || (selecao ? `Escolhi ${selecao.asset.nome}` : ''), anexos, criado: new Date().toISOString() }
      salvar({ ...p, mensagens: [...p.mensagens, local] })
      salvar(await processo.conversar(p.id, texto, selecao, anexos))
      if (anexos.length) void atualizarBiblioteca()
    } catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui enviar a mensagem.'); await atualizar().catch(() => undefined) }
    finally { setPensando(false) }
  }
  return { producoes, producao, biblioteca, carregando, pensando, inicio, aoVivo, modelos, erro, ia, dreamina, conexaoDetalhe, verificandoConexao, verificarConexao, salvar, abrir, atualizar, atualizarBiblioteca, nova, enviar }
}
