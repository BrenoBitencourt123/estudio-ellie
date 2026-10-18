// Configuração pontual pelo RPC oficial. O chat diário não pede operator.admin.
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { GatewayClient } from '@openclaw/gateway-client'
import { PROTOCOL_VERSION } from '@openclaw/gateway-protocol/version'

const config = JSON.parse(readFileSync(process.env.OPENCLAW_CONFIG_PATH ?? join(homedir(), '.openclaw', 'openclaw.json'), 'utf8'))
// Uso: node configurar-gateway.mjs [agente] [modelo]  (ex.: ellie-claude anthropic/claude-opus-5-5)
const agentId = process.argv[2] || 'ellie-studio'
const modelo = process.argv[3] || ''
const workspace = resolve(import.meta.dirname, '..', 'agente-ellie')
const token = process.env.OPENCLAW_GATEWAY_TOKEN || config.gateway?.auth?.token
if (typeof token !== 'string' || !token) throw new Error('Token local indisponível. Use a CLI oficial para resolver sua configuração.')
let client
const connected = new Promise((resolveConnection, rejectConnection) => {
  client = new GatewayClient({
    url: process.env.OPENCLAW_URL ?? 'ws://127.0.0.1:18789', token,
    clientName: 'gateway-client', clientDisplayName: 'Configuração Estúdio Ellie', mode: 'backend', platform: process.platform,
    role: 'operator', scopes: ['operator.read', 'operator.write', 'operator.admin'],
    minProtocol: PROTOCOL_VERSION, maxProtocol: PROTOCOL_VERSION,
    onHelloOk: resolveConnection, onConnectError: rejectConnection,
  })
})
// O Gateway pode demorar minutos para responder enquanto carrega plugins
const timeout = setTimeout(() => { console.error('O Gateway não respondeu em 4 minutos.'); client.stop(); process.exitCode = 1 }, 240000)
try {
  client.start()
  await connected
  const before = await client.request('agents.list', {}, { timeoutMs: 180000 })
  const existing = before.agents?.find(agent => agent.id === agentId)
  if (existing) {
    if (existing.workspace && resolve(existing.workspace).toLowerCase() !== workspace.toLowerCase()) {
      throw new Error(`${agentId} já existe em outro workspace; nenhuma configuração foi sobrescrita.`)
    }
    if (modelo) await client.request('agents.update', { agentId, model: modelo }, { timeoutMs: 180000 })
    console.log(JSON.stringify({ existente: true, agentId, workspace, ...(modelo ? { modelo } : {}) }))
  } else {
    const result = await client.request('agents.create', { name: agentId, workspace, ...(modelo ? { model: modelo } : {}) }, { timeoutMs: 180000 })
    console.log(JSON.stringify({ criado: result.ok, agentId: result.agentId, workspace: result.workspace, modelo: result.model }))
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : 'O Gateway não concluiu o registro. Confira agents.list antes de repetir.')
  process.exitCode = 1
} finally { clearTimeout(timeout); client.stop() }
