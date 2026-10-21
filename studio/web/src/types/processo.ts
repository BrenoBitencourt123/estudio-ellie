export type PastaMidia = 'persona' | 'base' | 'pecas' | 'cenarios' | 'movimentos' | 'saida' | 'anexos' | 'quadros' | 'referencias'
export type Midia = { pasta: PastaMidia; nome: string }
export type Biblioteca = Record<PastaMidia, string[]>
export type Bloco = {
  tipo: 'direcao' | 'caderno' | 'galeria' | 'quiz' | 'plano' | 'custo' | 'resultado' | 'upload' | 'edicao' | 'conexao' | 'imagem' | 'narracao'
  titulo?: string; pasta?: PastaMidia; papel?: 'movimento' | 'master' | 'estado' | 'bruto'
  nomes?: string[]; pergunta?: string; opcoes?: string[]; descartado?: boolean; gerada?: boolean; referencias?: boolean; termo?: string
  tomada?: string
  tecnico?: boolean
}
export type UsoIA = { modelo?: string; modo?: 'delta' | 'completo'; segundos?: number; usage?: Record<string, unknown> | null; tentativas?: number; caracteres?: number }
export type MensagemChat = { id: string; papel: 'user' | 'assistant'; texto: string; blocos?: Bloco[]; anexos?: Midia[]; criado: string; ia?: UsoIA; mudancas?: string[] }
export type Direcao = { ideia?: string; objetivo?: string; abertura?: string; desenvolvimento?: string; fecho?: string; visual?: string; audio?: string }
// video: gerada no Dreamina (paga). imagem: a primeira imagem ganha movimento de câmera na montagem (grátis).
export type TipoTomada = 'video' | 'imagem'
export type MovimentoLocal = 'aproximar' | 'afastar' | 'subir' | 'descer' | 'esquerda' | 'direita'
export type Tomada = {
  id: string; titulo: string; lado: 'esquerda' | 'direita' | 'cheia'; ellie?: boolean | null; modelo: string; modo: 'm2v' | 'first_last_frame'
  tipo?: TipoTomada; movimento_local?: MovimentoLocal
  descricao?: string; intencao?: string; fala?: string
  // O que o quadro e a tomada precisam mostrar: a conferência compara o material com estas frases
  exigencias?: string[]
  resolucao: '480p' | '720p' | '1080p'; duracao: number; prompt: string; imagens: Midia[]
  movimento: Midia | null; movimento_inicio: number; movimento_duracao: number; recorte: number[] | null
  arquivo?: Midia; estado?: string; creditos_registrados?: number; reserva_creditos?: number; submit_id?: string
}
export type Corte = { tomada: string; inicio: number; duracao: number; recorte?: number[] | null; velocidade?: number }
export type Faixa = {
  altura: number; sobretitulo: string; titulo: string; destaque: string; pergunta: string; esquerda: string; direita: string
}
export type Layout = 'tela_cheia' | 'lado_a_lado'
export type PlanoProducao = { layout?: Layout; duracao_final: number; tomadas: Tomada[]; cortes: Corte[]; faixa: Faixa; legenda: string }
export type Formato = 'duas_tomadas' | 'narrado'
// Faixas de trabalho do servidor: cada uma corre em paralelo com as outras.
// midia = imagem/Pinterest · voz = narração · producao = cotar/gerar/acompanhar/montar · conversa = turno de IA
export type FaixaTrabalho = 'midia' | 'voz' | 'producao' | 'conversa'
export type Trabalho = { id: string; faixa: FaixaTrabalho; rotulo: string; iniciado: string }
export type EstiloLegenda = 'karaoke' | 'elegante'
// Acabamento local da narração: muda só a montagem, nunca a voz
export type AjustesNarracao = {
  setas: boolean; cta: string; estilo_legenda: EstiloLegenda; seguir_voz: boolean; trilha: string; volume_trilha: number; sfx: boolean
}
export type Narracao = Partial<AjustesNarracao> & {
  texto: string; voz: string; setas: boolean; cta?: string; audio: string | null; palavras: { p: string; ini: number; fim: number }[]; origem?: string
}
// Ficha central: o que vale para a produção inteira, mais forte que o histórico do chat
export type AudioPlano = 'indefinido' | 'silencioso' | 'original' | 'narracao'
export type Ficha = { publico: string; restricoes: string[]; criterios: string[]; audio: AudioPlano }
export type PapelReferencia = 'inspiracao' | 'luz' | 'composicao' | 'personagem' | 'cenario' | 'roupa' | 'movimento'
export type ReferenciaCriativa = { id: string; asset: Midia; papel: PapelReferencia; orientacao: string; cenas: string[]; ativa: boolean }
// Conferência do material contra as exigências da cena (calculada no servidor)
export type SituacaoConferencia = 'pendente' | 'ok' | 'aceita' | 'problema' | 'indeterminada' | 'sem_quadro'
export type Conferencia = {
  atende: boolean | null; resumo: string; correcao: string; aceita?: boolean; tecnico?: string[]
  itens: { exigencia: string; ok: boolean; observacao: string }[]
}
export type Producao = PlanoProducao & {
  direcao?: Direcao
  ficha?: Ficha; referencias_criativas?: ReferenciaCriativa[]; fluxo_dirigido?: boolean
  conferencias?: Record<string, Conferencia>; conferencias_video?: Record<string, Conferencia>
  situacoes?: Record<string, { quadro: SituacaoConferencia; video?: SituacaoConferencia }>
  revisao_atual?: { assinatura: string; atual: boolean }
  id: string; nome: string; versao: number; criado: string; atualizado: string; status: string; erro: string
  ocupado?: boolean; trabalhos?: Trabalho[]
  formato?: Formato; narracao?: Narracao
  master: Midia | null; referencia: Midia | null; mensagens: MensagemChat[]; canvas_url: string
  cotacao: { id: string; total: number; itens: { nodeId: string; maxCredits: number }[]; tomadas?: string[]; executada?: boolean } | null
  // avisos: o que a conferência automática encontrou (duração, quadro parado, volume)
  // pendencias: o que impede dar o vídeo como pronto (ex.: sem áudio quando o plano pede som)
  resultado?: { nome: string; duracao: number; width: number; height: number; avisos?: string[]; pendencias?: string[]; aprovado?: boolean }
  historico_creditos?: number; exemplo?: boolean
}
export type ModeloVideo = { model: string; aliases?: string[]; modes: { name: string; flags: { flag: string; values?: string[]; min?: number; max?: number }[] }[] }
export type Selecao = { papel: 'movimento' | 'master' | 'estado' | 'bruto'; asset: Midia; tomada?: string }
