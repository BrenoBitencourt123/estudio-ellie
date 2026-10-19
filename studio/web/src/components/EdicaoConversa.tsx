import { useState } from 'react'
import { planoDe, processo } from '@/lib/processo'
import type { Producao } from '@/types/processo'
import ConversaModal from './ConversaModal'

export default function EdicaoConversa({ producao, fechar, salvar }: { producao: Producao; fechar: () => void; salvar: (p: Producao) => void }) {
  const [faixa, setFaixa] = useState(producao.faixa)
  const [legenda, setLegenda] = useState(producao.legenda)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const alterar = (field: string, value: string | number) => setFaixa({ ...faixa, [field]: value })
  return <ConversaModal titulo="Texto e montagem" fechar={fechar}>
    <p className="modal-intro">Altere a faixa e a legenda sem gerar outro vídeo.</p>
    <div className="editor-grid">{([
      ['sobretitulo', 'Linha de apoio'], ['titulo', 'Título'], ['destaque', 'Destaque amarelo'],
      ['pergunta', 'Pergunta para o público'], ['esquerda', 'Rótulo à esquerda'], ['direita', 'Rótulo à direita'],
    ] as const).map(([key, label]) => <label className="field" key={key}>{label}<input value={faixa[key]} maxLength={key === 'pergunta' ? 85 : 40}
      onChange={e => alterar(key, e.target.value)} /></label>)}</div>
    <label className="field">Altura da faixa: {faixa.altura}px<input type="range" min="0" max="400" step="10" value={faixa.altura}
      onChange={e => alterar('altura', Number(e.target.value))} /></label>
    <p className="field-note">Altura 0 = sem faixa. Campo vazio não aparece no vídeo.</p>
    <label className="field">Legenda e hashtags<textarea rows={4} value={legenda} onChange={e => setLegenda(e.target.value)} /></label>
    {erro && <p className="error-message" role="alert">{erro}</p>}
    <footer className="modal-footer"><span>Edição local · sem créditos de geração</span><button className="primary-button" disabled={ocupado} onClick={async () => {
      setOcupado(true)
      try { const p = await processo.salvar(producao, { ...planoDe(producao), faixa, legenda }); salvar(p); fechar() }
      catch (e) { setErro(e instanceof Error ? e.message : 'Não foi possível salvar.'); setOcupado(false) }
    }}>{ocupado ? 'Salvando…' : 'Salvar alterações'}</button></footer>
  </ConversaModal>
}
