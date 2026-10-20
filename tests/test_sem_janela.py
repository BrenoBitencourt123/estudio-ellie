"""Nenhum programa externo pode abrir janela de console.

O supervisor inicia o servidor com CREATE_NO_WINDOW, então o processo do Estúdio não tem console.
No Windows, todo filho que seja programa de console (ffmpeg, ffprobe, CLI do Dreamina, node) ganha
um console novo — a janela preta que piscava na tela a cada operação. Passar a mesma flag resolve.
"""
import ast
import unittest
from pathlib import Path
from unittest import mock

from studio.processos import SEM_JANELA, rodar

RAIZ = Path(__file__).resolve().parent.parent
FONTES = sorted((RAIZ / "studio").glob("*.py")) + [RAIZ / "gerar.py"]


def chamadas_cruas(arquivo: Path) -> list[int]:
    """Linhas com subprocess.run/Popen que não desligam a janela."""
    linhas = []
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        alvo = getattr(no, "func", None)
        if (isinstance(no, ast.Call) and isinstance(alvo, ast.Attribute) and alvo.attr in ("run", "Popen")
                and isinstance(alvo.value, ast.Name) and alvo.value.id == "subprocess"
                and not any(k.arg == "creationflags" for k in no.keywords)):
            linhas.append(no.lineno)
    return linhas


class SemJanelaTests(unittest.TestCase):
    def test_rodar_desliga_a_janela(self):
        recebido = {}
        with mock.patch("studio.processos.subprocess.run", side_effect=lambda c, **k: recebido.update(k)):
            rodar(["ffprobe", "-version"], capture_output=True)
        self.assertEqual(recebido["creationflags"], SEM_JANELA)

    def test_rodar_respeita_o_input_de_quem_chamou(self):
        recebido = {}
        with mock.patch("studio.processos.subprocess.run", side_effect=lambda c, **k: recebido.update(k)):
            rodar(["x"], input="oi")
        self.assertNotIn("stdin", recebido)  # subprocess recusa input e stdin juntos

    def test_nenhuma_chamada_crua_no_servidor(self):
        """`studio/processos.py` é o único lugar que pode chamar subprocess sem a flag."""
        sobrou = {a.name: chamadas_cruas(a) for a in FONTES if a.name != "processos.py"}
        sobrou = {nome: linhas for nome, linhas in sobrou.items() if linhas}
        self.assertEqual(sobrou, {}, f"chamadas que ainda abrem janela: {sobrou}")


if __name__ == "__main__":
    unittest.main()
