import copy
import json
import tempfile
import unittest
from pathlib import Path

from studio.cenas_voz import sincronizar
from studio.planejamento import ajustar_plano, atualizar_direcao
from studio.processo import Mensagem, Processo, Tomada, PROMPT_QUADRO


class IteracaoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.temporarios')
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        self.s = Processo(self.root, lambda *_: '{}')
        self.p = self.s.create('Uma ideia')

    def tearDown(self):
        self.temp.cleanup()

    def plano(self):
        cenas = [{'id': f'c{i}', 'titulo': f'Cena {i}', 'duracao': 5,
                  'prompt': 'A person lowers a bag and takes a breath.',
                  'descricao': f'Ação visual {i}', 'intencao': 'Mostrar a mudança'} for i in range(1, 3)]
        return self.s.save_plan(self.p, {'tomadas': cenas}, self.p['versao'])

    def test_direcao_e_editavel_sem_apagar_decisoes_anteriores(self):
        respostas = iter([{'mensagem_pt': 'Proponho uma pausa íntima.', 'direcao': {'ideia': 'Do peso ao alívio', 'objetivo': 'Acolher'}},
                          {'mensagem_pt': 'Vamos usar luz natural.', 'direcao': {'visual': 'Quarto com luz da janela'}}])
        self.s.ask = lambda *_: json.dumps(next(respostas))
        p = self.s.chat(self.p['id'], Mensagem(texto='quero desenvolver uma ideia'))
        self.assertEqual(p['mensagens'][-1]['blocos'][0]['tipo'], 'direcao')
        self.assertFalse(p['tomadas'])
        p = self.s.chat(p['id'], Mensagem(texto='prefiro luz natural'))
        self.assertEqual(p['direcao']['objetivo'], 'Acolher')
        self.assertEqual(p['direcao']['visual'], 'Quarto com luz da janela')
        self.assertIn('Direção do vídeo atualizada.', p['mensagens'][-1]['mudancas'])

    def test_ajustar_uma_cena_preserva_as_outras_e_seus_arquivos(self):
        p = self.plano()
        p['tomadas'][0].update(submit_id='ja-enviada', arquivo={'pasta': 'saida', 'nome': 'pronta.mp4'})
        p = self.s.store.save(p)
        primeira = copy.deepcopy(p['tomadas'][0])
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Ajustei só o fecho.', 'ajustes': {
            'tomadas': [{'id': 'c2', 'descricao': 'Ela abre a mão e solta a alça.', 'prompt': 'She opens her hand and releases the bag strap.'}]}})
        p = self.s.chat(p['id'], Mensagem(texto='muda apenas a segunda cena'))
        self.assertEqual(p['tomadas'][0], primeira)
        self.assertEqual(p['tomadas'][1]['descricao'], 'Ela abre a mão e solta a alça.')
        self.assertEqual(p['duracao_final'], 10)
        self.assertEqual(len(p['mensagens'][-1]['mudancas']), 1)

    def test_descricao_criativa_de_cena_pronta_nao_invalida_video_ou_custo(self):
        p = self.plano()
        p['tomadas'][0].update(submit_id='ja-enviada', arquivo={'pasta': 'saida', 'nome': 'pronta.mp4'})
        p['resultado'] = {'nome': 'final.mp4', 'duracao': 10}
        p['cotacao'] = {'id': 'mesma', 'total': 400}
        p = self.s.store.save(p)
        antes = self.s.generation_hash(p)
        plano = ajustar_plano(p, {'tomadas': [{'id': 'c1', 'intencao': 'Abrir com identificação'}]}, set(Tomada.model_fields))
        p = self.s.save_plan(p, plano, p['versao'])
        self.assertEqual(p['resultado']['nome'], 'final.mp4')
        self.assertEqual(p['cotacao']['id'], 'mesma')
        self.assertEqual(self.s.generation_hash(p), antes)

    def test_id_desconhecido_nao_cria_outra_cena_acidentalmente(self):
        p = self.plano()
        with self.assertRaisesRegex(ValueError, 'inexistente'):
            ajustar_plano(p, {'tomadas': [{'id': 'erro-de-id', 'descricao': 'Mudar'}]}, set(Tomada.model_fields))
        self.assertEqual(len(self.s.store.get(p['id'])['tomadas']), 2)

    def test_ordem_explicita_reconstroi_cortes_sem_perder_cenas(self):
        p = self.plano()
        plano = ajustar_plano(p, {'ordem': ['c2', 'c1']}, set(Tomada.model_fields))
        p = self.s.save_plan(p, plano, p['versao'])
        self.assertEqual([c['tomada'] for c in p['cortes']], ['c2', 'c1'])
        self.assertEqual(p['duracao_final'], 10)

    def test_voz_nao_rebatiza_nem_aumenta_sequencia_planejada(self):
        p = self.plano()
        p['narracao'].update(audio='voz.mp3', palavras=[{'p': f'Frase{i}.', 'ini': i, 'fim': i + .7} for i in range(5)])
        antes = copy.deepcopy(p['tomadas'])
        p = self.s.cenas_pela_voz(p, 5)
        self.assertEqual(p['tomadas'], antes)

    def test_sem_sequencia_dirigida_a_voz_ainda_pode_sugerir_cenas(self):
        p = copy.deepcopy(self.p)
        p['tomadas'] = [Tomada(id='quadro', titulo='Quadro', prompt=PROMPT_QUADRO).model_dump()]
        p['narracao'].update(audio='voz.mp3', palavras=[{'p': f'Frase{i}.', 'ini': i * 2, 'fim': i * 2 + 1.6} for i in range(3)])
        self.assertGreater(len(self.s.cenas_pela_voz(p, 6)['tomadas']), 1)

    def test_poucas_palavras_nao_eliminam_cenas(self):
        p = self.plano()
        for s in p['tomadas']:
            s['tipo'] = 'imagem'
        cortes, total, avisos = sincronizar(p['cortes'], p['tomadas'], [{'p': 'Breathe.', 'ini': 0, 'fim': 1}], 5)
        self.assertEqual([c['tomada'] for c in cortes], ['c1', 'c2'])
        self.assertAlmostEqual(sum(c['duracao'] for c in cortes), total, places=3)
        self.assertTrue(avisos)

    def test_editar_roteiro_invalida_voz_e_resultado_anteriores(self):
        p = self.plano()
        p['narracao'].update(texto='Old words.', audio='voz.mp3')
        p['resultado'] = {'nome': 'antigo.mp4', 'duracao': 10}
        self.s.store.save(p)
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Roteiro ajustado.', 'narracao': {'texto': 'Take one breath.'}})
        p = self.s.chat(p['id'], Mensagem(texto='muda a fala'))
        self.assertIsNone(p.get('resultado'))
        self.assertIsNone(p['narracao']['audio'])

    def test_revisao_com_alvo_ou_detalhes_nao_repete_ultima_imagem(self):
        p = self.plano()
        p['ultimo_pedido_imagem'] = {'pasta': 'quadros', 'descricao': 'A room'}
        self.assertIsNone(self.s.rota_rapida(p, 'refaz a cena 2 com a mochila na cadeira', False))
        self.assertIsNone(self.s.rota_rapida(p, 'gera outra versão, mas com luz da manhã', False))


if __name__ == '__main__':
    unittest.main()
