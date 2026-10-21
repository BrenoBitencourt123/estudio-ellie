"""Prévia com os tempos: vídeo-rascunho local do storyboard, grátis, antes de qualquer geração paga."""
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from studio.caderno import revisao
from studio.cenas_voz import duracao_total
from studio.montagem import probe, tem_audio
from studio.processo import Processo, create_router
from test_audio_primeiro import falar


class SemDreamina:
    """Qualquer uso do Dreamina na prévia é falha: ela não pode gastar nem consultar créditos."""
    def __init__(self):
        self.chamadas = []

    def __getattr__(self, nome):
        def chamada(*a, **k):
            self.chamadas.append(nome)
            raise AssertionError("A prévia chamou o Dreamina: " + nome)
        return chamada


class PreviaTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        for pasta in ('quadros', 'saida', 'trilhas'):
            (self.root / pasta).mkdir()
        for nome, cor in (('ceu.png', 'skyblue'), ('mar.png', 'navy'), ('luz.png', 'gold')):
            Image.new('RGB', (360, 640), cor).save(self.root / 'quadros' / nome)
        self.cli = SemDreamina()
        self.s = Processo(self.root, lambda *a: '{"mensagem_pt":"ok"}', cli=self.cli, imagem=lambda *a: 'x.png')
        self.p = self.s.create('fé')

    def tearDown(self):
        self.temp.cleanup()

    def _plano(self, tomadas: list[dict]) -> dict:
        p = self.s.store.get(self.p['id'])
        return self.s.save_plan(p, {"tomadas": tomadas}, p['versao'])

    def _tres_imagens(self) -> dict:
        cenas = [("c1", "ceu.png", "aproximar"), ("c2", "mar.png", "descer"), ("c3", "luz.png", "afastar")]
        return self._plano([{"id": i, "titulo": i.upper(), "tipo": "imagem", "movimento_local": m, "duracao": 4,
                             "prompt": "Slow camera move over the still.", "imagens": [{"pasta": "quadros", "nome": n}]}
                            for i, n, m in cenas])

    def _com_voz(self, palavras: list[dict], segundos: float):
        out = self.s.output(self.p['id'])
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=44100',
                        '-af', 'volume=0.3', '-t', str(segundos), '-y', str(out / 'voz.mp3')], check=True)
        p = self.s.store.get(self.p['id'])
        p['narracao'].update(texto=" ".join(w['p'] for w in palavras), audio='voz.mp3', palavras=palavras)
        self.s.store.save(p)

    def test_tres_cenas_com_voz_saem_na_duracao_da_voz_sem_dreamina(self):
        self._tres_imagens()
        w = falar("You are tired. You have waited so long. But God is not late.")
        self._com_voz(w, duracao_total(w) - 0.3)
        antes = self.s.store.get(self.p['id'])
        p = self.s.previa(self.p['id'])
        previa = p['previa']
        arquivo = self.s.output(self.p['id']) / previa['nome']
        info = probe(arquivo)
        self.assertEqual((info['width'], info['height']), (540, 960))
        self.assertAlmostEqual(info['duracao'], duracao_total(w), delta=.1)
        self.assertAlmostEqual(previa['duracao'], duracao_total(w), delta=.1)
        self.assertTrue(tem_audio(arquivo))  # a voz entra na prévia
        self.assertEqual(previa['assinatura'], revisao(antes)['assinatura'])
        self.assertEqual(previa['avisos'], [])
        # rascunho: não é o resultado, não muda o status e não sobra pasta de trabalho
        self.assertNotIn('resultado', p)
        self.assertEqual(p['status'], antes['status'])
        self.assertEqual([f.name for f in self.s.output(self.p['id']).glob('previa-*')], [previa['nome']])
        self.assertEqual(self.cli.chamadas, [])
        self.assertEqual(self.s.store.events(self.p['id'])[-1]['creditos'], 0)

    def test_storyboard_mudou_a_previa_fica_desatualizada(self):
        self._tres_imagens()
        p = self.s.previa(self.p['id'])
        self.assertEqual(p['previa']['assinatura'], revisao(p)['assinatura'])
        tomadas = [dict(s) for s in p['tomadas']]
        tomadas[1]['movimento_local'] = 'subir'
        p = self._plano(tomadas)
        self.assertNotEqual(p['previa']['assinatura'], revisao(p)['assinatura'])
        # a prévia nova substitui a anterior no disco
        anterior = p['previa']['nome']
        p = self.s.previa(self.p['id'])
        self.assertNotEqual(p['previa']['nome'], anterior)
        self.assertFalse((self.s.output(self.p['id']) / anterior).exists())
        self.assertEqual(p['previa']['assinatura'], revisao(p)['assinatura'])

    def test_tomada_paga_sem_arquivo_e_cena_sem_quadro(self):
        self._plano([
            {"id": "gancho", "titulo": "Gancho", "duracao": 3, "prompt": "Waves crash, slow motion.",
             "imagens": [{"pasta": "quadros", "nome": "mar.png"}]},
            {"id": "vazia", "titulo": "Mãos em oração", "tipo": "imagem", "duracao": 2, "prompt": "Hands in prayer, close."},
        ])
        p = self.s.store.get(self.p['id'])
        partes = self.s.partes_previa(p)
        self.assertTrue(partes[0]['selo'])  # o quadro com o selo "vídeo será gerado aqui"
        self.assertEqual(partes[0]['movimento'], 'aproximar')
        self.assertNotIn('imagem', partes[1])  # cartão cinza com o título
        self.assertEqual(partes[1]['titulo'], 'Cena 2: Mãos em oração')
        p = self.s.previa(self.p['id'])
        arquivo = self.s.output(self.p['id']) / p['previa']['nome']
        self.assertAlmostEqual(probe(arquivo)['duracao'], 5, delta=.1)
        self.assertFalse(tem_audio(arquivo))  # sem voz, prévia muda
        self.assertTrue(any('Mãos em oração' in a for a in p['previa']['avisos']))
        self.assertIsNone(p['cotacao'])
        self.assertEqual(self.cli.chamadas, [])

    def test_rota_roda_na_faixa_de_producao_e_serve_o_arquivo(self):
        router = create_router(self.root, lambda *_: '{}')
        router.service.cli = SemDreamina()
        app = FastAPI(); app.include_router(router)
        cliente = TestClient(app)
        s = router.service
        producao = s.create('Pela rota')
        s.save_plan(producao, {"tomadas": [{"id": "c1", "titulo": "Céu", "tipo": "imagem", "duracao": 2,
                                            "prompt": "Slow camera move over the still.",
                                            "imagens": [{"pasta": "quadros", "nome": "ceu.png"}]}]}, producao['versao'])
        self.assertEqual(cliente.get(f'/api/processo/{producao["id"]}/previa').status_code, 404)
        terminou = threading.Event()
        original = s.previa
        def previa(id):
            try:
                return original(id)
            finally:
                terminou.set()
        s.previa = previa
        corpo = cliente.post(f'/api/processo/{producao["id"]}/previa').json()
        self.assertEqual(corpo['faixa'], 'producao')
        self.assertTrue(terminou.wait(60))
        for _ in range(50):  # a vaga da faixa fecha logo depois
            if not s.ocupado(producao['id']):
                break
            threading.Event().wait(.1)
        estado = cliente.get(f'/api/processo/{producao["id"]}').json()
        self.assertEqual(estado['erro'], '')
        self.assertEqual(estado['previa']['assinatura'], estado['revisao_atual']['assinatura'])
        resposta = cliente.get(f'/api/processo/{producao["id"]}/previa')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers['content-type'], 'video/mp4')
        self.assertEqual(s.cli.chamadas, [])


if __name__ == '__main__':
    unittest.main()
