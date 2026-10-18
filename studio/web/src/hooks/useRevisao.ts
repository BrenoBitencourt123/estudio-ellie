import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { paraPedido } from '@/lib/estudioUtil'
import type { EstadoEstudio, Estimativa } from '@/types'

interface Revisao {
  estimativa: Estimativa | null
  promptAuto: string
  erro: string
}

// Atualiza custo e prompt montado pelo servidor sempre que algo muda (com pausa de 400ms)
export function useRevisao(estado: EstadoEstudio): Revisao {
  const [revisao, setRevisao] = useState<Revisao>({ estimativa: null, promptAuto: '', erro: '' })
  // Muda só quando algo que afeta custo ou prompt muda (o prompt manual não entra)
  const chave = JSON.stringify({ ...estado, promptManual: null, nome: '' })

  useEffect(() => {
    const pedido = paraPedido(estado)
    const cancelar = { valor: false }
    const timer = setTimeout(async () => {
      try {
        const estimativa = await api.estimar(pedido)
        let promptAuto = ''
        let erro = ''
        try {
          promptAuto = (await api.prompt(pedido)).prompt
        } catch (e) {
          erro = e instanceof Error ? e.message : 'Falha ao montar o prompt'
        }
        if (!cancelar.valor) setRevisao({ estimativa, promptAuto, erro })
      } catch (e) {
        if (!cancelar.valor) {
          setRevisao({ estimativa: null, promptAuto: '', erro: e instanceof Error ? e.message : 'Falha ao estimar' })
        }
      }
    }, 400)
    return () => {
      cancelar.valor = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave])

  return revisao
}
