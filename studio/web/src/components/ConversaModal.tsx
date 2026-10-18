import { useEffect, useRef, type ReactNode } from 'react'

export default function ConversaModal({ titulo, children, fechar }: { titulo: string; children: ReactNode; fechar: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close() }, [])
  return <dialog ref={ref} className="conversation-modal" aria-labelledby="modal-title" onCancel={fechar}
    onClick={e => { if (e.target === e.currentTarget) fechar() }}>
    <header><div><span className="eyebrow">NA CONVERSA</span><h2 id="modal-title">{titulo}</h2></div>
      <button className="icon-button" aria-label="Fechar janela" onClick={fechar}>×</button></header>
    {children}
  </dialog>
}
