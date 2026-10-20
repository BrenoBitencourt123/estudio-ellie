"""Chamadas a programas externos sem abrir janela preta no Windows.

O supervisor inicia o servidor com CREATE_NO_WINDOW, então o processo do Estúdio não tem console.
Quando ele chama um programa de console (ffmpeg, ffprobe, a CLI do Dreamina, node), o Windows cria
um console novo para esse filho — é a janela do cmd que pisca na tela a cada operação.
Passar a mesma flag para os filhos resolve: eles herdam a ausência de console.

Todo `subprocess.run` deste projeto deve passar por aqui.
"""
from __future__ import annotations

import os
import subprocess

SEM_JANELA = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def rodar(comando, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run com a janela de console desligada no Windows."""
    kwargs.setdefault("creationflags", SEM_JANELA)
    if "input" not in kwargs:
        # Sem isto o ffmpeg pode ficar esperando entrada quando o processo não tem console
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(comando, **kwargs)
