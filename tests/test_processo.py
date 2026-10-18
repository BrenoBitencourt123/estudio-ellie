import copy
import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from studio.processo import Processo, Mensagem, Gerar, Selecao, create_router


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
        self.p = self.s.create('Teste')

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

    def test_default_is_two_shots_not_eight(self):
        self.assertEqual(len(self.p['tomadas']), 2)
        self.assertEqual(sum(s['duracao'] for s in self.p['tomadas']), 18)
        self.assertEqual(self.p['duracao_final'], 9)
        self.assertNotIn('pilar', self.p)

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

    def test_chat_prevents_concurrent_spending(self):
        self.s.chatting[self.p['id']] = 999999
        with self.assertRaisesRegex(ValueError, 'processando'):
            self.s.background(self.p['id'], lambda *_: None)
        self.assertEqual(self.cli.runs, 0)

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
