"""Ctrl+V no chat: imagens coladas são resolvidas sem IA quando a intenção é clara."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from studio.processo import Processo, Mensagem, intencao_imagem, pede_variacao


class FakeCli:
    def status(self):
        return {"conectado": False}


class ColarImagemTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        for pasta in ('persona', 'anexos', 'cenarios'):
            (self.root / pasta).mkdir()
        Image.new('RGB', (40, 70), 'white').save(self.root / 'persona' / 'ellie-aprovada.png')
        Image.new('RGB', (40, 70), 'gray').save(self.root / 'anexos' / 'ref.png')
        self.ia_chamadas = []
        self.imagens = []

        def ask(prompt, photos):
            self.ia_chamadas.append((prompt, photos))
            return json.dumps({"mensagem_pt": "ok", "blocos": []})

        def imagem(pasta, descricao, nome, refs, usar_ellie):
            self.imagens.append((pasta, descricao, [r.name for r in refs], usar_ellie))
            Image.new('RGB', (40, 70), 'blue').save(self.root / pasta / 'gerada.png')
            return 'gerada.png'

        self.s = Processo(self.root, ask, cli=FakeCli(), imagem=imagem)
        self.p = self.s.create('teste')
        self.ref = {"pasta": "anexos", "nome": "ref.png"}

    def tearDown(self):
        self.temp.cleanup()

    def esperar(self):
        for _ in range(100):
            if self.p['id'] not in self.s.busy:
                return
            time.sleep(0.02)
        self.fail('geração não terminou')

    def test_intencoes(self):
        self.assertEqual(intencao_imagem('faz um cenário com isso'), 'cenarios')
        self.assertEqual(intencao_imagem('quero a Ellie usando essa roupa'), 'base')
        self.assertEqual(intencao_imagem('recria o look'), 'pecas')
        self.assertEqual(intencao_imagem('só guardar'), 'guardar')
        self.assertIsNone(intencao_imagem('hmm'))
        self.assertTrue(pede_variacao('gera outra versão'))

    def test_colar_com_intencao_gera_sem_ia(self):
        p = self.s.chat(self.p['id'], Mensagem(texto='cria um cenário', anexos=[self.ref]))
        self.assertTrue(p['ocupado'])
        self.esperar()
        p = self.s.store.get(self.p['id'])
        self.assertEqual(self.ia_chamadas, [])
        self.assertEqual(self.imagens[0][0], 'cenarios')
        self.assertEqual(self.imagens[0][2], ['ref.png'])
        ultimo = p['mensagens'][-1]['blocos'][0]
        self.assertEqual((ultimo['tipo'], ultimo['nomes']), ('imagem', ['gerada.png']))
        self.assertEqual(p['anexos_pendentes'], [])

    def test_colar_sem_texto_mostra_quiz_local_e_resposta_gera(self):
        p = self.s.chat(self.p['id'], Mensagem(texto='', anexos=[self.ref]))
        self.assertEqual(p['mensagens'][-1]['blocos'][0]['tipo'], 'quiz')
        self.assertEqual(self.ia_chamadas, [])
        self.s.chat(self.p['id'], Mensagem(texto='Ellie usando essa roupa'))
        self.esperar()
        self.assertEqual(self.imagens[0][0], 'base')
        self.assertTrue(self.imagens[0][3])
        self.assertEqual(self.ia_chamadas, [])

    def test_variacao_repete_ultimo_pedido(self):
        self.s.chat(self.p['id'], Mensagem(texto='cenário', anexos=[self.ref]))
        self.esperar()
        self.s.chat(self.p['id'], Mensagem(texto='gera outra versão'))
        self.esperar()
        self.assertEqual(len(self.imagens), 2)
        self.assertEqual(self.ia_chamadas, [])

    def test_pedido_elaborado_vai_para_ia_com_a_imagem(self):
        self.s.chat(self.p['id'], Mensagem(texto='olha essa referência e me diz o que acha da luz dela', anexos=[self.ref]))
        self.assertEqual(len(self.ia_chamadas), 1)
        self.assertIn('ref.png', [f.name for f in self.ia_chamadas[0][1]])

    def test_anexo_expira_depois_de_dois_turnos(self):
        self.s.chat(self.p['id'], Mensagem(texto='olha essa referência e me diz o que acha da luz dela', anexos=[self.ref]))
        self.s.chat(self.p['id'], Mensagem(texto='e se mudarmos a ideia do vídeo todo?'))
        self.s.chat(self.p['id'], Mensagem(texto='agora pensa na roupa do outono'))
        self.assertEqual(self.imagens, [])  # "roupa" não dispara imagem com anexo velho
        self.assertNotIn('ref.png', [f.name for f in self.ia_chamadas[-1][1]])

    def test_ia_pode_pedir_imagem(self):
        self.s.ask = lambda prompt, photos: json.dumps({"mensagem_pt": "Vou criar o cenário.", "blocos": [],
            "acao": "gerar_imagem", "imagem": {"pasta": "cenarios", "prompt": "cosy London bedroom", "usar_anexos": True}})
        self.s.chat(self.p['id'], Mensagem(texto='usa essa como base pra algo londrino e aconchegante', anexos=[self.ref]))
        self.esperar()
        self.assertEqual(self.imagens[0][:3], ('cenarios', 'cosy London bedroom', ['ref.png']))

    def test_descartar_move_para_lixeira(self):
        self.s.chat(self.p['id'], Mensagem(texto='cenário', anexos=[self.ref]))
        self.esperar()
        p = self.s.descartar(self.p['id'], {"pasta": "cenarios", "nome": "gerada.png"})
        self.assertFalse((self.root / 'cenarios' / 'gerada.png').exists())
        self.assertTrue((self.root / 'lixeira' / 'cenarios' / 'gerada.png').exists())
        self.assertTrue(p['mensagens'][-1]['blocos'][0]['descartado'])


    def test_nao_descarta_modelo_aprovada_nem_arquivo_do_breno(self):
        with self.assertRaises(ValueError):
            self.s.descartar(self.p['id'], {"pasta": "persona", "nome": "ellie-aprovada.png"})
        self.assertTrue((self.root / 'persona' / 'ellie-aprovada.png').exists())

    def test_cartao_da_ia_nao_ganha_botoes(self):
        cards = Processo.cards([{"tipo": "imagem", "pasta": "persona", "nomes": ["ellie-aprovada.png"], "gerada": True}],
                               {"persona": ["ellie-aprovada.png"]})
        self.assertNotIn("gerada", cards[0])


if __name__ == '__main__':
    unittest.main()
