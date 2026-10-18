export type Pasta = 'persona' | 'pecas' | 'cenarios' | 'movimentos' | 'base'

export type Assets = Record<Pasta, string[]>

export type Resolucao = '480p' | '720p'

// Pilares de conteúdo do perfil (meta 70/20/10)
export type Pilar = '' | 'outfit_clima' | 'pov_london' | 'lugar'

export interface ConfigEstudio {
  modelos: string[]
  modelos_kling: string[]
  precos: Record<string, number>
  modelo_padrao: string
  resolucao_padrao: Resolucao
  chave_configurada: boolean
  gasto_semana_usd: number
  teto_usd: number
  cotacao: number
  max_imagens: number
  provedor_prompt: string
}

// Tudo que define um vídeo. É isso que vira "receita" pra repetir o mesmo setup.
// Caminho escolhido no Criar: Ellie copiando um vídeo, Ellie a partir das fotos, ou Lugar
export type Modo = '' | 'movimento' | 'fotos' | 'lugar'

export interface EstadoEstudio {
  modo: Modo
  tipo: 'ellie' | 'lugar'
  nome: string
  persona: string[]
  peca: string | null
  cenario: string | null
  movimento: string | null
  movimentoInicio: number
  cena: string
  camera: string
  objeto: string
  mao: '' | 'right' | 'left'
  duracao: number
  modelo: string
  resolucao: Resolucao
  promptManual: string | null
  aumentar1080: boolean
  // Só Kling
  imagemBase: string | null
  orientacao: 'image' | 'video'
  manterSom: boolean
  // Crescimento do perfil
  pilar: Pilar
  rascunhoId: string
}

export interface Repetido {
  arquivo: string
  data: string
  nota: string
}

export interface Estimativa {
  custo_usd: number
  custo_brl: number
  segundos_movimento: number
  repetidos: Repetido[]
  dica: string
}

export interface Job {
  id: string
  nome: string
  status: 'rodando' | 'ok' | 'falhou' | 'enviado'
  etapa: string
  erro: string
  arquivo: string
  arquivo_1080: string
  prediction_id: string
  prompt: string
  custo_estimado_usd: number | string
  custo_real_usd: string
  criado: number
}

export interface ItemHistorico {
  data: string
  id: string
  modelo: string
  prediction_id: string
  duracao: string
  custo_estimado_usd: string
  custo_real_usd: string
  status: string
  arquivo: string
  arquivo_1080: string
  erro: string
  prompt: string
  pedido: PedidoApi | null
  pilar: string
  avaliacao: Avaliacao
}

// Formato que o servidor Python espera (snake_case)
export interface PedidoApi {
  tipo: 'ellie' | 'lugar'
  nome: string
  modelo: string
  resolucao: Resolucao
  duracao: number
  persona: string[]
  peca: string | null
  cenario: string | null
  movimento: string | null
  movimento_inicio: number
  cena: string
  camera: string
  objeto: string
  mao: '' | 'right' | 'left'
  prompt_manual: string | null
  aumentar_1080: boolean
  imagem_base: string | null
  orientacao: 'image' | 'video'
  manter_som: boolean
  pilar: Pilar
  rascunho_id: string
  projeto_id?: string
}

export type Receitas = Record<string, EstadoEstudio>

export interface PropsPasso {
  estado: EstadoEstudio
  mudar: (parcial: Partial<EstadoEstudio>) => void
  assets: Assets
  config: ConfigEstudio
  recarregarAssets: () => Promise<void>
}

export interface ResultadoAssistente {
  nome: string
  cena: string
  camera: string
  objeto: string
  mao: '' | 'right' | 'left'
  resumo_pt: string
  avisos: string[]
}

export interface RespostaAssistente {
  provedor: string
  folhas: string[]
  resultado: ResultadoAssistente | null
  briefing?: string
  aviso?: string
}

export interface Rascunho {
  id: string
  criado: string
  origem: string
  nota: string
  pedido: PedidoApi
  prompt: string
  custo_usd: number
  custo_brl: number
  segundos_movimento: number
  passa_do_teto: boolean
  repetidos: Repetido[]
  dica: string
}

export interface Tiktok {
  views?: number
  conclusao_pct?: number
  seguidores?: number
  postado_em?: string
}

export interface Avaliacao {
  nota?: '' | 'bom' | 'ruim'
  problemas?: string[]
  comentario?: string
  analise_ia?: { problemas: string[]; comentario: string; nota_sugerida?: string; em?: string }
  tiktok?: Tiktok
  virou_referencia?: string
  video_texto?: { arquivo: string; texto: string; estilo: string; cor: string; config?: Record<string, unknown> }
  legendas?: {
    opcoes: { texto_tela_en: string; texto_tela_pt: string; legenda_en: string; legenda_pt: string; origem?: string }[]
    recomendada: number
    porque_pt: string
  }
}

export interface ConfigAprendida {
  modo: string
  modelo: string
  gerados: number
  falhas: number
  bons: number
  ruins: number
  aprovacao: number | null
  custo_por_aprovado: number | null
  custo_medio: number | null
}

export interface Aprendizado {
  configs: ConfigAprendida[]
  problemas: { problema: string; nome: string; vezes: number; como_corrigir: string }[]
  pilares: {
    pilar: string
    videos: number
    meta: number
    fatia: number
    views_media: number | null
    conclusao_media: number | null
    seguidores_por_100_views: number | null
  }[]
  vencedores: {
    prediction_id: string
    arquivo: string
    modo: string
    modelo: string
    custo_usd: number
    pilar: string
    pedido: PedidoApi
    views: number | null
    conclusao_pct: number | null
    seguidores: number | null
  }[]
  rejeicoes_kling: { movimento: string; vezes: number }[]
  sem_avaliacao: number
  recomendacoes: string[]
  nomes_problemas: Record<string, string>
  modos: Record<string, string>
}

export interface StatusIa {
  conectado: boolean
  agente?: string
  existe?: boolean
  erro?: string
}

export interface MidiaACriar {
  pasta: 'pecas' | 'cenarios' | 'base' | 'persona'
  nome: string
  prompt: string
  usar_fotos_ellie: boolean
  porque_pt: string
  arquivo: string
}

export interface Plano {
  analise: {
    resumo_pt: string
    movimento_en: string
    enquadramento: string
    cabeca_visivel: boolean
    tronco_inteiro: boolean
    texto_sobre_corpo: boolean
    mao_celular: string
  }
  motor: 'seedance' | 'kling'
  modelo: string
  porque_pt: string
  usar: { persona: string[]; peca: string; cenario: string; imagem_base: string }
  criar: MidiaACriar[]
  video: {
    nome: string
    pilar: string
    duracao: number
    movimento_inicio: number
    cena: string
    camera: string
    objeto: string
    mao: string
    orientacao: string
    sem_rosto?: boolean
  }
  passos_pt: string[]
  riscos_pt: string[]
}

export interface RegistroPlano {
  id: string
  criado: string
  movimento: string | null
  ideia: string
  plano: Plano
  folha_movimento: string
  pedido: PedidoApi
  custo_usd: number | null
  pronto: boolean
  falta: string
}

export type Etapa = 'estrategia' | 'midias' | 'gerar' | 'gerando' | 'revisar' | 'postar' | 'postado' | 'medido'

export interface Projeto {
  id: string
  criado: string
  atualizado?: string
  titulo: string
  ideia: string
  pilar: string
  formato: 'movimento' | 'fotos' | 'lugar'
  movimento: string | null
  gancho_en: string
  gancho_pt: string
  ganchos: { en: string; pt: string }[]
  legenda_en: string
  legenda_pt: string
  porque_pt: string
  ideia_visual_pt: string
  precisa_referencia: boolean
  plano_id: string
  videos: string[]
  video_escolhido: string
  postado_em: string
  arquivado?: boolean
  sem_rosto?: boolean
  etapa: Etapa
  nome_etapa: string
  plano: RegistroPlano | null
  pedido: PedidoApi | null
  videos_detalhe: ItemHistorico[]
  capa: string
}
