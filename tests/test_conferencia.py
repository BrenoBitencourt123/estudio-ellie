"""Conferência: cada etapa confere se resolveu a anterior antes de seguir (quadro, gasto, tomada e vídeo final)."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from studio import conferencia as conf
from studio.caderno import assinatura_revisao
from studio.processo import AtivarReferencia, Gerar, Mensagem, Processo
from test_narrado import FakeCli

TUMULO = {"id": "saida", "titulo": "Saída do túmulo", "tipo": "video", "duracao": 5,
          "descricao": "Jesus sai do túmulo e caminha em direção à câmera.",
          "exigencias": ["Jesus visível na entrada do túmulo", "câmera do lado de fora", "espaço para ele caminhar"],
          "prompt": "Jesus steps out of the tomb and walks towards the camera.", "ellie": False}

REPROVADO = {"atende": False, "resumo": "O túmulo está vazio.", "correcao": "Show Jesus standing in the tomb entrance.",
             "itens": [{"exigencia": "Jesus visível na entrada do túmulo", "ok": False, "observacao": "não há ninguém"},
                       {"exigencia": "câmera do lado de fora", "ok": True, "observacao": "ok"}]}
APROVADO = {"atende": True, "resumo": "Jesus na entrada, câmera de fora.", "correcao": "", "itens": []}


def video(destino: Path, segundos: float = 5, som: bool = True):
    args = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=720x1280:rate=30']
    if som:
        args += ['-f', 'lavfi', '-i', 'sine=frequency=300:sample_rate=48000']
    subprocess.run(args + ['-t', str(segundos), '-pix_fmt', 'yuv420p', '-y', str(destino)], check=True)


class CliQueEntrega(FakeCli):
    """Dreamina simulado do envio ao download: entrega um vídeo real, com ou sem faixa de áudio."""
    def __init__(self, som=True):
        super().__init__()
        self.som, self.runs = som, 0

    def run(self, project, shots, ceiling):
        self.runs += 1
        return {}

    def operation(self, project, submit):
        return {"state": "success", "resources": [{"state": "success", "resourceId": "r1"}]}

    def resource(self, project, resource):
        return {"type": "video", "status": "success", "creditsAmount": 400}

    def download(self, project, resource, path):
        video(path, 5, self.som)
        return {}


class ConferenciaTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / '.temporarios'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        (self.root / 'studio').mkdir()
        (self.root / 'studio' / 'processo-prompt.md').write_text('JSON only', encoding='utf-8')
        for pasta in ('quadros', 'saida', 'referencias'):
            (self.root / pasta).mkdir()
        Image.new('RGB', (360, 640), 'gray').save(self.root / 'quadros' / 'tumulo-vazio.png')
        Image.new('RGB', (360, 640), 'white').save(self.root / 'quadros' / 'jesus-na-entrada.png')
        for n in range(14):
            Image.new('RGB', (90, 160), (n * 15, 0, 0)).save(self.root / 'referencias' / f'pin-{n}.jpg')
        self.vereditos, self.pedidos = [], []
        def ask(texto, fotos):
            self.pedidos.append((texto, [f.name for f in fotos]))
            if texto.startswith('Você é o conferente'):
                return json.dumps(self.vereditos.pop(0) if self.vereditos else APROVADO)
            return json.dumps({"mensagem_pt": "ok"})
        self.cli = CliQueEntrega()
        self.s = Processo(self.root, ask, cli=self.cli, imagem=lambda *a: self.proxima_imagem)
        self.proxima_imagem = 'tumulo-vazio.png'
        self.p = self.s.create('Ressurreição')
        self.p = self.s.save_plan(self.p, {"tomadas": [TUMULO]}, self.p['versao'])

    def tearDown(self):
        self.temp.cleanup()

    def esperar(self):
        for _ in range(400):
            if not self.s.ocupado(self.p['id']):
                return self.s.store.get(self.p['id'])
            time.sleep(0.05)
        self.fail('operação não terminou')

    def gerar_quadro(self, nome: str, veredito: dict):
        self.proxima_imagem = nome
        self.vereditos.append(veredito)
        self.s._gerar_imagem(self.p['id'], 'quadros', 'opening frame', [], False, 'saida')
        return self.s.store.get(self.p['id'])

    def com_audio(self, tipo: str):
        p = self.s.store.get(self.p['id'])
        p['ficha'] = {**p['ficha'], 'audio': tipo}
        return self.s.store.save(p)

    # ---- quadro antes do gasto ----
    def test_tumulo_vazio_e_reprovado_e_explica_o_que_falta(self):
        p = self.gerar_quadro('tumulo-vazio.png', REPROVADO)
        self.assertEqual(self.s.situacoes(p)['saida']['quadro'], 'problema')
        ultima = p['mensagens'][-1]
        self.assertIn('não atende', ultima['texto'])
        self.assertIn('✗ Jesus visível na entrada do túmulo', ultima['texto'])
        self.assertEqual(ultima['blocos'][0]['opcoes'], ['Refazer “Saída do túmulo” com a correção',
                                                         'Usar “Saída do túmulo” mesmo assim'])
        # a conferência recebe a exigência central e a imagem certa
        pedido, fotos = self.pedidos[-1]
        self.assertIn('Jesus visível na entrada do túmulo', pedido)
        self.assertEqual(fotos, ['tumulo-vazio.png'])

    def test_quadro_reprovado_segura_a_revisao_do_storyboard(self):
        self.com_audio('original')
        p = self.gerar_quadro('tumulo-vazio.png', REPROVADO)
        with self.assertRaisesRegex(ValueError, 'não passaram na conferência: Saída do túmulo'):
            self.s.revisar_storyboard(p['id'], self.s.com_estado(p)['revisao_atual']['assinatura'])

    def test_refazer_com_a_correcao_leva_a_exigencia_para_a_imagem(self):
        self.gerar_quadro('tumulo-vazio.png', REPROVADO)
        self.proxima_imagem = 'jesus-na-entrada.png'
        self.vereditos.append(APROVADO)
        enviados = []
        original = self.s.imagem
        self.s.imagem = lambda pasta, desc, nome, refs, ellie: enviados.append(desc) or original(pasta, desc, nome, refs, ellie)
        self.s.chat(self.p['id'], Mensagem(texto='Refazer “Saída do túmulo” com a correção'))
        p = self.esperar()
        self.assertIn('MUST FIX: Show Jesus standing in the tomb entrance.', enviados[0])
        self.assertIn('must_show', enviados[0])
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "quadros", "nome": "jesus-na-entrada.png"}])
        self.assertEqual(self.s.situacoes(p)['saida']['quadro'], 'ok')

    def test_usar_mesmo_assim_registra_a_decisao_e_libera(self):
        self.com_audio('original')
        self.gerar_quadro('tumulo-vazio.png', REPROVADO)
        p = self.s.chat(self.p['id'], Mensagem(texto='Usar “Saída do túmulo” mesmo assim'))
        self.assertEqual(self.s.situacoes(p)['saida']['quadro'], 'aceita')
        self.assertIn('decisão sua', p['mensagens'][-1]['texto'])
        p = self.s.revisar_storyboard(p['id'], self.s.com_estado(p)['revisao_atual']['assinatura'])
        self.assertTrue(self.s.com_estado(p)['revisao_atual']['atual'])

    def test_mudar_a_exigencia_volta_o_quadro_para_conferencia(self):
        p = self.gerar_quadro('jesus-na-entrada.png', APROVADO)
        self.assertEqual(self.s.situacoes(p)['saida']['quadro'], 'ok')
        cena = {**TUMULO, "imagens": p['tomadas'][0]['imagens'], "exigencias": TUMULO["exigencias"] + ["amanhecer ao fundo"]}
        p = self.s.save_plan(p, {"tomadas": [cena]}, p['versao'])
        self.assertEqual(self.s.situacoes(p)['saida']['quadro'], 'pendente')

    def test_resposta_sem_veredito_nao_aprova(self):
        self.assertIsNone(conf.veredito('Parece bom!')['atende'])
        contraditorio = conf.veredito(json.dumps({**APROVADO, "itens": REPROVADO["itens"]}))
        self.assertFalse(contraditorio['atende'])  # item reprovado vence o "atende" otimista

    # ---- gasto ----
    def test_nao_gera_sem_storyboard_revisado(self):
        p = self.s.store.get(self.p['id'])
        p['canvas_id'], p['tomadas'][0]['node_id'] = 'canvas', 'node_saida'
        p['cotacao'] = {"id": "q1", "total": 400, "hash": self.s.generation_hash(p), "draft_version": 1}
        self.s.store.save(p)
        with self.assertRaisesRegex(ValueError, 'Revise o storyboard'):
            self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=400))
        self.assertEqual(self.cli.runs, 0)

    # ---- tomada recebida e vídeo final ----
    def _gerar_e_acompanhar(self, som: bool, audio: str = 'original'):
        self.cli.som = som
        self.com_audio(audio)
        p = self.gerar_quadro('jesus-na-entrada.png', APROVADO)
        p['canvas_id'], p['tomadas'][0]['node_id'] = 'canvas', 'node_saida'
        p['cotacao'] = {"id": "q1", "total": 400, "hash": self.s.generation_hash(p), "draft_version": 1}
        p['revisao'] = {"assinatura": assinatura_revisao(p)}
        self.s.store.save(p)
        self.s.generate(self.p['id'], Gerar(cotacao_id='q1', teto=400))
        return self.s.sync(self.p['id'])

    def test_tomada_sem_audio_quando_o_plano_pede_som_original_nao_e_montada(self):
        p = self._gerar_e_acompanhar(som=False)
        self.assertEqual(p['status'], 'conferir_tomadas')
        self.assertFalse(p.get('resultado'))  # não montou com a tomada reprovada
        self.assertEqual(self.s.situacoes(p)['saida']['video'], 'problema')
        self.assertTrue(any('sem faixa de áudio' in m['texto'] for m in p['mensagens']))

    def test_tomada_certa_e_montada_com_o_som_original(self):
        p = self._gerar_e_acompanhar(som=True)
        self.assertEqual(p['status'], 'concluido')
        self.assertTrue(p['resultado']['aprovado'])
        from studio.montagem import tem_audio
        self.assertTrue(tem_audio(self.s.output(p['id']) / p['resultado']['nome']))
        # a folha de quadros da tomada foi conferida contra a ação
        self.assertTrue(any(t.startswith('Você é o conferente') and 'folha com quadros' in t for t, _ in self.pedidos))

    def test_audio_aceito_sem_som_deixa_pendencia_no_video_final(self):
        p = self._gerar_e_acompanhar(som=False)
        self.s.aceitar_conferencia(p['id'], 'saida', 'video')
        p = self.s.render(p['id'])
        self.assertFalse(p['resultado']['aprovado'])
        self.assertEqual(p['status'], 'com_pendencias')
        self.assertTrue(any('Sem som original' in x for x in p['resultado']['pendencias']))

    def test_silencio_intencional_nao_e_pendencia(self):
        p = self._gerar_e_acompanhar(som=False, audio='silencioso')
        self.assertEqual(p['status'], 'concluido')
        self.assertTrue(p['resultado']['aprovado'])

    # ---- referências ----
    def test_referencia_do_pinterest_entra_no_caderno_com_papel(self):
        p = self.s.ativar_referencia(self.p['id'], AtivarReferencia(
            asset={"pasta": "referencias", "nome": "pin-0.jpg"}, papel='luz', orientacao='luz dourada de lado'))
        ref = next(r for r in p['referencias_criativas'] if r['asset']['nome'] == 'pin-0.jpg')
        self.assertEqual((ref['ativa'], ref['papel'], ref['orientacao']), (True, 'luz', 'luz dourada de lado'))
        # e passa a ir junto, com o papel, para a IA e para a imagem da cena
        contexto, fotos = self.s._contexto(p)
        self.assertIn('pin-0.jpg', [f.name for f in fotos])
        self.assertEqual(contexto['referencias_visuais'][0]['papel'], 'luz')

    def test_varias_referencias_vao_juntas_para_a_ia_ate_12(self):
        for n in range(12):
            self.s.ativar_referencia(self.p['id'], AtivarReferencia(asset={"pasta": "referencias", "nome": f"pin-{n}.jpg"}))
        with self.assertRaisesRegex(ValueError, '12 referências ativas'):
            self.s.ativar_referencia(self.p['id'], AtivarReferencia(asset={"pasta": "referencias", "nome": "pin-12.jpg"}))
        _, fotos = self.s._contexto(self.s.store.get(self.p['id']))
        self.assertEqual(sum(f.name.startswith('pin-') for f in fotos), 12)

    def test_ia_explica_o_papel_de_cada_referencia_no_caderno(self):
        self.s.ativar_referencia(self.p['id'], AtivarReferencia(asset={"pasta": "referencias", "nome": "pin-1.jpg"}))
        self.s.ask = lambda *a: json.dumps({"mensagem_pt": "Esta serve para a luz.", "caderno": {
            "ficha": {"audio": "narracao", "restricoes": ["sem texto na imagem"]},
            "referencias": [{"nome": "pin-1.jpg", "papel": "composicao", "orientacao": "enquadramento baixo", "cenas": ["saida", "inventada"]}]}})
        p = self.s.chat(self.p['id'], Mensagem(texto='pra que serve essa referência?'))
        ref = next(r for r in p['referencias_criativas'] if r['asset']['nome'] == 'pin-1.jpg')
        self.assertEqual((ref['papel'], ref['orientacao'], ref['cenas']), ('composicao', 'enquadramento baixo', ['saida']))
        self.assertEqual(p['ficha']['audio'], 'narracao')
        self.assertEqual(p['ficha']['restricoes'], ['sem texto na imagem'])


if __name__ == '__main__':
    unittest.main()
