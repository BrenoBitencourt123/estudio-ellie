import type { ReactNode } from 'react'

interface Props {
  titulo: string
  descricao: string
  children: ReactNode
}

export default function Secao({ titulo, descricao, children }: Props) {
  return (
    <section className="space-y-5">
      <header>
        <h2 className="text-xl font-semibold text-slate-900">{titulo}</h2>
        <p className="mt-1 text-sm text-slate-600">{descricao}</p>
      </header>
      {children}
    </section>
  )
}
