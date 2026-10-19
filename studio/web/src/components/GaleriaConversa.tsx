import { useState } from 'react'
import { processo, urlMidia } from '@/lib/processo'
import type { Biblioteca, Bloco, PastaMidia, Producao, Selecao } from '@/types/processo'
import ConversaModal from './ConversaModal'

const nomes: Record<PastaMidia, string> = { persona: 'Modelo', base: 'Estados do look', pecas: 'Peças', cenarios: 'Cenários', movimentos: 'Movimento', saida: 'Vídeos prontos', anexos: 'Colados', quadros: 'Quadros iniciais', referencias: 'Pinterest' }
export default function GaleriaConversa({ bloco, biblioteca, producao, escolher, fechar, atualizar }: {
  bloco: Bloco; biblioteca: Biblioteca; producao: Producao | null
  escolher: (s: Selecao) => Promise<void>; fechar: () => void; atualizar: () => Promise<void>
}) {
  const [pasta, setPasta] = useState<PastaMidia>(bloco.pasta ?? 'movimentos')
  const [tomada, setTomada] = useState(producao?.tomadas[0]?.id ?? '')
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)
  const papel = pasta === 'movimentos' ? 'movimento' : pasta === 'persona' ? 'master' : pasta === 'saida' ? 'bruto' : 'estado'
  const escolherArquivo = async (nome: string) => {
    setErro(''); setEnviando(true)
    try { await escolher({ papel, asset: { pasta, nome }, ...(papel === 'bruto' ? { tomada } : {}) }); fechar() }
    catch (e) { setErro(String(e instanceof Error ? e.message : e)) }
    finally { setEnviando(false) }
  }
  return <ConversaModal titulo={bloco.titulo || 'Referências da produção'} fechar={fechar}>
    <nav className="folder-tabs" aria-label="Pastas da biblioteca">{Object.entries(nomes).map(([key, value]) =>
      <button key={key} className={pasta === key ? 'selected' : ''} onClick={() => setPasta(key as PastaMidia)}>{value}</button>)}</nav>
    <div className="upload-row"><p>Escolha uma referência existente ou envie um arquivo.</p>
      <label className="secondary-button upload-label">Enviar arquivo<input type="file" disabled={enviando}
        accept={pasta === 'movimentos' || pasta === 'saida' ? 'video/*' : 'image/*'} onChange={async e => {
          const file = e.target.files?.[0]; if (!file) return
          setEnviando(true); setErro('')
          try { const a = await processo.upload(pasta, file); await atualizar(); setEnviando(false); await escolherArquivo(a.nome) }
          catch (error) { setErro(error instanceof Error ? error.message : 'O envio falhou.'); setEnviando(false) }
        }} /></label></div>
    {papel === 'bruto' && <label className="field">Reaproveitar como<select value={tomada} onChange={e => setTomada(e.target.value)}>
      {producao?.tomadas.map(s => <option value={s.id} key={s.id}>{s.titulo}</option>)}</select></label>}
    {erro && <p className="error-message" role="alert">{erro}</p>}
    <div className="media-gallery">{biblioteca[pasta].map(nome => <article key={nome}>
      {pasta === 'movimentos' || pasta === 'saida'
        ? <video src={urlMidia(pasta, nome)} controls preload="metadata" aria-label={nome} />
        : <img src={urlMidia(pasta, nome)} alt={nome} loading="lazy" />}
      <div><span title={nome}>{nome}</span><button className="secondary-button" disabled={enviando || (papel === 'bruto' && !tomada)} onClick={() => void escolherArquivo(nome)}>
        {enviando ? 'Aguarde…' : 'Usar esta referência'}</button></div>
    </article>)}</div>
    {!biblioteca[pasta].length && <p className="empty-state">Ainda não há arquivos aqui. Envie a referência que quer usar.</p>}
  </ConversaModal>
}
