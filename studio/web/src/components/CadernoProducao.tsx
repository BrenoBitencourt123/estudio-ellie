import { useEffect, useState } from 'react'
import { processo, urlMidia } from '@/lib/processo'
import type { AudioPlano, Ficha, PapelReferencia, Producao, ReferenciaCriativa } from '@/types/processo'

const AUDIOS: { valor: AudioPlano; nome: string; dica: string }[] = [
  { valor: 'narracao', nome: 'Narração', dica: 'Voz por cima. O tempo de cada cena segue a fala.' },
  { valor: 'original', nome: 'Som original', dica: 'O som gerado com cada tomada vai para o vídeo final.' },
  { valor: 'silencioso', nome: 'Sem som', dica: 'Silêncio de propósito (você põe a música no TikTok).' },
  { valor: 'indefinido', nome: 'Ainda não decidi', dica: 'O storyboard só é revisado depois dessa decisão.' },
]
const PAPEIS: { valor: PapelReferencia; nome: string }[] = [
  { valor: 'inspiracao', nome: 'Inspiração geral' }, { valor: 'luz', nome: 'Luz' }, { valor: 'composicao', nome: 'Enquadramento' },
  { valor: 'personagem', nome: 'Personagem' }, { valor: 'cenario', nome: 'Cenário' }, { valor: 'roupa', nome: 'Roupa' },
  { valor: 'movimento', nome: 'Movimento' },
]
const linhas = (texto: string) => texto.split('\n').map(l => l.trim()).filter(Boolean)
const FICHA_VAZIA: Ficha = { publico: '', restricoes: [], criterios: [], audio: 'indefinido' }

// Ficha central da produção: o que vale para todas as cenas e o que cada referência ensina.
// A IA e a geração de imagem leem daqui; o chat só altera.
export default function CadernoProducao({ producao: p, atualizar }: { producao: Producao; atualizar: () => Promise<void> }) {
  const [ficha, setFicha] = useState<Ficha>(p.ficha ?? FICHA_VAZIA)
  const [restricoes, setRestricoes] = useState((p.ficha?.restricoes ?? []).join('\n'))
  const [criterios, setCriterios] = useState((p.ficha?.criterios ?? []).join('\n'))
  const [refs, setRefs] = useState<ReferenciaCriativa[]>(p.referencias_criativas ?? [])
  const [erro, setErro] = useState('')
  const [salvo, setSalvo] = useState(false)
  const [busy, setBusy] = useState(false)
  // Mudança vinda do chat (a IA também edita o caderno): recarrega o formulário
  useEffect(() => {
    setFicha(p.ficha ?? FICHA_VAZIA); setRestricoes((p.ficha?.restricoes ?? []).join('\n'))
    setCriterios((p.ficha?.criterios ?? []).join('\n')); setRefs(p.referencias_criativas ?? [])
  }, [p.versao])
  const ativas = refs.filter(r => r.ativa).length
  const mudar = (id: string, dados: Partial<ReferenciaCriativa>) => { setSalvo(false); setRefs(rs => rs.map(r => r.id === id ? { ...r, ...dados } : r)) }
  const salvar = async () => {
    setBusy(true); setErro('')
    try {
      await processo.salvarCaderno(p, { ...ficha, restricoes: linhas(restricoes), criterios: linhas(criterios) }, refs)
      await atualizar(); setSalvo(true)
    } catch (e) { setErro(e instanceof Error ? e.message : 'O caderno não foi salvo.') }
    finally { setBusy(false) }
  }
  return <div className="notebook">
    <fieldset className="notebook-audio"><legend>Áudio do vídeo</legend>
      {AUDIOS.map(a => <label key={a.valor} className={ficha.audio === a.valor ? 'selected' : ''}>
        <input type="radio" name="audio" checked={ficha.audio === a.valor} onChange={() => { setSalvo(false); setFicha({ ...ficha, audio: a.valor }) }} />
        <strong>{a.nome}</strong><small>{a.dica}</small></label>)}
    </fieldset>
    <label className="field">Para quem é o vídeo
      <input type="text" value={ficha.publico} maxLength={400} placeholder="ex.: cristãos jovens no Reino Unido, que assistem à noite"
        onChange={e => { setSalvo(false); setFicha({ ...ficha, publico: e.target.value }) }} /></label>
    <div className="editor-grid">
      <label className="field">Restrições (uma por linha)
        <textarea rows={3} value={restricoes} placeholder="ex.: sem texto na imagem" onChange={e => { setSalvo(false); setRestricoes(e.target.value) }} /></label>
      <label className="field">O vídeo está bom quando… (uma por linha)
        <textarea rows={3} value={criterios} placeholder="ex.: o rosto de Jesus aparece nos 2 primeiros segundos" onChange={e => { setSalvo(false); setCriterios(e.target.value) }} /></label>
    </div>
    <div className="section-heading"><h3>Referências</h3><span>{ativas} de 12 em uso</span></div>
    <p className="field-note">As referências em uso vão para a IA e para a geração de cada quadro, cada uma só no papel dela. Nenhuma troca o protagonista ou a ação da cena.</p>
    {!refs.length && <p className="field-note">Nenhuma ainda. Busque no Pinterest pelo chat ou cole imagens.</p>}
    <div className="notebook-refs">{refs.map(r => <article key={r.id} className={r.ativa ? 'active' : ''}>
      <img src={urlMidia(r.asset.pasta, r.asset.nome)} alt={`Referência ${r.asset.nome}`} loading="lazy" />
      <div>
        <label className="pilot-choice"><input type="checkbox" checked={r.ativa} disabled={!r.ativa && ativas >= 12}
          onChange={e => mudar(r.id, { ativa: e.target.checked })} /> Usar</label>
        <select aria-label="Papel da referência" value={r.papel} onChange={e => mudar(r.id, { papel: e.target.value as PapelReferencia })}>
          {PAPEIS.map(x => <option key={x.valor} value={x.valor}>{x.nome}</option>)}</select>
        <input type="text" aria-label="O que aproveitar desta referência" placeholder="O que aproveitar dela" value={r.orientacao} maxLength={600}
          onChange={e => mudar(r.id, { orientacao: e.target.value })} />
        {p.tomadas.length > 0 && <details><summary>{r.cenas.length ? `Só em ${r.cenas.length} cena(s)` : 'Todas as cenas'}</summary>
          {p.tomadas.map(s => <label key={s.id} className="pilot-choice"><input type="checkbox" checked={r.cenas.includes(s.id)}
            onChange={e => mudar(r.id, { cenas: e.target.checked ? [...r.cenas, s.id] : r.cenas.filter(c => c !== s.id) })} /> {s.titulo}</label>)}
        </details>}
      </div>
    </article>)}</div>
    {erro && <p role="alert" className="error-message">{erro}</p>}
    <div className="card-buttons"><button className="primary-button" disabled={busy} onClick={() => void salvar()}>{busy ? 'Salvando…' : 'Salvar caderno'}</button>
      {salvo && <span className="success-note" role="status">Salvo. Os quadros são conferidos de novo se algo mudou.</span>}</div>
  </div>
}
