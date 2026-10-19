"""Busca de referências no Pinterest (sem API nem chave): roda o scraper do pinterest-mcp-server
(studio/pinterest/buscar.bundle.mjs, Chrome/Edge escondido) e baixa as imagens para a pasta referencias."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

PASTA_SCRIPT = Path(__file__).resolve().parent / "pinterest"
EXTENSOES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def achar_node() -> str | None:
    candidatos = [shutil.which("node"),
                  str(Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe")]
    return next((c for c in candidatos if c and Path(c).exists()), None)


def pesquisar(termo: str, quantidade: int = 10, timeout: int = 150) -> list[dict]:
    """Resultados crus do Pinterest: [{title, image_url, link}]."""
    script = PASTA_SCRIPT / "buscar.bundle.mjs"
    if not script.exists():
        script = PASTA_SCRIPT / "buscar.mjs"  # versão com node_modules (npm install em studio/pinterest)
    node = achar_node()
    if not node:
        raise ValueError("Não achei o Node.js para rodar a busca do Pinterest.")
    try:
        r = subprocess.run([node, str(script), termo, str(quantidade)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           cwd=str(PASTA_SCRIPT), creationflags=0x08000000 if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise ValueError("O Pinterest demorou demais para responder. Tente de novo ou com um termo mais curto.") from None
    linhas = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    try:
        dados = json.loads(linhas[-1])
    except (IndexError, ValueError):
        raise ValueError("A busca do Pinterest não respondeu: " + (r.stderr.strip().splitlines() or ["sem detalhes"])[-1][:300]) from None
    if not dados.get("ok"):
        raise ValueError(str(dados.get("erro") or "A busca do Pinterest falhou.")[:300])
    return dados.get("resultados") or []


def _baixar(url: str) -> tuple[bytes, str] | None:
    """Tenta o original e, se o Pinterest recusar, a versão 736px."""
    for tentativa in (url, re.sub(r"/originals/", "/736x/", url)):
        try:
            resp = requests.get(tentativa, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200 or len(resp.content) < 2000:
                continue
            img = Image.open(BytesIO(resp.content))
            img.verify()
            ext = EXTENSOES.get(img.format or "")
            if ext:
                return resp.content, ext
        except (requests.RequestException, OSError, Image.DecompressionBombError):
            continue
    return None


def slug(texto: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "busca"


def buscar_e_baixar(termo: str, destino: Path, quantidade: int = 10, pesquisa=pesquisar, baixar=_baixar) -> list[str]:
    """Baixa até `quantidade` imagens para `destino`. Devolve os nomes salvos (a mesma imagem não é baixada duas vezes)."""
    destino.mkdir(parents=True, exist_ok=True)
    resultados = pesquisa(termo, quantidade + 4)  # alguns links falham; pede um pouco a mais
    nomes: list[str] = []
    base = slug(termo)
    for item in resultados:
        if len(nomes) >= quantidade:
            break
        url = str(item.get("image_url") or "")
        if not url.startswith("https://"):
            continue
        chave = hashlib.sha1(url.encode()).hexdigest()[:10]
        existente = next(destino.glob(f"*-{chave}.*"), None)
        if existente:
            nomes.append(existente.name)
            continue
        baixado = baixar(url)
        if not baixado:
            continue
        conteudo, ext = baixado
        nome = f"pin-{base}-{chave}{ext}"
        (destino / nome).write_bytes(conteudo)
        nomes.append(nome)
    return nomes
