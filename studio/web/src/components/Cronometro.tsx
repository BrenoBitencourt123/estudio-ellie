import { useEffect, useState } from 'react'

export const duracao = (s: number) => s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}min ${Math.round(s % 60)}s`

// Relógio que anda sozinho, usado nas fichas de trabalho e nas etapas em curso
export default function Cronometro({ desde }: { desde: number }) {
  const [agora, setAgora] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setAgora(Date.now()), 1000); return () => clearInterval(t) }, [])
  return <span className="live-timer">{duracao(Math.max(0, (agora - desde) / 1000))}</span>
}
