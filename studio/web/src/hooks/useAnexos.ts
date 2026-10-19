import { useCallback, useEffect, useRef, useState } from 'react'
import { processo } from '@/lib/processo'
import type { Midia } from '@/types/processo'

// Imagens coladas (Ctrl+V), arrastadas ou escolhidas: sobem na hora para a pasta "anexos"
// e ficam como chips removíveis até a mensagem ser enviada.
export type Anexo = { id: string; url: string; asset?: Midia; erro?: string }

const TIPOS = ['image/png', 'image/jpeg', 'image/webp']
const AUDIO = /^audio\/|\.(mp3|wav|m4a|ogg)$/i
const ehAudio = (f: File) => AUDIO.test(f.type) || AUDIO.test(f.name)
const MAXIMO = 4

// aoAudio: áudio colado/arrastado (narração do vídeo) vai direto para quem cuida dele
export function useAnexos(aoAudio?: (f: File) => void) {
  const [anexos, setAnexos] = useState<Anexo[]>([])
  const lista = useRef<Anexo[]>([])
  lista.current = anexos

  const audio = useRef(aoAudio)
  audio.current = aoAudio
  const adicionar = useCallback((files: File[]) => {
    const audios = files.filter(ehAudio)
    if (audios.length && audio.current) audio.current(audios[0])
    const imagens = files.filter(f => TIPOS.includes(f.type)).slice(0, Math.max(0, MAXIMO - lista.current.length))
    for (const file of imagens) {
      const id = crypto.randomUUID()
      const nome = file.name && file.name !== 'image.png' ? file.name : `colada-${Date.now()}.${file.type.split('/')[1].replace('jpeg', 'jpg')}`
      setAnexos(atual => [...atual, { id, url: URL.createObjectURL(file) }])
      processo.upload('anexos', new File([file], nome, { type: file.type }))
        .then(asset => setAnexos(atual => atual.map(a => a.id === id ? { ...a, asset } : a)))
        .catch(e => setAnexos(atual => atual.map(a => a.id === id ? { ...a, erro: e instanceof Error ? e.message : 'Não subiu' } : a)))
    }
    return imagens.length + (audios.length && audio.current ? 1 : 0)
  }, [])

  const remover = useCallback((id: string) => setAnexos(atual => {
    const item = atual.find(a => a.id === id)
    if (item) URL.revokeObjectURL(item.url)
    return atual.filter(a => a.id !== id)
  }), [])

  const limpar = useCallback(() => setAnexos(atual => { atual.forEach(a => URL.revokeObjectURL(a.url)); return [] }), [])

  // Ctrl+V em qualquer lugar da página (exceto em campos de outros formulários/modais)
  useEffect(() => {
    const aoColar = (e: ClipboardEvent) => {
      const alvo = e.target as HTMLElement | null
      if (alvo && alvo.closest('.conversation-modal')) return
      const files = [...(e.clipboardData?.files ?? [])]
      if (files.some(f => TIPOS.includes(f.type) || ehAudio(f)) && adicionar(files)) e.preventDefault()
    }
    window.addEventListener('paste', aoColar)
    return () => window.removeEventListener('paste', aoColar)
  }, [adicionar])

  const prontos = anexos.filter(a => a.asset).map(a => a.asset!)
  const enviando = anexos.some(a => !a.asset && !a.erro)
  return { anexos, prontos, enviando, adicionar, remover, limpar }
}
