export type PastaMidia = 'persona' | 'base' | 'pecas' | 'cenarios' | 'movimentos' | 'saida'
export type Midia = { pasta: PastaMidia; nome: string }
export type Biblioteca = Record<PastaMidia, string[]>
export type Bloco = {
  tipo: 'galeria' | 'quiz' | 'plano' | 'custo' | 'resultado' | 'upload' | 'edicao' | 'conexao'
  titulo?: string; pasta?: PastaMidia; papel?: 'movimento' | 'master' | 'estado' | 'bruto'
  nomes?: string[]; pergunta?: string; opcoes?: string[]
}
export type MensagemChat = { id: string; papel: 'user' | 'assistant'; texto: string; blocos?: Bloco[]; criado: string }
export type Tomada = {
  id: string; titulo: string; lado: 'esquerda' | 'direita'; modelo: string; modo: 'm2v' | 'first_last_frame'
  resolucao: '480p' | '720p' | '1080p'; duracao: number; prompt: string; imagens: Midia[]
  movimento: Midia | null; movimento_inicio: number; movimento_duracao: number; recorte: number[] | null
  arquivo?: Midia; estado?: string; creditos_registrados?: number; reserva_creditos?: number; submit_id?: string
}
export type Corte = { tomada: string; inicio: number; duracao: number; recorte?: number[] | null }
export type Faixa = {
  altura: number; sobretitulo: string; titulo: string; destaque: string; pergunta: string; esquerda: string; direita: string
}
export type PlanoProducao = { duracao_final: number; tomadas: Tomada[]; cortes: Corte[]; faixa: Faixa; legenda: string }
export type Producao = PlanoProducao & {
  id: string; nome: string; versao: number; criado: string; atualizado: string; status: string; erro: string; ocupado?: boolean
  master: Midia | null; referencia: Midia | null; mensagens: MensagemChat[]; canvas_url: string
  cotacao: { id: string; total: number; itens: { nodeId: string; maxCredits: number }[]; tomadas?: string[]; executada?: boolean } | null
  resultado?: { nome: string; duracao: number; width: number; height: number }
  historico_creditos?: number; exemplo?: boolean
}
export type ModeloVideo = { model: string; aliases?: string[]; modes: { name: string; flags: { flag: string; values?: string[]; min?: number; max?: number }[] }[] }
export type Selecao = { papel: 'movimento' | 'master' | 'estado' | 'bruto'; asset: Midia; tomada?: string }
