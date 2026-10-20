import copy
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from studio.processo import Processo, Mensagem, Gerar, Selecao, create_router, plano_exemplo_ellie


class FakeCli:
    def __init__(self):
        self.runs = 0
        self.total = 720
        self.version = 1
        self.uncertain = False

    def quote(self, project, nodes):
        return {"confirmable": True, "totalMaxCredits": self.total, "draftVersion": self.version,
                "items": [{"nodeId": n, "maxCredits": self.total // len(nodes)} for n in nodes]}

    def run(self, project, shots, ceiling):
        self.runs += 1
        if self.uncertain:
            raise RuntimeError("connection lost after sending")
        return {"items": []}

    def operation(self, project, submit):
        return {"state": "failed", "resources": []}

    def validate(self, shot):
        if len(shot['imagens']) < 2:
            raise ValueError('identity reference missing')

    def canvas(self, id, title):
        return {'webUrl': 'https://dreamina.capcut.com/example/' + id}

    def upload(self, path, project, resource, kind):
        return {'resourceId': resource}

    def import_node(self, *args):
        # Como a CLI real: sem node_id informado, ela gera e devolve um
        self.nodes = getattr(self, 'nodes', 0) + 1
        return {'node': {'nodeId': args[2] or f'node_cli_{self.nodes}'}}

    def draft(self, shot, *args):
        self.version += 1
        self.nodes = getattr(self, 'nodes', 0) + 1
        return {'node': {'nodeId': shot.get('node_id') or f'node_cli_{self.nodes}'}}


class ProductionTests(unittest.TestCase):
    def setUp(self):
        sandbox_temp = Path(__file__).resolve().parent / '.temporarios'
        sandbox_temp.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=sandbox_temp)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        (self.root / 'persona').mkdir()
        (self.root / 'base').mkdir()
        Image.new('RGB', (32, 64), 'red').save(self.root / 'persona' / 'ellie-aprovada.png')
        for name in ['01-verao.png', '04-outono.png']:
            Image.new('RGB', (32, 64), 'blue' if name.startswith('01') else 'cyan').save(self.root / 'base' / name)
        self.cli = FakeCli()
        self.s = Processo(self.root, lambda *_: json.dumps({"mensagem_pt": "Qual referência?", "blocos": [{"tipo": "quiz", "pergunta": "Qual?", "opcoes": ["A", "B"]}]}), cli=self.cli)
        self.p = self.s.create('Teste', 'duas_tomadas')
        plano = plano_exemplo_ellie()
        for shot in plano['tomadas']:
            shot['imagens'] = [{"pasta": "base", "nome": '01-verao.png' if shot['lado'] == 'direita' else '04-outono.png'}]
        self.p = self.s.save_plan(self.p, plano, self.p['versao'])

    def tearDown(self):
        self.temp.cleanup()

    def quoted(self):
        p = self.s.store.get(self.p['id'])
        p['canvas_id'] = 'canvas'
        for shot in p['tomadas']:
            shot['node_id'] = 'node_' + shot['id']
        p['cotacao'] = {"id": "q1", "total": 720, "hash": self.s.generation_hash(p), "draft_version": 1}
        self.s.store.save(p)
        return p

    def test_nova_producao_comeca_vazia(self):
        p = self.s.create('Livre')
        self.assertEqual(p['tomadas'], [])
        self.assertEqual(p['layout'], 'tela_cheia')
        self.assertIsNone(p['master'])
        self.assertEqual(p['legenda'], '')
        self.assertEqual(p['faixa']['altura'], 0)
        self.assertEqual(p['narracao']['texto'], '')
        self.assertNotIn('pilar', p)

    def test_exemplo_ellie_continua_lado_a_lado(self):
        self.assertEqual(self.p['layout'], 'lado_a_lado')
        self.assertEqual(len(self.p['tomadas']), 2)
        self.assertEqual(self.p['master']['nome'], 'ellie-aprovada.png')

    def test_producao_antiga_sem_layout_vira_lado_a_lado(self):
        from studio.processo import layout_de
        self.assertEqual(layout_de({"formato": "duas_tomadas", "tomadas": [{}]}), 'lado_a_lado')
        self.assertEqual(layout_de({"tomadas": [{}]}), 'lado_a_lado')
        self.assertEqual(layout_de({"formato": "narrado", "tomadas": [{}]}), 'tela_cheia')

    def test_tela_cheia_com_tres_cenas_e_corte_automatico(self):
        p = self.s.create('Três cenas')
        cena = lambda i: {"id": f"c{i}", "titulo": f"Cena {i}", "duracao": 5, "prompt": "Slow push-in over the sea at dawn.",
                          "ellie": False}
        p = self.s.save_plan(p, {"tomadas": [cena(1), cena(2), cena(3)]}, p['versao'])
        self.assertEqual([c['tomada'] for c in p['cortes']], ['c1', 'c2', 'c3'])
        self.assertEqual(p['duracao_final'], 15)
        self.assertEqual(p['layout'], 'tela_cheia')

    def test_lado_a_lado_exige_direita_continua(self):
        p = self.s.create('Errado')
        plano = {"layout": "lado_a_lado", "duracao_final": 5, "tomadas": [
            {"id": "a", "titulo": "A", "lado": "esquerda", "duracao": 5, "prompt": "Some motion here."}],
            "cortes": [{"tomada": "a", "duracao": 5}]}
        with self.assertRaisesRegex(ValueError, 'direita'):
            self.s.save_plan(p, plano, p['versao'])

    def test_ia_liga_ellie_e_ve_historico(self):
        vistos = []
        def ask(texto, fotos):
            vistos.append(texto)
            return json.dumps({"mensagem_pt": "Liguei a Ellie.", "ellie": True})
        s = Processo(self.root, ask, cli=self.cli)
        p = s.create('Nova ideia')
        p = s.chat(p['id'], Mensagem(texto='quero a Ellie numa ideia nova'))
        self.assertEqual(p['master']['nome'], 'ellie-aprovada.png')
        self.assertIn('PRODUÇÕES ANTERIORES', vistos[0])
        self.assertIn('Teste', vistos[0])  # a produção anterior aparece para não repetir

    def test_stale_window_does_not_overwrite(self):
        old = copy.deepcopy(self.p)
        self.s.store.save(self.p)
        with self.assertRaisesRegex(ValueError, 'outra janela'):
            self.s.store.save(old, old['versao'])

    def test_below_ceiling_never_sends(self):
        self.quoted()
        with self.assertRaisesRegex(ValueError, 'ultrapassa'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=719))
        self.assertEqual(self.cli.runs, 0)

    def test_changed_price_requires_new_approval(self):
        self.quoted(); self.cli.total = 800
        with self.assertRaisesRegex(ValueError, 'preço mudou'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=900))
        self.assertEqual(self.cli.runs, 0)

    def test_external_draft_change_invalidates_even_same_price(self):
        self.quoted(); self.cli.version = 2
        with self.assertRaisesRegex(ValueError, 'preço mudou'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(self.cli.runs, 0)

    def test_second_click_cannot_resubmit(self):
        self.quoted()
        first = self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        ids = [s['submit_id'] for s in first['tomadas']]
        with self.assertRaisesRegex(ValueError, 'já foram enviadas'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(self.cli.runs, 1)
        self.assertEqual(ids, [s['submit_id'] for s in self.s.store.get(first['id'])['tomadas']])

    def test_uncertain_send_preserves_ids_and_reserves(self):
        self.quoted(); self.cli.uncertain = True
        first = self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(first['status'], 'envio_incerto')
        self.assertEqual(sum(s['reserva_creditos'] for s in first['tomadas']), 720)
        restarted = Processo(self.root, lambda *_: '', cli=self.cli)
        with self.assertRaises(ValueError):
            restarted.generate(first['id'], Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(self.cli.runs, 1)

    def test_failed_operation_is_not_assumed_refunded(self):
        self.quoted(); self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        p = self.s.sync(self.p['id'])
        self.assertEqual(p['status'], 'parcial')
        self.assertIn('estorno ainda não foi confirmado', p['erro'])
        self.assertEqual(sum(s['reserva_creditos'] for s in p['tomadas']), 720)
        self.assertEqual(self.cli.runs, 1)

    def test_tampered_image_invalidates_quote(self):
        self.quoted()
        Image.new('RGB', (32, 64), 'green').save(self.root / 'base' / '01-verao.png')
        with self.assertRaisesRegex(ValueError, 'plano mudou'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(self.cli.runs, 0)

    def test_no_path_escape(self):
        with self.assertRaises(ValueError):
            self.s.asset({'pasta': 'base', 'nome': '../../secret.env'})

    def test_chat_returns_real_quiz_and_persists(self):
        result = self.s.message(self.p['id'], Mensagem(texto='Quero um look de outono'))
        self.assertEqual(result['mensagens'][-1]['blocos'][0]['tipo'], 'quiz')
        self.assertEqual(len(self.s.store.get(self.p['id'])['mensagens']), 2)
        self.assertEqual(self.cli.runs, 0)

    def test_missing_openclaw_preserves_message_without_api_fallback(self):
        def down(*_):
            raise RuntimeError('gateway offline')
        self.s.ask = down
        result = self.s.message(self.p['id'], Mensagem(texto='Minha ideia continua aqui'))
        self.assertEqual(result['mensagens'][0]['texto'], 'Minha ideia continua aqui')
        self.assertEqual(result['mensagens'][-1]['blocos'][0]['tipo'], 'conexao')

    def test_unknown_gallery_files_are_filtered(self):
        cards = self.s.cards([{'tipo': 'galeria', 'pasta': 'base', 'nomes': ['ok.png', 'secret.env']}, {'tipo': 'javascript'}], {'base': ['ok.png']})
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['nomes'], ['ok.png'])

    def test_text_edit_keeps_quote_and_does_not_generate(self):
        p = self.quoted()
        plan = {k: copy.deepcopy(p[k]) for k in ['duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda']}
        plan['faixa']['pergunta'] = 'Which look is your favourite?'
        updated = self.s.save_plan(self.s.store.get(p['id']), plan, self.s.store.get(p['id'])['versao'])
        self.assertEqual(updated['cotacao']['id'], 'q1')
        self.assertEqual(self.cli.runs, 0)

    def test_prompt_edit_discards_quote(self):
        p = self.quoted()
        plan = {k: copy.deepcopy(p[k]) for k in ['duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda']}
        plan['tomadas'][0]['prompt'] += ' Gently smile.'
        current = self.s.store.get(p['id'])
        updated = self.s.save_plan(current, plan, current['versao'])
        self.assertIsNone(updated['cotacao'])

    def test_submitted_prompt_cannot_be_silently_changed(self):
        self.quoted(); p = self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=720))
        plan = {k: copy.deepcopy(p[k]) for k in ['duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda']}
        plan['tomadas'][0]['prompt'] += ' Different action.'
        with self.assertRaisesRegex(ValueError, 'já enviada'):
            self.s.save_plan(p, plan, p['versao'])

    def test_paid_endpoint_requires_ui_approval(self):
        app = FastAPI(); app.include_router(create_router(self.root, lambda *_: '{}'))
        response = TestClient(app).post(f'/api/processo/{self.p["id"]}/gerar', json={'cotacao_id': 'anything', 'teto': 9999})
        self.assertEqual(response.status_code, 403)

    def test_quote_prepares_but_never_generates_and_reuses_imports(self):
        first = self.s.prepare_quote(self.p['id'])
        imported = {k: v['node'] for k, v in first['imports'].items()}
        self.assertEqual(first['cotacao']['total'], 720)
        self.assertEqual(len(imported), 3)
        second = self.s.prepare_quote(self.p['id'])
        self.assertEqual(imported, {k: v['node'] for k, v in second['imports'].items()})
        self.assertEqual(self.cli.runs, 0)

    # ---------------- Faixas de trabalho: o que corre junto e o que espera ----------------
    @contextmanager
    def faixa_ocupada(self, faixa):
        """Mantém um trabalho dessa faixa correndo enquanto o bloco roda."""
        solta, comecou = threading.Event(), threading.Event()
        def segura(*_):
            comecou.set()
            solta.wait(5)
        self.s.background(self.p['id'], segura, faixa=faixa, rotulo=f'teste {faixa}')
        comecou.wait(5)
        try:
            yield
        finally:
            solta.set()
            for _ in range(200):
                if not self.s.ocupado(self.p['id'], faixa):
                    break
                time.sleep(0.01)

    def plano_atual(self):
        p = self.s.store.get(self.p['id'])
        return {k: p[k] for k in ('layout', 'duracao_final', 'tomadas', 'cortes', 'faixa', 'legenda')}

    def test_imagem_voz_e_producao_correm_ao_mesmo_tempo(self):
        with self.faixa_ocupada('midia'), self.faixa_ocupada('voz'), self.faixa_ocupada('producao'):
            correndo = sorted(j['faixa'] for j in self.s.em_andamento(self.p['id']))
            self.assertEqual(correndo, ['midia', 'producao', 'voz'])

    def test_a_quarta_imagem_espera_uma_vaga(self):
        with self.faixa_ocupada('midia'), self.faixa_ocupada('midia'), self.faixa_ocupada('midia'):
            with self.assertRaisesRegex(ValueError, 'três imagens'):
                self.s.background(self.p['id'], lambda *_: None, faixa='midia')

    def test_so_uma_operacao_que_gasta_por_vez(self):
        with self.faixa_ocupada('producao'):
            with self.assertRaisesRegex(ValueError, 'cotando, gerando ou montando'):
                self.s.background(self.p['id'], self.s.generate, Gerar(cotacao_id='q1', teto=720))
        self.assertEqual(self.cli.runs, 0)

    def test_a_conversa_segue_livre_durante_qualquer_operacao(self):
        with self.faixa_ocupada('midia'), self.faixa_ocupada('voz'), self.faixa_ocupada('producao'):
            p = self.s.chat(self.p['id'], Mensagem(texto='e aí, como está indo?'))
        self.assertEqual(p['mensagens'][-2]['texto'], 'e aí, como está indo?')
        self.assertEqual(p['mensagens'][-1]['texto'], 'Qual referência?')

    def test_estrutura_pode_mudar_com_imagem_correndo(self):
        with self.faixa_ocupada('midia'):
            p = self.s.save_plan(self.s.store.get(self.p['id']), self.plano_atual(), None)
        self.assertEqual(len(p['tomadas']), len(self.p['tomadas']))

    def test_estrutura_nao_muda_durante_a_producao(self):
        with self.faixa_ocupada('producao'):
            with self.assertRaisesRegex(ValueError, 'cotando, gerando ou montando'):
                self.s.save_plan(self.s.store.get(self.p['id']), self.plano_atual(), None)

    def test_a_rota_conta_o_que_esta_correndo_e_o_supervisor_enxerga(self):
        router = create_router(self.root, lambda *_: '{}')
        app = FastAPI(); app.include_router(router)
        cliente = TestClient(app)
        producao = router.service.create('Pela rota')
        solta, comecou = threading.Event(), threading.Event()
        def segura(*_):
            comecou.set()
            solta.wait(5)
        router.service.background(producao['id'], segura, faixa='midia', rotulo='Gerando o cenário')
        self.assertTrue(comecou.wait(5))
        try:
            corpo = cliente.get(f'/api/processo/{producao["id"]}').json()
            self.assertTrue(corpo['ocupado'])
            self.assertEqual([t['rotulo'] for t in corpo['trabalhos']], ['Gerando o cenário'])
            # O supervisor usa esta rota para não reiniciar o servidor no meio de um trabalho
            self.assertTrue(cliente.get('/api/processo/ocupado').json()['ocupado'])
        finally:
            solta.set()

    def test_a_conversa_nao_apaga_o_que_o_segundo_plano_escreveu(self):
        """A resposta da IA demora minutos. Uma imagem que ficar pronta no meio não pode sumir do chat."""
        liberado, pensando = threading.Event(), threading.Event()
        def devagar(*_):
            pensando.set()
            liberado.wait(5)
            return json.dumps({"mensagem_pt": "Resposta da IA", "blocos": []})
        self.s.ask = devagar
        turno = threading.Thread(target=lambda: self.s.chat(self.p['id'], Mensagem(texto='monta uma cena')))
        turno.start()
        self.assertTrue(pensando.wait(5))
        self.s.responder(self.p['id'], 'A imagem ficou pronta.')
        liberado.set()
        turno.join(10)
        textos = [m['texto'] for m in self.s.store.get(self.p['id'])['mensagens']]
        self.assertIn('A imagem ficou pronta.', textos)
        self.assertIn('Resposta da IA', textos)

    def test_o_segundo_plano_nao_apaga_o_que_a_conversa_escreveu(self):
        """O lado oposto: uma operação longa da faixa de produção não pode engolir mensagens do chat."""
        p = self.s.store.get(self.p['id'])
        self.s.responder(self.p['id'], 'mensagem que precisa sobreviver')
        p['status'] = 'parcial'  # grava o estado lido ANTES da mensagem acima
        self.s._gravar(p)
        textos = [m['texto'] for m in self.s.store.get(self.p['id'])['mensagens']]
        self.assertIn('mensagem que precisa sobreviver', textos)
        self.assertEqual(self.s.store.get(self.p['id'])['status'], 'parcial')

    def test_pilot_only_submits_the_chosen_shot(self):
        p = self.s.prepare_quote(self.p['id'], ['outono'])
        p = self.s.generate(p['id'], Gerar(cotacao_id=p['cotacao']['id'], teto=720))
        sent = [s['id'] for s in p['tomadas'] if s.get('submit_id')]
        self.assertEqual(sent, ['outono'])
        self.assertEqual(self.cli.runs, 1)

    def test_pilot_does_not_accept_an_unknown_shot(self):
        with self.assertRaisesRegex(ValueError, 'somente tomadas novas'):
            self.s.prepare_quote(self.p['id'], ['inventada'])
        self.assertEqual(self.cli.runs, 0)


if __name__ == '__main__':
    unittest.main()
