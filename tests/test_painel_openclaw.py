"""Botão do painel do OpenClaw: usa o link de uso único do próprio OpenClaw, sem expor o token."""
import json
import subprocess
import unittest
from unittest import mock

from studio import processo


class PainelTests(unittest.TestCase):
    def rodar(self, stdout, code=0, stderr=""):
        r = subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)
        with mock.patch.object(processo, "achar_openclaw", return_value="openclaw"), \
             mock.patch("subprocess.run", return_value=r) as run:
            return processo.abrir_painel_openclaw(), run

    def test_usa_browser_url(self):
        saida = json.dumps({"url": "http://127.0.0.1:18789/", "browserUrl": "http://127.0.0.1:18789/#bootstrap=abc"})
        res, run = self.rodar("aviso qualquer\n" + saida)
        self.assertEqual(res["url"], "http://127.0.0.1:18789/#bootstrap=abc")
        self.assertEqual(run.call_args.args[0][1:], ["dashboard", "--json"])

    def test_falha_abre_endereco_normal_com_aviso(self):
        res, _ = self.rodar(json.dumps({"ok": False, "reason": "device-required"}), code=1)
        self.assertEqual(res["url"], "http://127.0.0.1:18789/")
        self.assertIn("device-required", res["aviso"])

    def test_sem_openclaw(self):
        with mock.patch.object(processo, "achar_openclaw", return_value=None), mock.patch.dict("os.environ", {"OPENCLAW_URL": ""}):
            res = processo.abrir_painel_openclaw()
        self.assertEqual(res["url"], "http://127.0.0.1:18789/")
