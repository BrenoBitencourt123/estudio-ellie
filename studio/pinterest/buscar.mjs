// Busca imagens no Pinterest com o scraper do pinterest-mcp-server (Chrome/Edge escondido, sem API nem chave).
// Uso: node buscar.mjs "termo" [quantidade]  ->  imprime UMA linha JSON no stdout: {ok, resultados:[{title,image_url,link}]}
import fs from 'node:fs'
import path from 'node:path'
import PinterestScraper from 'pinterest-mcp-server/dist/pinterest-scraper.js'

const escrever = console.log.bind(console)
console.log = (...a) => console.error(...a)  // o scraper fala no console; o stdout fica só com o JSON
const sair = (dados, codigo = 0) => { escrever(JSON.stringify(dados)); process.exit(codigo) }

const [, , termo = '', quantidade = '10'] = process.argv
if (!termo.trim()) sair({ ok: false, erro: 'Informe o termo da busca.' }, 2)
const local = process.env.LOCALAPPDATA ?? ''
const candidatos = [
  process.env.PINTEREST_CHROME,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'),
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/opt/pw-browsers/chromium',
]
const navegador = candidatos.find(c => c && fs.existsSync(c))
if (!navegador) sair({ ok: false, erro: 'Não achei Chrome nem Edge. Defina PINTEREST_CHROME no .env com o caminho do navegador.' }, 3)

const scraper = new PinterestScraper()
scraper.getChromePath = () => navegador
const limite = Math.max(1, Math.min(30, Number(quantidade) || 10))
try {
  const resultados = await scraper.search(termo, limite, true)
  sair({ ok: true, navegador, resultados })
} catch (e) {
  sair({ ok: false, erro: String(e?.message ?? e) }, 1)
}
