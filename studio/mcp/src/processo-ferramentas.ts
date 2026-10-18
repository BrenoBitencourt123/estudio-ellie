// Superfície ativa do agente: produção e arquivos. Sem avaliações, pilares ou geração paga.
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { estudio } from './estudio.ts'

const texto = (value: unknown) => ({ content: [{ type: 'text' as const, text: JSON.stringify(value, null, 2) }] })
const safe = <T>(fn: (args: T) => Promise<unknown>) => async (args: T) => {
  try { return texto(await fn(args)) }
  catch (e) { return { ...texto({ erro: e instanceof Error ? e.message : String(e) }), isError: true } }
}
const id = z.string().regex(/^[a-zA-Z0-9_-]{1,70}$/)
const asset = z.object({ pasta: z.enum(['persona', 'base', 'pecas', 'cenarios', 'movimentos', 'saida']), nome: z.string() })

export function criarServidorMcp(): McpServer {
  const server = new McpServer({ name: 'estudio-ellie', version: '2.0.0' })
  server.registerTool('estado_estudio', {
    title: 'Estado da produção', description: 'Lista conversas de produção e a biblioteca real. Não consulta avaliações ou redes sociais.',
    inputSchema: {}, annotations: { readOnlyHint: true },
  }, safe(async () => ({ producoes: await estudio.get('/api/processo'), biblioteca: await estudio.get('/api/processo/biblioteca') })))
  server.registerTool('criar_producao', {
    title: 'Abrir produção', description: 'Cria um contexto persistente para a ideia. Não gera nem gasta créditos.',
    inputSchema: { nome: z.string().min(1).max(100) },
  }, safe(async ({ nome }) => estudio.post('/api/processo', { nome })))
  server.registerTool('ver_producao', {
    title: 'Consultar produção', description: 'Lê o plano, a conversa, custos conhecidos, recursos e resultado existentes.',
    inputSchema: { id }, annotations: { readOnlyHint: true },
  }, safe(async ({ id }) => estudio.get(`/api/processo/${id}`)))
  server.registerTool('definir_referencia', {
    title: 'Selecionar referência', description: 'Associa um nome real da biblioteca à modelo, movimento, estado da roupa ou bruto reaproveitado.',
    inputSchema: { id, papel: z.enum(['master', 'movimento', 'estado', 'bruto']), asset, tomada: z.string().optional() },
  }, safe(async ({ id, ...body }) => estudio.post(`/api/processo/${id}/referencia`, body)))
  server.registerTool('salvar_estrutura', {
    title: 'Guardar estrutura', description: 'Salva plano completo e versão esperada, sem gerar. Campos: duracao_final, tomadas, cortes, faixa, legenda.',
    inputSchema: { id, versao: z.number().int(), plano: z.record(z.string(), z.unknown()) },
  }, safe(async ({ id, ...body }) => {
    const response = await fetch(`${process.env.ESTUDIO_URL ?? 'http://127.0.0.1:8000'}/api/processo/${id}/plano`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    const value = await response.json()
    if (!response.ok) throw new Error(JSON.stringify(value))
    return value
  }))
  server.registerTool('consultar_custo', {
    title: 'Cotar plano', description: 'Prepara rascunhos e consulta a cotação Dreamina real; não autoriza nem inicia geração. Consulte ver_producao depois.',
    inputSchema: { id, tomadas: z.array(z.string()).optional() },
  }, safe(async ({ id, tomadas }) => estudio.post(`/api/processo/${id}/cotar`, { tomadas })))
  server.registerTool('acompanhar_producao', {
    title: 'Acompanhar e recuperar', description: 'Consulta os envios originais e baixa os resultados existentes pela CLI. Não reenvia geração.',
    inputSchema: { id },
  }, safe(async ({ id }) => estudio.post(`/api/processo/${id}/acompanhar`, {})))
  server.registerTool('montar_video', {
    title: 'Editar localmente', description: 'Monta arquivos existentes com cortes e faixa, sem créditos de geração. Nunca publica.',
    inputSchema: { id },
  }, safe(async ({ id }) => estudio.post(`/api/processo/${id}/montar`, {})))
  return server
}
