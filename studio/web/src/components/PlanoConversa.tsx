import { useEffect, useState } from 'react'
import { ehPaga, planoDe, processo } from '@/lib/processo'
import type { Biblioteca, ModeloVideo, MovimentoLocal, PlanoProducao, Producao, TipoTomada } from '@/types/processo'
import ConversaModal from './ConversaModal'

const MOVIMENTOS: { valor: MovimentoLocal; nome: string }[] = [
  { valor: 'aproximar', nome: 'Aproximar devagar' }, { valor: 'afastar', nome: 'Afastar devagar' },
  { valor: 'subir', nome: 'Subir' }, { valor: 'descer', nome: 'Descer' },
  { valor: 'esquerda', nome: 'Para a esquerda' }, { valor: 'direita', nome: 'Para a direita' },
]

export default function PlanoConversa({ producao, biblioteca, fechar, salvar }: {
  producao: Producao; biblioteca: Biblioteca; fechar: () => void; salvar: (p: Producao) => void
}) {
  const [plan, setPlan] = useState<PlanoProducao>(() => structuredClone(planoDe(producao)))
  const [models, setModels] = useState<ModeloVideo[]>([])
  const [erro, setErro] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { void processo.modelos().then(setModels).catch(() => undefined) }, [])
  const changeShot = (i: number, data: Partial<PlanoProducao['tomadas'][number]>) =>
    setPlan(p => ({ ...p, tomadas: p.tomadas.map((s, index) => index === i ? { ...s, ...data } : s) }))
  return <ConversaModal titulo="Estrutura do vídeo" fechar={fechar}>
    <p className="modal-intro">{plan.tomadas.length} cenas · {plan.tomadas.filter(ehPaga).reduce((a, s) => a + s.duracao, 0)} segundos brutos pagos · {Number(plan.duracao_final.toFixed(1))} segundos na montagem.</p>
    {producao.narracao?.audio && (producao.narracao.seguir_voz ?? true) && plan.layout !== 'lado_a_lado'
      ? <p className="field-note">Os cortes seguem as frases da voz: a duração final e a de cada corte se ajustam sozinhas ao salvar.</p>
      : <label className="field">Duração final, em segundos<input type="number" min="1" max="90" step="0.1" value={plan.duracao_final}
        onChange={e => setPlan({ ...plan, duracao_final: Number(e.target.value) })} /></label>}
    {plan.tomadas.map((shot, i) => <section className="shot-editor" key={shot.id}>
      <div className="section-heading"><h3>{shot.titulo}</h3><span>{shot.lado === 'direita' ? 'Direita · contínuo' : shot.lado === 'esquerda' ? 'Esquerda · cortes' : 'Tela cheia'}</span></div>
      {shot.arquivo && <p className="success-note">Arquivo disponível: {shot.arquivo.nome}. Será reaproveitado.</p>}
      <div className="editor-grid"><label className="field">Tipo de cena<select value={shot.tipo ?? 'video'} disabled={!!shot.submit_id || !!shot.arquivo}
        onChange={e => changeShot(i, { tipo: e.target.value as TipoTomada })}>
        <option value="video">Vídeo gerado no Dreamina · pago</option>
        <option value="imagem">Imagem com movimento de câmera · grátis</option></select></label>
        {!ehPaga(shot) && <label className="field">Movimento da câmera<select value={shot.movimento_local ?? 'aproximar'}
          onChange={e => changeShot(i, { movimento_local: e.target.value as MovimentoLocal })}>
          {MOVIMENTOS.map(m => <option key={m.valor} value={m.valor}>{m.nome}</option>)}</select></label>}</div>
      <p className="field-note">{ehPaga(shot)
        ? 'Vídeo gerado: a pessoa e a roupa podem se mover. Descreva a ação no prompt; o custo é consultado antes da autorização.'
        : 'Imagem com movimento: aproxima ou desloca a câmera sobre uma foto. A pessoa e a roupa permanecem paradas.'}</p>
      {!ehPaga(shot) && !shot.imagens.length && <p className="field-note">Esta cena precisa de uma imagem: peça no chat ou cole uma.</p>}
      {ehPaga(shot) && <div className="editor-grid"><label className="field">Modelo<select value={shot.modelo} disabled={!!shot.submit_id || !!shot.arquivo}
        onChange={e => changeShot(i, { modelo: e.target.value })}>
        {!models.some(m => m.model === shot.modelo) && <option>{shot.modelo}</option>}
        {models.map(m => <option key={m.model} value={m.model}>{m.model.replaceAll('_', ' ')}</option>)}</select></label>
        <label className="field">Duração bruta<input type="number" min="4" max="30" value={shot.duracao} disabled={!!shot.submit_id || !!shot.arquivo}
          onChange={e => changeShot(i, { duracao: Number(e.target.value) })} /></label></div>}
      <details><summary>Direção e referências desta tomada</summary>
        <label className="field">Prompt completo<textarea rows={8} value={shot.prompt} disabled={!!shot.submit_id}
          onChange={e => changeShot(i, { prompt: e.target.value })} /></label>
        <div className="image-choices">{biblioteca.base.map(nome => <label key={nome}>
          <input type="checkbox" disabled={!!shot.submit_id} checked={shot.imagens.some(a => a.pasta === 'base' && a.nome === nome)} onChange={e =>
            changeShot(i, { imagens: e.target.checked ? [...shot.imagens, { pasta: 'base', nome }] : shot.imagens.filter(a => !(a.pasta === 'base' && a.nome === nome)) })} />{nome}</label>)}</div>
        {shot.movimento && <div className="editor-grid"><label className="field">Movimento começa em (s)<input type="number" min="0" step="0.1" value={shot.movimento_inicio}
          disabled={!!shot.submit_id} onChange={e => changeShot(i, { movimento_inicio: Number(e.target.value) })} /></label>
          <label className="field">Trecho usado (s)<input type="number" min="2" max="30" step="0.1" value={shot.movimento_duracao}
            disabled={!!shot.submit_id} onChange={e => changeShot(i, { movimento_duracao: Number(e.target.value) })} /></label></div>}
      </details>
    </section>)}
    <details><summary>{plan.layout === 'lado_a_lado' ? 'Cortes da metade esquerda' : 'Cortes em sequência'}</summary><div className="cuts-list">{plan.cortes.map((cut, i) => <div key={i} className="cut-row">
      <span>{i + 1}. {plan.tomadas.find(s => s.id === cut.tomada)?.titulo}</span>
      <label>Início<input aria-label={`Início do corte ${i + 1}`} type="number" min="0" step="0.1" value={cut.inicio} onChange={e =>
        setPlan(p => ({ ...p, cortes: p.cortes.map((c, j) => j === i ? { ...c, inicio: Number(e.target.value) } : c) }))} /></label>
      <label>Duração<input aria-label={`Duração do corte ${i + 1}`} type="number" min="0.1" step="0.1" value={cut.duracao} onChange={e =>
        setPlan(p => ({ ...p, cortes: p.cortes.map((c, j) => j === i ? { ...c, duracao: Number(e.target.value) } : c) }))} /></label>
    </div>)}</div></details>
    {erro && <p role="alert" className="error-message">{erro}</p>}
    <footer className="modal-footer"><span>Salvar não gera vídeo nem consome créditos.</span><button className="primary-button" disabled={busy} onClick={async () => {
      setBusy(true)
      try { salvar(await processo.salvar(producao, plan)); fechar() } catch (e) { setErro(e instanceof Error ? e.message : 'Erro ao salvar'); setBusy(false) }
    }}>{busy ? 'Salvando…' : 'Salvar estrutura'}</button></footer>
  </ConversaModal>
}
