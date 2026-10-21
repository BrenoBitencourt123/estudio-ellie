"""Referências do Pinterest: comando no chat, ação da IA, download e uso como quadro (sem rede nos testes)."""
import json
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from studio.processo import Processo, Mensagem, UsarImagem, termo_pinterest
from studio.referencias import buscar_e_baixar


def jpg(cor='red'):
    b = BytesIO()
    Image.new('RGB', (90, 160), cor).save(b, 'JPEG')
    return b.getvalue()


class PinterestTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        self.buscas = []

        def pinterest(termo, destino, qtd):
            self.buscas.append((termo, qtd))
            destino.mkdir(parents=True, exist_ok=True)
            (destino / 'pin-a.jpg').write_bytes(jpg())
            return ['pin-a.jpg']
        self.s = Processo(self.root, lambda *a: json.dumps({"mensagem_pt": "Vou buscar.", "acao": "buscar_referencias",
                                                          "busca": {"termo": "jesus storm", "quantidade": 6}}),
                          cli=object(), imagem=self.gerar, pinterest=pinterest)
        self.p = self.s.create('ref')

    def gerar(self, pasta, *a):
        (self.root / pasta).mkdir(exist_ok=True)
        Image.new('RGB', (90, 160), 'blue').save(self.root / pasta / 'q.png')
        return 'q.png'

    def tearDown(self):
        self.temp.cleanup()

    def esperar(self):
        for _ in range(200):
            if not self.s.ocupado(self.p['id'], 'midia'):
                return self.s.store.get(self.p['id'])
            time.sleep(0.05)
        self.fail('não terminou')

    def test_termo(self):
        self.assertEqual(termo_pinterest('busca no pinterest jesus walking on water'), 'jesus walking on water')
        self.assertEqual(termo_pinterest('Pinterest: god light'), 'god light')
        self.assertEqual(termo_pinterest('pesquisa no Pinterest "lamb of god"'), 'lamb of god')
        self.assertIsNone(termo_pinterest('gosto do pinterest'))

    def test_comando_direto_sem_ia(self):
        self.s.ask = lambda *a: self.fail('não deveria chamar a IA')
        self.s.chat(self.p['id'], Mensagem(texto='busca no pinterest jesus na tempestade'))
        p = self.esperar()
        self.assertEqual(self.buscas, [('jesus na tempestade', 10)])
        bloco = p['mensagens'][-1]['blocos'][0]
        self.assertEqual((bloco['pasta'], bloco['nomes'], bloco['referencias']), ('referencias', ['pin-a.jpg'], True))

    def test_termo_longo_vai_para_a_ia_resumir(self):
        self.s.chat(self.p['id'], Mensagem(texto='busca no pinterest algo que tem a ver com\n\nWhen the storm is loudest, He is still in the boat.'))
        self.esperar()
        self.assertEqual(self.buscas, [('jesus storm', 6)])  # o termo curto que a IA escolheu

    def test_imagem_gerada_vira_quadro_mesmo_ocupado(self):
        self.s.background(self.p['id'], self.s._gerar_imagem, 'quadros', 'storm', [], False, faixa='midia')
        (self.root / 'quadros').mkdir(exist_ok=True)
        p = self.esperar()
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "quadros", "nome": "q.png"}])
        self.assertEqual(p['erro'], '')
        # depois do "Pronto" vem a conferência do quadro, numa mensagem própria
        self.assertTrue(any('Pronto' in m['texto'] for m in p['mensagens']))

    def test_ia_pede_busca(self):
        self.s.chat(self.p['id'], Mensagem(texto='acha umas referências de Jesus acalmando a tempestade'))
        self.esperar()
        self.assertEqual(self.buscas, [('jesus storm', 6)])

    def test_usar_como_quadro(self):
        (self.root / 'referencias').mkdir()
        (self.root / 'referencias' / 'pin-a.jpg').write_bytes(jpg())
        p = self.s.usar_imagem(self.p['id'], UsarImagem(asset={"pasta": "referencias", "nome": "pin-a.jpg"}, como='quadro'))
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "referencias", "nome": "pin-a.jpg"}])

    def test_baixa_sem_repetir_e_pula_link_quebrado(self):
        destino = self.root / 'referencias'
        res = [{"image_url": "https://i.pinimg.com/originals/a.jpg"}, {"image_url": "https://i.pinimg.com/originals/ruim.jpg"},
               {"image_url": "https://i.pinimg.com/originals/b.jpg"}]
        baixar = lambda url: None if 'ruim' in url else (jpg(), '.jpg')
        nomes = buscar_e_baixar('Jesus na tempestade', destino, 5, pesquisa=lambda t, q: res, baixar=baixar)
        self.assertEqual(len(nomes), 2)
        self.assertTrue(all(n.startswith('pin-jesus-na-tempestade-') for n in nomes))
        de_novo = buscar_e_baixar('Jesus na tempestade', destino, 5, pesquisa=lambda t, q: res,
                                  baixar=lambda url: None if 'ruim' in url else self.fail('não deveria baixar de novo'))
        self.assertEqual(de_novo, nomes)
