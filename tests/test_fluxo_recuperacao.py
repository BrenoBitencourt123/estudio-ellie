import copy
import json
import tempfile
import unittest
from pathlib import Path

from studio.processo import Mensagem, Processo, Tomada
from studio.dreamina import Dreamina


class RecuperacaoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.temporarios')
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        self.s = Processo(self.root, lambda *_: '{}')
        self.p = self.s.create('Teste de recuperação')

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def plano(**campos):
        return {'duracao_final': 10, 'tomadas': [
            {'id': 'look', 'titulo': 'Look', 'tipo': 'video', 'duracao': 10,
             'prompt': 'She adjusts the lapel and takes one small step back.', **campos}],
            'cortes': [{'tomada': 'look', 'inicio': 0, 'duracao': 10}]}

    def test_movimento_local_invalido_nao_rejeita_video_nem_muda_tipo(self):
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Preparando.',
                                            'plano': self.plano(movimento_local='natural')})
        p = self.s.chat(self.p['id'], Mensagem(texto='vídeo de 10 segundos'))
        self.assertEqual(p['tomadas'][0]['tipo'], 'video')
        self.assertEqual(p['duracao_final'], 10)
        self.assertFalse(p['erro'])

    def test_duracao_em_string_decimal_e_infinito(self):
        self.assertEqual(Tomada(**self.plano(duracao='6.3')['tomadas'][0]).duracao, 7)
        with self.assertRaises(ValueError):
            Tomada(**self.plano(duracao=float('inf'))['tomadas'][0])

    def test_movimento_valido_de_video_preserva_hash_de_cotacoes_existentes(self):
        self.assertEqual(Tomada(**self.plano(movimento_local='afastar')['tomadas'][0]).movimento_local, 'afastar')

    def test_cartoes_malformados_nao_derrubam_a_resposta(self):
        self.assertEqual(self.s.cards(None, {}), [])
        self.assertEqual(self.s.cards([None, 'plano', {'tipo': 'plano'}], {}), [{'tipo': 'plano', 'titulo': ''}])

    def test_repara_plano_uma_vez_sem_executar_acoes_da_correcao(self):
        respostas = iter([
            {'mensagem_pt': 'Preparando.', 'plano': self.plano(prompt='curto')},
            {'plano': self.plano(), 'acao': 'montar'},
        ])
        self.s.ask = lambda *_: json.dumps(next(respostas))
        p = self.s.chat(self.p['id'], Mensagem(texto='prepara o look'))
        self.assertEqual(len(p['tomadas']), 1)
        self.assertFalse(p['erro'])
        self.assertIsNone(p['cotacao'])
        self.assertIsNone(p.get('resultado'))
        self.assertEqual(len(self.s.store.events(p['id'])), 2)

    def test_reparo_rejeitado_nao_gera_imagem_orfa_nem_anuncia_sucesso(self):
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Cena pronta!',
            'plano': self.plano(prompt='curto'), 'acao': 'gerar_imagem',
            'imagem': {'pasta': 'quadros', 'prompt': 'Mirror look'}})
        chamadas = []
        self.s.imagem = lambda *args: chamadas.append(args)
        p = self.s.chat(self.p['id'], Mensagem(texto='prepara'))
        self.assertFalse(chamadas)
        self.assertFalse(p['tomadas'])
        self.assertNotIn('Cena pronta!', p['mensagens'][-1]['texto'])
        self.assertIn('Não apliquei', p['mensagens'][-1]['texto'])
        self.assertNotIn('OpenClaw', p['mensagens'][-1]['texto'])
        self.assertTrue(p['erro'])

    def test_preserva_imagem_que_chega_enquanto_ia_responde(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        contexto = copy.deepcopy(p)
        p['tomadas'][0]['imagens'] = [{'pasta': 'quadros', 'nome': 'pronto.png'}]
        p = self.s.store.save(p)
        proposta = self.plano(imagens=[])
        novo = self.s.salvar_plano_da_ia(p, proposta, contexto)
        self.assertEqual(novo['tomadas'][0]['imagens'][0]['nome'], 'pronto.png')

    def test_nao_troca_video_por_imagem_ao_corrigir(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Corrigido.', 'plano': self.plano(tipo='imagem')})
        p = self.s.chat(p['id'], Mensagem(texto='corrige o movimento_local e preserva o vídeo'))
        self.assertEqual(p['tomadas'][0]['tipo'], 'video')
        self.assertIn('trocava vídeo', p['erro'])

    def test_troca_explicitamente_pedida_e_aceita(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Trocado.', 'plano': self.plano(tipo='imagem')})
        p = self.s.chat(p['id'], Mensagem(texto='pode trocar por imagem com movimento de câmera'))
        self.assertEqual(p['tomadas'][0]['tipo'], 'imagem')
        self.assertFalse(p['erro'])

    def test_negacao_nao_autoriza_trocar_video_por_imagem(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        self.s.ask = lambda *_: json.dumps({'mensagem_pt': 'Trocado.', 'plano': self.plano(tipo='imagem')})
        p = self.s.chat(p['id'], Mensagem(texto='não quero usar imagem animada, preserve o vídeo'))
        self.assertEqual(p['tomadas'][0]['tipo'], 'video')

    def test_edicao_invalida_nao_muta_plano_do_chamador(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        p['tomadas'][0]['submit_id'] = 'existente'
        p = self.s.store.save(p)
        antes = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            self.s.save_plan(p, self.plano(prompt='Different camera direction.'), p['versao'])
        self.assertEqual(p, antes)

    def test_edicao_nao_apresenta_video_antigo_como_resultado_atual(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        p['resultado'] = {'nome': 'anterior.mp4', 'duracao': 10}
        p = self.s.store.save(p)
        novo = self.s.save_plan(p, {**self.plano(), 'faixa': {'altura': 120, 'titulo': 'Novo texto'}}, p['versao'])
        self.assertIsNone(novo.get('resultado'))

    def test_legenda_do_post_nao_exige_remontar_video(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        p['resultado'] = {'nome': 'pronto.mp4', 'duracao': 10}
        p = self.s.store.save(p)
        novo = self.s.save_plan(p, {**self.plano(), 'legenda': 'Caption for TikTok'}, p['versao'])
        self.assertEqual(novo['resultado']['nome'], 'pronto.mp4')

    def test_renomear_cena_nao_deixa_cotacao_com_hash_antigo(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        p['cotacao'] = {'id': 'q', 'hash': self.s.generation_hash(p), 'total': 400}
        p = self.s.store.save(p)
        novo = self.s.save_plan(p, self.plano(titulo='Novo título'), p['versao'])
        self.assertIsNone(novo['cotacao'])

    def test_recotar_edita_rascunho_existente_sem_iniciar_geracao(self):
        cli = Dreamina(binary='simulado')
        chamadas = []
        cli.call = lambda *args: chamadas.append(args) or {}
        shot = Tomada(**self.plano()['tomadas'][0]).model_dump()
        cli.draft(shot, 'canvas', ['ref'])
        cli.draft({**shot, 'node_id': 'existente'}, 'canvas', ['ref'])
        self.assertEqual(chamadas[0][:3], ('node', 'create', 'video'))
        self.assertEqual(chamadas[1][:3], ('node', 'edit', 'video'))
        self.assertNotIn('--run', chamadas[1])

    def test_consulta_falha_nao_preserva_cotacao_autorizavel(self):
        p = self.s.save_plan(self.p, self.plano(), self.p['versao'])
        p['cotacao'] = {'id': 'antiga', 'total': 400}
        self.s.store.save(p)
        with self.assertRaises(ValueError):
            self.s.prepare_quote(p['id'])  # falta quadro
        self.assertIsNone(self.s.store.get(p['id'])['cotacao'])


if __name__ == '__main__':
    unittest.main()
