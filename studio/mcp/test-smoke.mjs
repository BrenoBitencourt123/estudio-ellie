import assert from 'node:assert/strict'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
const client = new Client({ name: 'estudio-smoke', version: '1.0' })
const transport = new StdioClientTransport({ command: process.execPath, args: ['src/index.ts', '--stdio'], env: {
  ...process.env, ESTUDIO_URL: process.env.ESTUDIO_URL ?? 'http://127.0.0.1:8000',
} })
try {
  await client.connect(transport)
  const listed = await client.listTools()
  const names = listed.tools.map(t => t.name)
  assert.equal(names.length, 8)
  assert.ok(!names.some(n => /avaliar|pilar|gerar_video|aprovar/.test(n)))
  const state = await client.callTool({ name: 'estado_estudio', arguments: {} })
  assert.ok(!state.isError)
  console.log('MCP: 8 ferramentas, biblioteca acessível, nenhuma geração paga exposta.')
} finally { await client.close() }
