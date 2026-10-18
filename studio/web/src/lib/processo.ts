import type { Biblioteca, Midia, ModeloVideo, PlanoProducao, Producao, Selecao } from '@/types/processo'

async function request<T>(path: string, method = 'GET', body?: unknown, human = false): Promise<T> {
  const response = await fetch(`/api/processo${path}`, {
    method, headers: { 'Content-Type': 'application/json', ...(human ? { 'X-Estudio-Humano': 'sim' } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Não foi possível concluir. Confira os campos e tente novamente.')
  return value as T
}
export const processo = {
  listar: () => request<Producao[]>(''),
  criar: (nome: string) => request<Producao>('', 'POST', { nome }),
  obter: (id: string) => request<Producao>(`/${id}`),
  biblioteca: () => request<Biblioteca>('/biblioteca'),
  modelos: () => request<ModeloVideo[]>('/modelos'),
  status: () => request<{ dreamina: { conectado: boolean; instalada: boolean; erro?: string }; planejamento: string }>('/status'),
  conversar: (id: string, texto: string, selecao?: Selecao, anexos: Midia[] = []) => request<Producao>(`/${id}/conversa`, 'POST', { texto, selecao, anexos }),
  rascunho: (id: string) => request<{ texto: string; pensando: boolean }>(`/${id}/rascunho`),
  descartar: (id: string, asset: Midia) => request<Producao>(`/${id}/descartar`, 'POST', { asset }),
  salvar: (p: Producao, plano: PlanoProducao) => request<Producao>(`/${p.id}/plano`, 'PUT', { versao: p.versao, plano }),
  cotar: (id: string, tomadas?: string[]) => request<{ iniciado: boolean }>(`/${id}/cotar`, 'POST', { tomadas }),
  gerar: (p: Producao, teto: number) => request(`/${p.id}/gerar`, 'POST', { cotacao_id: p.cotacao?.id, teto }, true),
  acompanhar: (id: string) => request(`/${id}/acompanhar`, 'POST'),
  montar: (id: string) => request(`/${id}/montar`, 'POST'),
  reusar: (id: string, tomada: string, asset: Selecao['asset']) => request<Producao>(`/${id}/reusar`, 'POST', { tomada, asset }),
  upload: async (pasta: string, file: File) => {
    const body = new FormData(); body.append('arquivo', file)
    const r = await fetch(`/api/processo/upload/${pasta}`, { method: 'POST', body })
    const value = await r.json()
    if (!r.ok) throw new Error(value.detail ?? 'O arquivo não foi enviado.')
    return value as Selecao['asset']
  },
}
export const urlMidia = (pasta: string, nome: string) => `/api/processo/arquivo/${encodeURIComponent(pasta)}/${encodeURIComponent(nome)}`
export const urlResultado = (id: string) => `/api/processo/${id}/resultado`
export const planoDe = (p: Producao): PlanoProducao => ({
  duracao_final: p.duracao_final, tomadas: p.tomadas, cortes: p.cortes, faixa: p.faixa, legenda: p.legenda,
})
