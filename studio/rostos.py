"""Quais fotos da Ellie mostram o rosto.

O detector (OpenCV) é só um palpite: ele erra perfil e foto cortada no queixo. A marcação do Breno
(um clique na biblioteca) vale mais e fica salva em dados/rostos.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ALTURA_ANALISE = 640
TOPO_MAXIMO = 0.45  # rosto achado abaixo disso (ex.: no tênis) é falso positivo em foto de corpo


def _caixas(caminho: Path) -> list[tuple[float, float]]:
    """Faixas verticais (topo, base) dos rostos achados, em fração da altura da imagem."""
    try:
        import cv2
        import numpy
    except ImportError:
        return []
    img = Image.open(caminho).convert("L")
    escala = ALTURA_ANALISE / img.height
    cinza = numpy.array(img.resize((max(1, int(img.width * escala)), ALTURA_ANALISE)))
    faixas = []
    for nome in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + nome)
        for espelhar in (False, True):  # o detector de perfil só acha rosto virado para um lado
            alvo = cinza[:, ::-1].copy() if espelhar else cinza
            for (_x, y, _l, a) in detector.detectMultiScale(alvo, scaleFactor=1.08, minNeighbors=4, minSize=(24, 24)):
                topo = y / ALTURA_ANALISE
                if topo <= TOPO_MAXIMO:
                    faixas.append((topo, (y + a) / ALTURA_ANALISE))
    return faixas


def detectar(caminho: Path) -> bool:
    return bool(_caixas(caminho))


def ler(arquivo: Path) -> dict[str, dict]:
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mapa(pasta: Path, nomes: list[str], arquivo: Path) -> dict[str, bool]:
    """{nome: tem_rosto}. Detecta só o que ainda não foi visto e guarda o resultado."""
    dados = ler(arquivo)
    mudou = False
    for nome in nomes:
        if nome not in dados:
            dados[nome] = {"rosto": detectar(pasta / nome), "manual": False}
            mudou = True
    if mudou:
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return {n: bool(dados[n]["rosto"]) for n in nomes}


def marcar(arquivo: Path, nome: str, rosto: bool) -> None:
    dados = ler(arquivo)
    dados[nome] = {"rosto": rosto, "manual": True}
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def recortar_sem_rosto(origem: Path, destino: Path) -> Path:
    """Corta a foto logo abaixo do queixo: vira referência de corpo e roupa sem rosto.
    Sem rosto detectado (ex.: perfil), corta 18% do topo, que é onde fica a cabeça numa foto de corpo inteiro."""
    faixas = _caixas(origem)
    corte = max(b for _t, b in faixas) + 0.02 if faixas else 0.18
    img = Image.open(origem)
    img.crop((0, int(img.height * min(corte, 0.5)), img.width, img.height)).save(destino)
    return destino
