"""Áudio primeiro: a voz decide os cortes, cenas de imagem são grátis e o acabamento sai pronto para postar."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from studio.cenas_voz import dividir_em, duracao_total, sincronizar
from studio.montagem import animar_imagem
from studio.montagem_narrada import checar
from studio.processo import AjustesNarracao, Mensagem, Processo
from test_narrado import FakeCli

ROTEIRO = "You are tired. You have waited so long. But God is not late. Save this for today."


def falar(texto: str, ritmo: float = 0.32, pausa: float = 0.35) -> list[dict]:
    """Palavras com tempo, pausa maior depois de cada frase (como sai do ElevenLabs)."""
    saida, t = [], 0.2
    for p in texto.split():
        saida.append({"p": p, "ini": round(t, 3), "fim": round(t + ritmo * 0.85, 3)})
        t += ritmo + (pausa if p[-1] in ".!?" else 0)
    return saida


class CenasVozTests(unittest.TestCase):
    def test_corta_no_respiro_entre_frases(self):
        w = falar(ROTEIRO)
        cenas = dividir_em(w, 4)
        self.assertEqual([c["texto"].split()[0] for c in cenas], ["You", "You", "But", "Save"])
        # o corte entra logo antes da primeira palavra da frase seguinte
        segunda = next(x for x in w[1:] if x["p"] == "You")
        self.assertAlmostEqual(cenas[1]["ini"], segunda["ini"] - 0.06, delta=1 / 30)
        self.assertEqual(cenas[-1]["fim"], duracao_total(w))

    def test_cortes_somam_a_duracao_em_quadros_exatos(self):
        w = falar(ROTEIRO)
        cenas = dividir_em(w, 3)
        quadros = sum(round((c["fim"] - c["ini"]) * 30) for c in cenas)
        self.assertEqual(quadros, round(duracao_total(w) * 30))

    def test_voz_longa_no_arquivo_vale_o_arquivo(self):
        w = falar("Peace be still.")
        self.assertEqual(duracao_total(w, 4.0), 4.0)

    def test_tomada_paga_curta_ganha_camera_lenta_ou_recusa(self):
        w = falar(ROTEIRO)
        tomadas = [{"id": "a", "titulo": "A", "duracao": 4}, {"id": "b", "titulo": "B", "tipo": "imagem", "duracao": 4}]
        cortes = [{"tomada": "a", "inicio": 0, "duracao": 4}, {"tomada": "b", "inicio": 0, "duracao": 4}]
        novos, total, _ = sincronizar(cortes, tomadas, w)
        self.assertAlmostEqual(sum(c["duracao"] for c in novos), total, delta=.01)
        self.assertGreaterEqual(novos[0]["velocidade"], 0.6)
        so_uma = [{"tomada": "a", "inicio": 0, "duracao": 4}]
        with self.assertRaisesRegex(ValueError, "cena de imagem"):
            sincronizar(so_uma, tomadas[:1], w + falar(ROTEIRO))  # ~20 s numa tomada de 4 s


class AudioPrimeiroTests(unittest.TestCase):
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
            img = Image.new('RGB', (360, 640), cor)
            for k in range(0, 640, 40):  # grade: o movimento aparece em qualquer direção
                img.paste('white', (k, 0, k + 6, 640))
                img.paste('white', (0, k, 360, k + 6))
            img.save(self.root / 'quadros' / nome)
        self.cli = FakeCli()
        self.s = Processo(self.root, lambda *a: '{"mensagem_pt":"ok"}', cli=self.cli, imagem=lambda *a: 'x.png')
        self.p = self.s.create('fé')

    def tearDown(self):
        self.temp.cleanup()

    def _voz(self, segundos: float) -> str:
        out = self.s.output(self.p['id'])
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=44100',
                        '-af', 'volume=0.3', '-t', str(segundos), '-y', str(out / 'voz.mp3')], check=True)
        return 'voz.mp3'

    def _plano_imagens(self) -> dict:
        p = self.s.store.get(self.p['id'])
        cenas = [("c1", "ceu.png", "aproximar"), ("c2", "mar.png", "descer"), ("c3", "luz.png", "afastar")]
        return self.s.save_plan(p, {"tomadas": [
            {"id": i, "titulo": i.upper(), "tipo": "imagem", "movimento_local": m, "duracao": 4,
             "prompt": "Slow camera move over the still.", "imagens": [{"pasta": "quadros", "nome": n}]}
            for i, n, m in cenas]}, p['versao'])

    def _com_voz(self, palavras: list[dict], segundos: float, **extra):
        p = self.s.store.get(self.p['id'])
        p['narracao'].update(texto=" ".join(w['p'] for w in palavras), audio=self._voz(segundos), palavras=palavras, **extra)
        self.s.store.save(p)

    def test_animar_imagem_tem_movimento_e_duracao_exata(self):
        destino = self.root / 'saida' / 'anim.mp4'
        info = animar_imagem(self.root / 'quadros' / 'ceu.png', destino, 2.5, 'aproximar')
        self.assertEqual((info['width'], info['height']), (1080, 1920))
        self.assertAlmostEqual(info['duracao'], 2.5, delta=.05)
        self.assertEqual(checar(destino, 2.5), [])  # sem trecho congelado

    def test_cenas_de_imagem_seguem_a_voz_sem_creditos(self):
        self._plano_imagens()
        w = falar("You are tired. You have waited so long. But God is not late.")
        self._com_voz(w, duracao_total(w) - 0.3)
        with self.assertRaisesRegex(ValueError, "não usam créditos"):
            self.s.prepare_quote(self.p['id'])
        p = self.s.render(self.p['id'])
        esperado = duracao_total(w)
        self.assertAlmostEqual(p['resultado']['duracao'], esperado, delta=.1)
        self.assertEqual(p['duracao_final'], esperado)
        # um corte por frase, na ordem do plano
        self.assertEqual([c['tomada'] for c in p['cortes']], ['c1', 'c2', 'c3'])
        self.assertEqual(p['resultado']['avisos'], [])
        self.assertEqual(self.cli.validados, [])  # nada passou pelo Dreamina

    def test_cotacao_so_da_tomada_paga(self):
        p = self._plano_imagens()
        tomadas = [*p['tomadas'], {"id": "gancho", "titulo": "Gancho", "duracao": 4, "prompt": "Waves crash, slow motion.",
                                   "imagens": [{"pasta": "quadros", "nome": "mar.png"}]}]
        p = self.s.save_plan(p, {"tomadas": tomadas}, p['versao'])
        p = self.s.prepare_quote(self.p['id'])
        self.assertEqual(p['cotacao']['tomadas'], ['gancho'])
        hash_antes = p['cotacao']['hash']
        p['tomadas'][0]['movimento_local'] = 'subir'  # mexer numa cena grátis não invalida a cotação
        self.assertEqual(self.s.generation_hash(p), hash_antes)

    def test_acabamento_trilha_whoosh_elegante_e_loudness(self):
        self._plano_imagens()
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=44100', '-t', '2',
                        '-y', str(self.root / 'trilhas' / 'piano.mp3')], check=True)  # mais curta que o vídeo: repete
        w = falar("You are tired. You have waited so long. But God is not late.")
        self._com_voz(w, duracao_total(w) - 0.3)
        p = self.s.ajustar_narracao(self.p['id'], AjustesNarracao(estilo_legenda='elegante', trilha='piano.mp3', sfx=True))
        self.assertEqual(p['narracao']['trilha'], 'piano.mp3')
        p = self.s.render(self.p['id'])
        final = self.s.output(self.p['id']) / p['resultado']['nome']
        r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(final), '-af', 'ebur128', '-f', 'null', '-'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
        self.assertAlmostEqual(lufs, -14, delta=2.5)
        self.assertEqual(p['resultado']['avisos'], [])

    def test_trilha_inexistente_e_recusada(self):
        with self.assertRaisesRegex(ValueError, 'Trilha não encontrada'):
            self.s.ajustar_narracao(self.p['id'], AjustesNarracao(trilha='nao-existe.mp3'))

    def test_checagem_acha_quadro_congelado(self):
        destino = self.root / 'saida' / 'parado.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:size=360x640:rate=30', '-t', '2',
                        '-pix_fmt', 'yuv420p', '-y', str(destino)], check=True)
        self.assertTrue(any('parada' in a for a in checar(destino, 2)))

    # ---- Problemas vistos na produção "vídeo de Jesus" (20/10/2026) ----
    def _voz_pela_rota_real(self, texto: str):
        """Grava a voz como o envio de áudio faz (com mensagem e cenas), sem Whisper."""
        w = falar(texto)
        out = self.s.output(self.p['id'])
        self._voz(duracao_total(w) - 0.3)
        def gravar(atual):
            return {**atual, "narracao": {**atual["narracao"], "texto": texto, "audio": "voz.mp3", "palavras": w}}
        self.s._voz_pronta(self.p['id'], "Áudio recebido", w, out / "voz.mp3", gravar)
        return self.s.store.get(self.p['id'])

    def test_duracao_fracionaria_da_ia_nao_derruba_o_plano(self):
        p = self.s.store.get(self.p['id'])
        p = self.s.save_plan(p, {"tomadas": [{"id": "a", "titulo": "A", "duracao": 6.3, "prompt": "Some slow motion."}]}, p['versao'])
        self.assertEqual(p['tomadas'][0]['duracao'], 7)

    def test_plano_invalido_mantem_a_resposta_e_nao_culpa_o_openclaw(self):
        self.s.ask = lambda *a: json.dumps({"mensagem_pt": "Sim, são essas três.",
                                            "plano": {"tomadas": [{"id": "x", "titulo": "X", "prompt": "curto"}]}})
        p = self.s.chat(self.p['id'], Mensagem(texto='essas são as 3 imagens?'))
        ultima = p['mensagens'][-1]
        self.assertNotIn('Sim, são essas três.', ultima['texto'])  # não anunciar sucesso de um plano rejeitado
        self.assertIn('Não apliquei', ultima['texto'])
        self.assertNotIn('OpenClaw', ultima['texto'])
        self.assertFalse(any(b['tipo'] == 'conexao' for b in ultima['blocos']))

    def test_voz_pronta_cria_uma_cena_por_frase_e_converte_o_quadro_pago(self):
        # como no chat: imagem do Pinterest virou quadro (tomada paga de 10 s) antes da voz existir
        p = self.s.usar_como_quadro(self.s.store.get(self.p['id']), {"pasta": "quadros", "nome": "ceu.png"})
        self.assertEqual(p['tomadas'][0]['tipo'], 'video')
        p = self._voz_pela_rota_real("If your heart feels heavy today, hear this: Jesus has not left you. "
                                     "Give Him what you cannot carry. Save this for when you need it.")
        self.assertEqual(len(p['tomadas']), 3)
        self.assertTrue(all(s['tipo'] == 'imagem' for s in p['tomadas']))  # nada pago por padrão
        self.assertEqual(p['tomadas'][0]['imagens'], [{"pasta": "quadros", "nome": "ceu.png"}])
        self.assertTrue(p['tomadas'][1]['titulo'].startswith('Frase 2'))
        self.assertEqual([c['tomada'] for c in p['cortes']], [s['id'] for s in p['tomadas']])
        self.assertAlmostEqual(sum(c['duracao'] for c in p['cortes']), p['duracao_final'], delta=.01)
        msg = p['mensagens'][-1]
        self.assertIn('Frase 3', msg['texto'])
        self.assertIn('falta imagem', msg['texto'])

    def test_imagens_geradas_preenchem_cena_por_cena(self):
        self._voz_pela_rota_real("You are tired. Give Him what you cannot carry. Save this for today.")
        ids = [s['id'] for s in self.s.store.get(self.p['id'])['tomadas']]
        self.s.imagem = lambda pasta, desc, nome, refs, ellie: 'mar.png'
        self.s._gerar_imagem(self.p['id'], 'quadros', 'stone', [], False, ids[1])  # cena pedida pela IA
        self.s.imagem = lambda *a: 'luz.png'
        self.s._gerar_imagem(self.p['id'], 'quadros', 'opening', [], False)  # sem cena: a primeira vazia
        p = self.s.store.get(self.p['id'])
        self.assertEqual([[a['nome'] for a in s['imagens']] for s in p['tomadas']], [['luz.png'], ['mar.png'], []])
        self.assertTrue(any('Ainda sem imagem' in m['texto'] for m in p['mensagens'][-3:]))
        self.s.imagem = lambda *a: 'ceu.png'
        self.s._gerar_imagem(self.p['id'], 'quadros', 'path', [], False)
        self.s.imagem = lambda *a: 'ceu.png'
        self.s._gerar_imagem(self.p['id'], 'quadros', 'extra', [], False)  # tudo cheio: não troca no chute
        p = self.s.store.get(self.p['id'])
        self.assertEqual([s['imagens'][0]['nome'] for s in p['tomadas']], ['luz.png', 'mar.png', 'ceu.png'])
        self.assertTrue(any('não entrou em nenhuma cena' in m['texto'] for m in p['mensagens'][-3:]))

    def test_mais_uma_com_cena_vazia_vai_para_a_ia_e_nao_repete_a_ultima(self):
        self._voz_pela_rota_real("You are tired. Give Him what you cannot carry. Save this for today.")
        p = self.s.store.get(self.p['id'])
        p['ultimo_pedido_imagem'] = {"pasta": "quadros", "descricao": "stone", "referencias": [], "usar_ellie": False}
        self.s.store.save(p)
        chamadas = []
        self.s.ask = lambda *a: chamadas.append(1) or json.dumps({"mensagem_pt": "Vou criar a próxima cena."})
        self.s.chat(self.p['id'], Mensagem(texto='pode gerar mais uma'))
        self.assertEqual(chamadas, [1])

    def test_ia_recebe_as_frases_com_tempo(self):
        w = falar("You are tired. But God is not late.")
        self._com_voz(w, duracao_total(w) - 0.3)
        recebido = {}
        def ask(texto, fotos):
            recebido['texto'] = texto
            return json.dumps({"mensagem_pt": "ok"})
        self.s.ask = ask
        self.s.chat(self.p['id'], Mensagem(texto='Planejar as cenas pela voz'))
        estado = json.loads(recebido['texto'].split('ESTADO REAL:\n')[1].split('\nBIBLIOTECA REAL:')[0])
        frases = estado['narracao']['frases']
        self.assertEqual([f['texto'] for f in frases], ['You are tired.', 'But God is not late.'])
        self.assertAlmostEqual(estado['narracao']['duracao_voz'], duracao_total(w), delta=.05)


if __name__ == '__main__':
    unittest.main()
