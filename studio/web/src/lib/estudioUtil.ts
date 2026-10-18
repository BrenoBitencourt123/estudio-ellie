import type { ConfigEstudio, EstadoEstudio, Modo, PedidoApi } from '@/types'

export const estadoVazio: EstadoEstudio = {
  modo: '',
  tipo: 'ellie',
  nome: '',
  persona: [],
  peca: null,
  cenario: null,
  movimento: null,
  movimentoInicio: 0,
  cena: '',
  camera: '',
  objeto: '',
  mao: '',
  duracao: 8,
  modelo: '2.0-fast',
  resolucao: '720p',
  promptManual: null,
  aumentar1080: true,
  imagemBase: null,
  orientacao: 'video',
  manterSom: false,
  pilar: '',
  rascunhoId: '',
}

export const ehKling = (modelo: string) => modelo.startsWith('kling')

// Reconstrói o caminho (modo) a partir de um pedido salvo
export function modoDoPedido(p: Pick<PedidoApi, 'tipo' | 'modelo' | 'movimento'>): Modo {
  if (p.tipo === 'lugar') return 'lugar'
  if (p.movimento || ehKling(p.modelo)) return 'movimento'
  return 'fotos'
}

// Os dois botões principais do passo final: testar barato e versão para postar
export const OPCOES_GERAR = {
  seedance: [
    { id: 'teste', titulo: 'Testar barato', modelo: '2.0-mini', resolucao: '480p' as const, dica: 'Confere movimento, roupa e cena por centavos' },
    { id: 'final', titulo: 'Versão para postar', modelo: '2.0-fast', resolucao: '720p' as const, dica: 'Melhor custo-benefício em 720p' },
  ],
  kling: [
    { id: 'teste', titulo: 'Kling 2.6 Std', modelo: 'kling-2.6-std', resolucao: '720p' as const, dica: 'O mais barato, já dá bom resultado' },
    { id: 'final', titulo: 'Kling 3.0 Std', modelo: 'kling-3.0-std', resolucao: '720p' as const, dica: 'Mais fiel, quase o dobro do preço' },
  ],
}

export const paraPedido = (e: EstadoEstudio): PedidoApi => ({
  tipo: e.tipo,
  nome: e.nome,
  modelo: e.modelo,
  resolucao: e.resolucao,
  duracao: e.duracao,
  persona: e.persona,
  peca: e.peca,
  cenario: e.cenario,
  movimento: e.movimento,
  movimento_inicio: e.movimentoInicio,
  cena: e.cena,
  camera: e.camera,
  objeto: e.objeto,
  mao: e.mao,
  prompt_manual: e.promptManual,
  aumentar_1080: e.aumentar1080,
  imagem_base: e.imagemBase,
  orientacao: e.orientacao,
  manter_som: e.manterSom,
  pilar: e.pilar,
  rascunho_id: e.rascunhoId,
})

export const dePedido = (p: PedidoApi): EstadoEstudio => ({
  modo: modoDoPedido(p),
  tipo: p.tipo ?? 'ellie',
  nome: p.nome,
  modelo: p.modelo,
  resolucao: p.resolucao,
  duracao: p.duracao,
  persona: p.persona,
  peca: p.peca,
  cenario: p.cenario,
  movimento: p.movimento,
  movimentoInicio: p.movimento_inicio,
  cena: p.cena,
  camera: p.camera ?? '',
  objeto: p.objeto,
  mao: p.mao,
  promptManual: p.prompt_manual,
  aumentar1080: p.aumentar_1080,
  imagemBase: p.imagem_base ?? null,
  orientacao: p.orientacao ?? 'video',
  manterSom: p.manter_som ?? false,
  pilar: p.pilar ?? '',
  rascunhoId: p.rascunho_id ?? '',
})

export const formatarUsd = (v: number) => `US$ ${v.toFixed(2)}`
export const formatarBrl = (v: number) => `R$ ${v.toFixed(2).replace('.', ',')}`

// Presets de qualidade: rascunho barato pra testar a cena, final pra postar
export const presetsKling = [
  { id: 'k-teste', nome: 'Kling teste', modelo: 'kling-2.6-std', dica: 'O mais barato, bom para testar o movimento' },
  { id: 'k-26pro', nome: 'Kling 2.6 Pro', modelo: 'kling-2.6-pro', dica: 'Mais detalhe que o Std' },
  { id: 'k-30std', nome: 'Kling 3.0 Std', modelo: 'kling-3.0-std', dica: 'Geração nova, boa para comparar' },
  { id: 'k-30pro', nome: 'Kling 3.0 Pro', modelo: 'kling-3.0-pro', dica: 'A mais fiel e a mais cara' },
] as const

export const presets = [
  { id: 'rascunho', nome: 'Rascunho', modelo: '2.0-mini', resolucao: '480p', dica: 'Testar movimento e cena por centavos' },
  { id: 'teste', nome: 'Teste bom', modelo: '2.0-fast', resolucao: '720p', dica: 'Já dá pra julgar rosto e roupa' },
  { id: 'final', nome: 'Final', modelo: '2.0', resolucao: '720p', dica: 'Qualidade alta, cerca de US$ 0,24 por segundo em 720p' },
  { id: 'premium', nome: 'Premium', modelo: '2.5', resolucao: '720p', dica: 'Mais fiel, bem mais caro' },
] as const

const CHAVE_RASCUNHO = 'estudio-ellie:rascunho'

export function lerRascunho(): EstadoEstudio | null {
  try {
    const bruto = localStorage.getItem(CHAVE_RASCUNHO)
    return bruto ? ({ ...estadoVazio, ...JSON.parse(bruto) } as EstadoEstudio) : null
  } catch {
    return null
  }
}

export function salvarRascunho(estado: EstadoEstudio): void {
  try {
    localStorage.setItem(CHAVE_RASCUNHO, JSON.stringify(estado))
  } catch {
    // sem localStorage (janela privada): segue sem salvar
  }
}

// Estado vindo de fora (receita antiga, rascunho, histórico) ganha os campos novos e o caminho certo
export function normalizarEstado(e: Partial<EstadoEstudio>): EstadoEstudio {
  const completo = { ...estadoVazio, ...e }
  return { ...completo, modo: completo.modo || modoDoPedido(completo) }
}

// O que ainda falta para poder gerar (null = pronto)
export function problemaDoEstado(estado: EstadoEstudio, config: ConfigEstudio | null): string | null {
  if (config && !config.chave_configurada) return 'Falta ATLASCLOUD_API_KEY no .env.'
  if (estado.tipo === 'lugar') {
    if (!estado.cenario) return 'Escolha a foto do lugar.'
    if (!estado.cena.trim()) return 'Descreva a câmera e o clima.'
    return null
  }
  if (ehKling(estado.modelo)) {
    if (!estado.imagemBase) return 'Escolha a imagem base da Ellie.'
    if (!estado.movimento) return 'Escolha o vídeo de referência.'
  } else {
    if (estado.modo === 'movimento' && !estado.movimento) return 'Escolha o vídeo de referência.'
    if (estado.persona.length === 0) return 'Escolha ao menos uma foto da Ellie.'
    if (!estado.cena.trim()) return 'Escreva a cena.'
  }
  if (estado.objeto.trim() && !estado.mao) return 'Diga em qual mão ela segura o objeto.'
  return null
}
