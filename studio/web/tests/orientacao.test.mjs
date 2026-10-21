import assert from 'node:assert/strict'
import test from 'node:test'
import { proximoPasso } from '../src/lib/orientacao.ts'

const cena = (extra = {}) => ({ id: 'look', tipo: 'video', imagens: [], ...extra })
const producao = (extra = {}) => ({ tomadas: [], trabalhos: [], narracao: {}, ...extra })

test('não oferece cotar quando ainda não existe um plano', () => {
  const passo = proximoPasso(producao())
  assert.equal(passo.titulo, 'Desenvolver a ideia')
  assert.equal(passo.bloco, undefined)
})
test('quadro em geração não pede outro arquivo', () => {
  const passo = proximoPasso(producao({ tomadas: [cena()], trabalhos: [{ faixa: 'midia' }] }))
  assert.equal(passo.titulo, 'Preparando os quadros')
  assert.equal(passo.botao, undefined)
})
test('seleção de quadro aponta para a cena que falta', () => {
  const passo = proximoPasso(producao({ tomadas: [cena()] }))
  assert.equal(passo.bloco.tomada, 'look')
  assert.equal(passo.bloco.pasta, 'quadros')
})
test('cotação aguarda autorização e nunca dispara a geração', () => {
  const passo = proximoPasso(producao({ tomadas: [cena({ imagens: [{}] })], cotacao: { total: 400 } }))
  assert.equal(passo.titulo, 'Revisar custo e autorizar')
  assert.equal(passo.bloco.tipo, 'custo')
})
test('tomada já enviada pede acompanhamento', () => {
  const passo = proximoPasso(producao({ tomadas: [cena({ submit_id: 'existente', imagens: [{}] })] }))
  assert.equal(passo.titulo, 'Acompanhar as tomadas')
})
test('cenas de imagem prontas seguem para montagem local', () => {
  const passo = proximoPasso(producao({ tomadas: [cena({ tipo: 'imagem', imagens: [{}] })] }))
  assert.equal(passo.bloco.tipo, 'edicao')
})
test('modelo aprovada não substitui a foto de uma cena local', () => {
  const passo = proximoPasso(producao({ master: {}, tomadas: [cena({ tipo: 'imagem' })] }))
  assert.equal(passo.titulo, 'Completar os quadros')
})
test('direção resumida leva à sequência antes de pedir referências', () => {
  const passo = proximoPasso(producao({ direcao: { ideia: 'Do peso ao alívio' } }))
  assert.equal(passo.titulo, 'Desenvolver a sequência')
  assert.equal(passo.bloco.tipo, 'direcao')
})
test('voz informa os cortes antes da preparação dos quadros', () => {
  const passo = proximoPasso(producao({ tomadas: [cena()], narracao: { texto: 'Take a breath.' } }))
  assert.equal(passo.bloco.tipo, 'narracao')
})

test('quadro reprovado na conferência vem antes do custo', () => {
  const passo = proximoPasso(producao({ tomadas: [cena({ imagens: [{}], titulo: 'Saída' })],
    situacoes: { look: { quadro: 'problema' } }, conferencias: { look: { resumo: 'O túmulo está vazio.' } } }))
  assert.equal(passo.titulo, 'Resolver o quadro de “Saída”')
  assert.equal(passo.detalhe, 'O túmulo está vazio.')
})
test('storyboard não revisado segura a cotação', () => {
  const passo = proximoPasso(producao({ fluxo_dirigido: true, ficha: { audio: 'original' }, tomadas: [cena({ imagens: [{}] })],
    situacoes: { look: { quadro: 'ok' } }, revisao_atual: { atual: false } }))
  assert.equal(passo.titulo, 'Revisar o storyboard')
})
test('áudio é decidido logo depois das cenas', () => {
  const passo = proximoPasso(producao({ fluxo_dirigido: true, ficha: { audio: 'indefinido' }, tomadas: [cena()] }))
  assert.equal(passo.bloco.tipo, 'caderno')
})
test('vídeo final com pendência não aparece como pronto', () => {
  const passo = proximoPasso(producao({ resultado: { pendencias: ['O vídeo final saiu sem faixa de áudio.'] } }))
  assert.equal(passo.titulo, 'Vídeo com pendências')
})
