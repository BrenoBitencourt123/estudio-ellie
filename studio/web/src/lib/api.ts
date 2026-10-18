import type {
  Aprendizado,
  Avaliacao,
  Assets,
  ConfigEstudio,
  Estimativa,
  ItemHistorico,
  Job,
  Pasta,
  Projeto,
  PedidoApi,
  Receitas,
  EstadoEstudio,
  Rascunho,
  RegistroPlano,
  StatusIa,
  RespostaAssistente,
  ResultadoAssistente,
} from '@/types'

async function chamar<T>(url: string, opcoes?: RequestInit): Promise<T> {
  const resposta = await fetch(url, opcoes)
  if (!resposta.ok) {
    let mensagem = `Erro ${resposta.status}`
    try {
      const corpo = await resposta.json()
      if (typeof corpo.detail === 'string') mensagem = corpo.detail
      else if (Array.isArray(corpo.detail)) mensagem = corpo.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      // resposta sem JSON: fica a mensagem genérica
    }
    throw new Error(mensagem)
  }
  return resposta.json() as Promise<T>
}

const enviarJson = (metodo: string, corpo: unknown): RequestInit => ({
  method: metodo,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(corpo),
})

export const api = {
  config: () => chamar<ConfigEstudio>('/api/config'),
  assets: () => chamar<Assets>('/api/assets'),
  prompt: (p: PedidoApi) => chamar<{ prompt: string }>('/api/prompt', enviarJson('POST', p)),
  estimar: (p: PedidoApi) => chamar<Estimativa>('/api/estimar', enviarJson('POST', p)),
  gerar: (p: PedidoApi) => chamar<Job>('/api/gerar', enviarJson('POST', p)),
  assistente: (pedido: PedidoApi, ideia: string) =>
    chamar<RespostaAssistente>('/api/assistente', enviarJson('POST', { pedido, ideia })),
  interpretar: (texto: string) =>
    chamar<{ resultado: ResultadoAssistente }>('/api/assistente/interpretar', enviarJson('POST', { texto })),
  rascunhos: () => chamar<Rascunho[]>('/api/rascunhos'),
  descartarRascunho: (id: string) =>
    chamar<{ ok: boolean }>(`/api/rascunhos/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  planos: () => chamar<RegistroPlano[]>('/api/planos'),
  planejar: (movimento: string | null, ideia: string) =>
    chamar<RegistroPlano>('/api/plano', enviarJson('POST', { movimento, ideia })),
  criarMidia: (planoId: string, indice: number, prompt: string) =>
    chamar<RegistroPlano>(`/api/plano/${planoId}/midia`, enviarJson('POST', { indice, prompt })),
  rascunhoDoPlano: (planoId: string) => chamar<Rascunho>(`/api/plano/${planoId}/rascunho`, enviarJson('POST', {})),
  statusIa: () => chamar<StatusIa>('/api/ia/status'),
  revisar: (prediction_id: string) =>
    chamar<{ avaliacao: Avaliacao }>('/api/revisar', enviarJson('POST', { prediction_id })),
  legenda: (prediction_id: string) =>
    chamar<{ avaliacao: Avaliacao }>('/api/legenda', enviarJson('POST', { prediction_id })),
  gerarMidia: (
    pasta: Pasta,
    descricao: string,
    usar_fotos_ellie: boolean,
    referencias_coladas: string[] = [],
    escopo: 'look' | 'peca' = 'look',
  ) =>
    chamar<{ pasta: Pasta; nome: string }>(
      '/api/midia/gerar',
      enviarJson('POST', { pasta, descricao, usar_fotos_ellie, referencias_coladas, escopo }),
    ),
  midiaDoVideo: (movimento: string, pasta: Pasta, extra: string) =>
    chamar<{ pasta: Pasta; nome: string }>('/api/midia/do-video', enviarJson('POST', { movimento, pasta, extra })),
  sugerirTextoTela: (prediction_id: string, texto: string) =>
    chamar<{ texto: string; texto_pt: string; fonte: string; fundo: string; tamanho: number; x: number; y: number; cor: string; porque_pt: string }>(
      '/api/texto-na-tela/sugerir', enviarJson('POST', { prediction_id, texto }),
    ),
  posicaoTexto: (prediction_id: string, altura: number, largura: number) =>
    chamar<{ x: number; y: number; cor: string; luminosidade: number }>(
      '/api/texto-na-tela/posicao', enviarJson('POST', { prediction_id, altura, largura }),
    ),
  camadaTexto: (prediction_id: string, png: string, texto: string, config: object) =>
    chamar<{ avaliacao: Avaliacao }>('/api/texto-na-tela/camada', enviarJson('POST', { prediction_id, png, texto, config })),
  paraReferencia: (prediction_id: string) =>
    chamar<{ nome: string; avaliacao: Avaliacao }>('/api/video/para-referencia', enviarJson('POST', { prediction_id })),
  textoNaTela: (prediction_id: string, texto: string, estilo: string, posicao: string) =>
    chamar<{ avaliacao: Avaliacao }>('/api/texto-na-tela', enviarJson('POST', { prediction_id, texto, estilo, posicao })),
  projetos: () => chamar<Projeto[]>('/api/projetos'),
  projeto: (id: string) => chamar<Projeto>(`/api/projetos/${id}`),
  criarProjeto: (titulo: string, ideia: string) => chamar<Projeto>('/api/projetos', enviarJson('POST', { titulo, ideia })),
  editarProjeto: (id: string, campos: Partial<Projeto>) => chamar<Projeto>(`/api/projetos/${id}`, enviarJson('PATCH', campos)),
  estrategia: (id: string) => chamar<Projeto>(`/api/projetos/${id}/estrategia`, enviarJson('POST', {})),
  planejarProjeto: (id: string) => chamar<Projeto>(`/api/projetos/${id}/planejar`, enviarJson('POST', {})),
  videoRapido: (dados: { movimento: string | null; peca: string | null; cenario: string | null; ideia: string; sem_rosto: boolean }) =>
    chamar<Projeto>('/api/projetos/rapido', enviarJson('POST', dados)),
  pauta: (quantidade: number, foco: string) =>
    chamar<{ criados: string[]; projetos: Projeto[] }>('/api/pauta', enviarJson('POST', { quantidade, foco })),
  editarPlano: (id: string, edicao: { usar?: Record<string, unknown>; video?: Record<string, unknown>; modelo?: string }) =>
    chamar<RegistroPlano>(`/api/plano/${id}`, enviarJson('PATCH', edicao)),
  aprendizado: () => chamar<Aprendizado>('/api/aprendizado'),
  // Quais fotos da Ellie mostram o rosto (palpite do detector, corrigível com um clique)
  rostos: () => chamar<Record<string, boolean>>('/api/persona/rostos'),
  marcarRosto: (nome: string, rosto: boolean) =>
    chamar<Record<string, boolean>>('/api/persona/rostos', enviarJson('POST', { nome, rosto })),
  recortarSemRosto: (nome: string) =>
    chamar<{ nome: string; rostos: Record<string, boolean> }>('/api/persona/sem-rosto', enviarJson('POST', { nome })),
  avaliar: (prediction_id: string, campos: Partial<Avaliacao>) =>
    chamar<{ avaliacao: Avaliacao }>('/api/avaliar', enviarJson('POST', { prediction_id, ...campos })),
  jobs: () => chamar<Job[]>('/api/jobs'),
  historico: () => chamar<ItemHistorico[]>('/api/historico'),
  receitas: () => chamar<Receitas>('/api/receitas'),
  salvarReceita: (nome: string, estado: EstadoEstudio) =>
    chamar<{ ok: boolean }>(`/api/receitas/${encodeURIComponent(nome)}`, enviarJson('PUT', estado)),
  apagarReceita: (nome: string) =>
    chamar<{ ok: boolean }>(`/api/receitas/${encodeURIComponent(nome)}`, { method: 'DELETE' }),
  enviarArquivo: (pasta: Pasta, arquivo: File) => {
    const dados = new FormData()
    dados.append('arquivo', arquivo)
    return chamar<{ nome: string }>(`/api/assets/${pasta}`, { method: 'POST', body: dados })
  },
}
