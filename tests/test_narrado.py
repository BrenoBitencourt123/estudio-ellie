"""Narração em qualquer produção: voz + legenda karaokê + setas no CTA (montagem local real com ffmpeg)."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from studio.processo import Processo, Mensagem, Narracao
from studio.narracao import palavras_de_caracteres
from studio.montagem_narrada import blocos, inicio_cta


class FakeCli:
    def __init__(self):
        self.validados = []

    def status(self):
        return {"conectado": True}

    def validate(self, shot):
        self.validados.append(shot)

    def canvas(self, id, title):
        return {"webUrl": "https://dreamina/x"}

    def upload(self, path, project, resource, kind):
        return {"resourceId": resource}

    def import_node(self, *a):
        return {"node": {"nodeId": "node_ref1"}}

    def draft(self, shot, *a):
        return {"node": {"nodeId": shot.get("node_id") or "node_cena"}}

    def quote(self, project, nodes):
        return {"confirmable": True, "totalMaxCredits": 400, "draftVersion": 1,
                "items": [{"nodeId": n, "maxCredits": 400} for n in nodes]}


class NarradoTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        for pasta in ('anexos', 'quadros', 'saida'):
            (self.root / pasta).mkdir()
        Image.new('RGB', (90, 160), 'orange').save(self.root / 'anexos' / 'ref.png')
        self.cli = FakeCli()
        self.s = Processo(self.root, lambda *a: '{"mensagem_pt":"ok"}', cli=self.cli, imagem=lambda *a: 'x.png')
        self.p = self.s.create('oração')

    def tearDown(self):
        self.temp.cleanup()

    def esperar(self):
        for _ in range(300):
            if not self.s.ocupado(self.p['id']):
                return
            time.sleep(0.05)
        self.fail('operação não terminou')

    def test_comeca_sem_texto_nem_cena_fixos(self):
        self.assertEqual(self.p['tomadas'], [])
        self.assertIsNone(self.p['master'])
        self.assertEqual(self.p['narracao']['texto'], '')
        self.assertNotIn('Amen', json.dumps(self.p))
        self.assertNotIn('tomb', json.dumps(self.p).lower())

    def test_segundo_quadro_substitui_e_nao_cria_cena(self):
        self.s.chat(self.p['id'], Mensagem(texto='', anexos=[{"pasta": "anexos", "nome": "ref.png"}]))
        self.s.chat(self.p['id'], Mensagem(texto='Usar como quadro inicial'))
        Image.new('RGB', (90, 160), 'blue').save(self.root / 'anexos' / 'ref2.png')
        self.s.chat(self.p['id'], Mensagem(texto='', anexos=[{"pasta": "anexos", "nome": "ref2.png"}]))
        p = self.s.chat(self.p['id'], Mensagem(texto='Usar como quadro inicial'))
        self.assertEqual(len(p['tomadas']), 1)
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "anexos", "nome": "ref2.png"}])

    def test_inicio_do_cta(self):
        w = [{"p": p, "ini": i * .5, "fim": i * .5 + .4} for i, p in enumerate(
            "He calms the storm. Share this with someone who needs it.".split())]
        self.assertEqual(inicio_cta(w, "Share this with someone who needs it."), 2.0)
        self.assertEqual(inicio_cta(w), 2.0)  # sem CTA no plano: verbo típico no começo da frase
        sem = [{"p": "Peace", "ini": 0, "fim": .3}, {"p": "be", "ini": .4, "fim": .5}, {"p": "still.", "ini": .6, "fim": .9}]
        self.assertIsNone(inicio_cta(sem))  # sem CTA: sem setas, nada de chute

    def test_ia_define_texto_e_cta(self):
        self.s.ask = lambda *a: json.dumps({"mensagem_pt": "Texto novo.", "narracao": {
            "texto": "My child, rest. I am here. Type Yes if you receive it.", "cta": "Type Yes if you receive it."}})
        p = self.s.chat(self.p['id'], Mensagem(texto='escreve um texto de Deus falando'))
        self.assertEqual(p['narracao']['cta'], 'Type Yes if you receive it.')
        self.assertEqual(p['mensagens'][-1]['blocos'][0]['tipo'], 'narracao')

    def test_colar_imagem_e_usar_como_quadro(self):
        p = self.s.chat(self.p['id'], Mensagem(texto='', anexos=[{"pasta": "anexos", "nome": "ref.png"}]))
        self.assertIn('Usar como quadro inicial', p['mensagens'][-1]['blocos'][0]['opcoes'])
        p = self.s.chat(self.p['id'], Mensagem(texto='Usar como quadro inicial'))
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "anexos", "nome": "ref.png"}])

    def test_cotacao_sem_modelo_aprovada(self):
        p = self.s.chat(self.p['id'], Mensagem(texto='', anexos=[{"pasta": "anexos", "nome": "ref.png"}]))
        self.s.chat(self.p['id'], Mensagem(texto='Usar como quadro inicial'))
        p = self.s.prepare_quote(self.p['id'])
        self.assertEqual(p['cotacao']['total'], 400)
        self.assertEqual(len(self.cli.validados[0]['imagens']), 1)  # só o quadro inicial, sem a Ellie

    def test_gerar_voz_guarda_palavras(self):
        def falso(texto, destino, voz=''):
            destino.write_bytes(b'mp3')
            return [{"p": "God", "ini": 0, "fim": .3}]
        with mock.patch('studio.narracao.gerar_elevenlabs', falso):
            self.s.background(self.p['id'], self.s.gerar_narracao, Narracao(texto='God.', voz='abc12345'))
            self.esperar()
        p = self.s.store.get(self.p['id'])
        self.assertEqual(p['narracao']['palavras'][0]['p'], 'God')
        self.assertTrue((self.s.output(self.p['id']) / p['narracao']['audio']).exists())
        self.assertEqual(p['mensagens'][-1]['blocos'][0]['tipo'], 'narracao')

    def test_palavras_e_blocos(self):
        t = 'Comment Amen, and follow for more prayers.'
        w = palavras_de_caracteres(list(t), [i * .05 for i in range(len(t))], [i * .05 + .04 for i in range(len(t))])
        self.assertEqual([x['p'] for x in w][:2], ['Comment', 'Amen,'])
        self.assertEqual(blocos(w), [[0, 1], [2, 3, 4], [5, 6]])

    def _video(self, nome, cor, dur):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={cor}:size=360x640:rate=30', '-t', str(dur),
                        '-pix_fmt', 'yuv420p', '-y', str(self.root / 'saida' / nome)], check=True)

    def test_montagem_real(self):
        out = self.s.output(self.p['id'])
        self._video('cena.mp4', 'orange', 4)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '5', '-y',
                        str(out / 'voz.mp3')], check=True)
        p = self.s.store.get(self.p['id'])
        p = self.s.save_plan(p, {"tomadas": [{"id": "cena", "titulo": "Cena", "duracao": 4, "prompt": "Gentle push-in.",
                                              "arquivo": None}]}, p['versao'])
        p['tomadas'][0]['arquivo'] = {"pasta": "saida", "nome": "cena.mp4"}
        p['narracao'].update(texto='God loves you. Comment Amen.', cta='Comment Amen.', audio='voz.mp3',
                             palavras=[{"p": "God", "ini": .2, "fim": .6}, {"p": "loves", "ini": .7, "fim": 1.1},
                                       {"p": "you.", "ini": 1.2, "fim": 1.5}, {"p": "Comment", "ini": 2.0, "fim": 2.4},
                                       {"p": "Amen.", "ini": 2.5, "fim": 3.0}])
        self.s.store.save(p)
        p = self.s.render(self.p['id'])
        self.assertEqual((p['resultado']['width'], p['resultado']['height']), (1080, 1920))
        # Áudio primeiro: o vídeo dura o tempo da voz (5 s); a cena de 4 s ganha câmera lenta em vez de congelar
        self.assertAlmostEqual(p['resultado']['duracao'], 5.0, delta=.1)
        self.assertLess(p['cortes'][0]['velocidade'], 1)

    def test_tres_cenas_com_faixa_sem_narracao(self):
        for i, cor in enumerate(['red', 'green', 'blue'], 1):
            self._video(f'c{i}.mp4', cor, 4)
        p = self.s.store.get(self.p['id'])
        p = self.s.save_plan(p, {"tomadas": [{"id": f"c{i}", "titulo": f"Cena {i}", "duracao": 4, "prompt": "Some motion."}
                                             for i in (1, 2, 3)],
                                 "cortes": [{"tomada": "c1", "duracao": 2}, {"tomada": "c2", "inicio": 1, "duracao": 3},
                                            {"tomada": "c3", "duracao": 2}], "duracao_final": 7,
                                 "faixa": {"altura": 200, "titulo": "He is with you", "pergunta": "Do you believe?"}},
                             p['versao'])
        for i in (0, 1, 2):
            p['tomadas'][i]['arquivo'] = {"pasta": "saida", "nome": f"c{i + 1}.mp4"}
        self.s.store.save(p)
        p = self.s.render(self.p['id'])
        self.assertEqual((p['resultado']['width'], p['resultado']['height']), (1080, 1920))
        self.assertAlmostEqual(p['resultado']['duracao'], 7, delta=.1)

    def test_varias_cenas_com_voz_curta_seguem_a_voz(self):
        for i in (1, 2):
            self._video(f'c{i}.mp4', 'gray', 4)
        out = self.s.output(self.p['id'])
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300', '-t', '3', '-y',
                        str(out / 'voz.mp3')], check=True)
        p = self.s.store.get(self.p['id'])
        p = self.s.save_plan(p, {"tomadas": [{"id": f"c{i}", "titulo": f"C{i}", "duracao": 4, "prompt": "Some motion."}
                                             for i in (1, 2)]}, p['versao'])
        for i in (0, 1):
            p['tomadas'][i]['arquivo'] = {"pasta": "saida", "nome": f"c{i + 1}.mp4"}
        p['narracao'].update(texto='Peace be still.', audio='voz.mp3', palavras=[{"p": "Peace", "ini": .2, "fim": .6},
                             {"p": "be", "ini": .7, "fim": .9}, {"p": "still.", "ini": 1.0, "fim": 1.5}])
        self.s.store.save(p)
        p = self.s.render(self.p['id'])
        # As duas cenas dividem os 3 s da voz em vez de esticar o vídeo para 8 s com fala só no começo
        self.assertAlmostEqual(p['resultado']['duracao'], 3.0, delta=.1)
        self.assertEqual(len(p['cortes']), 2)
        self.assertAlmostEqual(sum(c['duracao'] for c in p['cortes']), 3.0, delta=.01)

    def test_texto_sem_voz_nao_monta(self):
        self._video('c1.mp4', 'gray', 4)
        p = self.s.store.get(self.p['id'])
        p = self.s.save_plan(p, {"tomadas": [{"id": "c1", "titulo": "C1", "duracao": 4, "prompt": "Some motion."}]}, p['versao'])
        p['tomadas'][0]['arquivo'] = {"pasta": "saida", "nome": "c1.mp4"}
        p['narracao']['texto'] = 'Peace be still.'
        self.s.store.save(p)
        with self.assertRaisesRegex(ValueError, 'Falta a narração'):
            self.s.render(self.p['id'])

if __name__ == '__main__':
    unittest.main()
