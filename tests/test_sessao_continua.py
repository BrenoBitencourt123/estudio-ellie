"""Fase 2: sessão contínua por produção. O contexto completo vai uma vez; depois, só o que mudou."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from studio.processo import Processo, Mensagem


class FakeCli:
    def status(self):
        return {"conectado": False}


class SessaoContinuaTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('CONTRATO JSON ' * 200, encoding='utf-8')
        for pasta in ('persona', 'anexos', 'cenarios'):
            (self.root / pasta).mkdir()
        Image.new('RGB', (40, 70), 'white').save(self.root / 'persona' / 'ellie-aprovada.png')
        self.pedidos = []
        self.modelo = 'anthropic/claude'
        self.tentativas = []

        def conversar(pedido, ao_delta):
            self.pedidos.append(pedido)
            usa_delta = bool(pedido['delta']) and pedido['modeloAnterior'] == self.modelo
            resposta = json.dumps({"mensagem_pt": "Certo, \"anotado\".", "blocos": []}, ensure_ascii=False)
            ao_delta(resposta[:20], False)
            self.parcial = self.s.rascunho(self.p['id'])
            ao_delta(resposta[20:], False)
            return {"texto": resposta, "modelo": self.modelo, "modo": "delta" if usa_delta else "completo",
                    "segundos": 1.2, "usage": {"input": 10, "output": 5}, "tentativas": self.tentativas}

        self.s = Processo(self.root, lambda *a: self.fail('modo antigo não deveria ser usado'), cli=FakeCli(), conversar=conversar)
        self.p = self.s.create('teste', 'duas_tomadas')

    def tearDown(self):
        self.temp.cleanup()

    def falar(self, texto):
        return self.s.chat(self.p['id'], Mensagem(texto=texto))

    def test_primeiro_turno_completo_depois_so_delta(self):
        self.falar('quero um vídeo de outono')
        primeiro = self.pedidos[0]
        self.assertIsNone(primeiro['delta'])
        self.assertIn('CONTRATO JSON', primeiro['completo'])
        self.assertEqual(len(primeiro['imagensCompleto']), 1)  # foto aprovada vai uma vez
        p = self.falar('mais curto, 7 segundos')
        segundo = self.pedidos[1]
        self.assertEqual(segundo['modeloAnterior'], 'anthropic/claude')
        self.assertNotIn('CONTRATO JSON', segundo['delta'])
        self.assertNotIn('ESTADO ATUALIZADO', segundo['delta'])  # nada mudou
        self.assertNotIn('BIBLIOTECA', segundo['delta'])
        self.assertEqual(segundo['imagensDelta'], [])  # foto não é reenviada
        self.assertIn('mais curto, 7 segundos', segundo['delta'])
        self.assertLess(len(segundo['delta']) * 10, len(segundo['completo']))
        self.assertEqual(p['mensagens'][-1]['ia']['modo'], 'delta')
        self.assertEqual(primeiro['sessao'], segundo['sessao'])

    def test_estado_alterado_pela_interface_vai_no_delta(self):
        self.falar('oi')
        p = self.s.store.get(self.p['id'])
        plano = {k: p[k] for k in ('duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda')}
        plano['legenda'] = 'Nova legenda'
        self.s.save_plan(p, plano, p['versao'])
        self.falar('e agora?')
        self.assertIn('ESTADO ATUALIZADO', self.pedidos[1]['delta'])
        self.assertIn('Nova legenda', self.pedidos[1]['delta'])

    def test_biblioteca_nova_vai_no_delta(self):
        self.falar('oi')
        Image.new('RGB', (40, 70), 'red').save(self.root / 'cenarios' / 'novo.png')
        self.falar('olha a biblioteca')
        self.assertIn('BIBLIOTECA ATUALIZADA', self.pedidos[1]['delta'])

    def test_mensagens_locais_entram_no_delta(self):
        self.falar('oi')
        p = self.s.store.get(self.p['id'])
        self.s.responder(p, 'Pronto (imagem gerada).', [{"tipo": "imagem", "pasta": "cenarios", "nomes": ["x.png"]}])
        self.falar('gostei')
        self.assertIn('NO APLICATIVO', self.pedidos[1]['delta'])
        self.assertIn('imagem:x.png', self.pedidos[1]['delta'])

    def test_troca_de_modelo_manda_completo(self):
        self.falar('oi')
        self.modelo = 'openai-codex/gpt'  # Claude caiu, GPT assumiu: a ponte decide e manda completo
        self.tentativas = [{"modelo": "anthropic/claude", "erro": "limite"}]
        p = self.falar('continua')
        self.assertEqual(p['mensagens'][-1]['ia']['modo'], 'completo')
        self.assertEqual(p['mensagens'][-1]['ia']['tentativas'], 1)
        self.assertEqual(p['ia_sessao']['modelo'], 'openai-codex/gpt')

    def test_contrato_novo_abre_sessao_nova(self):
        self.falar('oi')
        (self.root / 'studio' / 'processo-prompt.md').write_text('CONTRATO V2', encoding='utf-8')
        self.falar('oi de novo')
        self.assertIsNone(self.pedidos[1]['delta'])
        self.assertNotEqual(self.pedidos[0]['sessao'], self.pedidos[1]['sessao'])

    def test_rascunho_mostra_so_a_mensagem(self):
        self.falar('oi')
        self.assertTrue('Certo'.startswith(self.parcial) or self.parcial.startswith('Certo'))
        self.assertNotIn('{', self.parcial)
        self.assertEqual(self.s.rascunho(self.p['id']), '')  # limpo no fim

    def test_historico_enxuto_sem_listas_de_arquivos(self):
        resumo = Processo.resumo_mensagens([{"papel": "assistant", "texto": "x", "blocos": [
            {"tipo": "galeria", "nomes": ["a.mp4"] * 50}]}])
        self.assertEqual(resumo, [{"papel": "assistant", "texto": "x", "cartoes": ["galeria"]}])


if __name__ == '__main__':
    unittest.main()
