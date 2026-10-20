"""
Texto na tela automático (gancho do vídeo), no estilo que aprovamos: sem contorno, letra escura em fundo claro
ou branca em fundo escuro, com um halo suave. A posição é escolhida olhando vários quadros do vídeo: a área mais
lisa e estável (sem cabelo, mão ou objeto passando), fora das zonas que o TikTok cobre (abas no topo, ícones à
direita, legenda e música embaixo).
"""

import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from studio.processos import rodar

LARGURA, ALTURA = 1080, 1920
FONTES = {
    "serifa": ("C:/Windows/Fonts/georgiai.ttf", 64),
    "sans": ("C:/Windows/Fonts/segoeui.ttf", 66),
    "negrito": ("C:/Windows/Fonts/segoeuib.ttf", 62),
}
LARGURA_BLOCO = 470
X_CENTROS = (0.36, 0.43, 0.50, 0.57, 0.64)
Y_TOPOS = (0.11, 0.16, 0.21, 0.27, 0.33, 0.40)
# Posição pedida pelo Breno: auto escolhe sozinho; alto e meio limitam a faixa de altura
FAIXAS = {"auto": Y_TOPOS, "alto": (0.11, 0.16, 0.21), "meio": (0.27, 0.33, 0.40)}
COR_ESCURA, COR_CLARA = (34, 30, 28, 255), (255, 255, 255, 255)


def _quebrar(texto: str, fonte: ImageFont.FreeTypeFont, maximo: int) -> list[str]:
    if "|" in texto:  # quebra manual
        return [l.strip() for l in texto.split("|") if l.strip()]
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if fonte.getlength(teste) <= maximo or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    return linhas + ([atual] if atual else [])


def _duracao(video: Path) -> float:
    r = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
              capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def _quadros(video: Path, pasta: Path, quantidade: int = 8) -> list[Path]:
    dur = max(_duracao(video), 1)
    rodar(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
           "-vf", f"fps={quantidade / dur:.4f},scale=360:-2", "-frames:v", str(quantidade),
           str(pasta / "q_%02d.png")], check=True)
    return sorted(pasta.glob("q_*.png"))


def _rostos(imagens: list[Image.Image]) -> list[tuple[float, float, float, float]]:
    """Rostos encontrados nos quadros, em coordenadas do vídeo 1080x1920 e com margem (o texto nunca cobre o rosto)."""
    try:
        import cv2
        import numpy
    except ImportError:
        return []
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    rostos = []
    for img in imagens:
        escala = LARGURA / img.width
        for (x, y, l, a) in detector.detectMultiScale(numpy.array(img), scaleFactor=1.1, minNeighbors=5, minSize=(18, 18)):
            m = 0.35  # margem em volta do rosto (cabelo, queixo)
            rostos.append(((x - l * m) * escala, (y - a * m) * escala, (x + l * (1 + m)) * escala, (y + a * (1 + m)) * escala))
    return rostos


def _escolher_posicao(quadros: list[Path], altura_bloco: int, posicao: str = "auto") -> tuple[float, float, float]:
    """Devolve (centro_x, topo, luminosidade média) da área mais lisa e estável."""
    imagens = [Image.open(q).convert("L") for q in quadros]
    rostos = _rostos(imagens)
    melhor = None
    for cx in X_CENTROS:
        for ty in FAIXAS.get(posicao, Y_TOPOS):
            caixas_std, caixas_media = [], []
            for img in imagens:
                sx, sy = img.width / LARGURA, img.height / ALTURA
                caixa = (int((cx * LARGURA - LARGURA_BLOCO / 2) * sx), int(ty * ALTURA * sy),
                         int((cx * LARGURA + LARGURA_BLOCO / 2) * sx), int((ty * ALTURA + altura_bloco) * sy))
                stat = ImageStat.Stat(img.crop(caixa))
                caixas_std.append(stat.stddev[0])
                caixas_media.append(stat.mean[0])
            # Fundo liso (pouca textura), estável no tempo (nada passando) e de preferência perto do centro
            # Leve preferência pela parte de cima (onde o gancho costuma ficar no TikTok)
            x0, y0 = cx * LARGURA - LARGURA_BLOCO / 2, ty * ALTURA
            x1, y1 = x0 + LARGURA_BLOCO, y0 + altura_bloco
            cobre_rosto = any(x0 < rx1 and rx0 < x1 and y0 < ry1 and ry0 < y1 for rx0, ry0, rx1, ry1 in rostos)
            nota = (1000 if cobre_rosto else 0) + statistics.mean(caixas_std) + 1.5 * statistics.pstdev(caixas_media) + 40 * abs(cx - 0.5) + 12 * ty
            if melhor is None or nota < melhor[0]:
                melhor = (nota, cx, ty, statistics.mean(caixas_media))
    return melhor[1], melhor[2], melhor[3]


def aplicar(entrada: Path, saida: Path, texto: str, estilo: str = "serifa", posicao: str = "auto") -> dict:
    caminho_fonte, tamanho = FONTES.get(estilo, FONTES["serifa"])
    fonte = ImageFont.truetype(caminho_fonte, tamanho)
    linhas = _quebrar(texto, fonte, LARGURA_BLOCO)
    while len(linhas) > 4 and tamanho > 44:  # texto longo: diminui a letra até caber em 4 linhas
        tamanho -= 4
        fonte = ImageFont.truetype(caminho_fonte, tamanho)
        linhas = _quebrar(texto, fonte, LARGURA_BLOCO)
    entrelinha = int(tamanho * 1.22)
    altura_bloco = entrelinha * len(linhas)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cx, topo_rel, luminosidade = _escolher_posicao(_quadros(entrada, tmp), altura_bloco, posicao)
        escuro = luminosidade >= 140
        letra, halo = (COR_ESCURA, (255, 255, 255, 170)) if escuro else (COR_CLARA, (0, 0, 0, 150))

        texto_img = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
        sombra = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
        dt, ds = ImageDraw.Draw(texto_img), ImageDraw.Draw(sombra)
        topo = int(topo_rel * ALTURA)
        for i, linha in enumerate(linhas):
            x = cx * LARGURA - fonte.getlength(linha) / 2
            y = topo + i * entrelinha
            ds.text((x, y + (2 if escuro else 4)), linha, font=fonte, fill=halo)
            dt.text((x, y), linha, font=fonte, fill=letra)
        camada = Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(10)), texto_img)
        png = tmp / "texto.png"
        camada.save(png)

        resultado = rodar([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(entrada), "-i", str(png),
            "-filter_complex", f"[0:v]scale={LARGURA}:{ALTURA}[v];[v][1:v]overlay=0:0",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(saida),
        ], capture_output=True, text=True)
        if resultado.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou ao aplicar o texto: {resultado.stderr.strip()[:300]}")
    return {"centro_x": cx, "topo": topo_rel, "cor": "escura" if escuro else "clara", "linhas": linhas}


# ---------------------------------------------------------------------------
# Editor visual: o navegador desenha o texto (prévia = resultado) e o servidor só sugere a posição e cola no vídeo
# ---------------------------------------------------------------------------

def posicao_sugerida(entrada: Path, altura_bloco: int, largura_bloco: int = LARGURA_BLOCO, posicao: str = "auto") -> dict:
    """Área mais lisa e estável para um bloco de texto do tamanho pedido (x = centro, y = topo, de 0 a 1)."""
    global LARGURA_BLOCO
    original = LARGURA_BLOCO
    LARGURA_BLOCO = max(200, min(900, largura_bloco))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cx, topo, luminosidade = _escolher_posicao(_quadros(entrada, Path(tmp)), altura_bloco, posicao)
    finally:
        LARGURA_BLOCO = original
    return {"x": cx, "y": topo, "luminosidade": round(luminosidade), "cor": "#221e1c" if luminosidade >= 140 else "#ffffff"}


def compor(entrada: Path, camada_png: Path, saida: Path) -> None:
    """Cola uma camada PNG transparente de 1080x1920 sobre o vídeo inteiro."""
    with Image.open(camada_png) as img:
        if img.size != (LARGURA, ALTURA) or img.mode != "RGBA":
            raise RuntimeError(f"A camada de texto precisa ser PNG RGBA de {LARGURA}x{ALTURA} (veio {img.size} {img.mode}).")
    resultado = rodar([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(entrada), "-i", str(camada_png),
        "-filter_complex", f"[0:v]scale={LARGURA}:{ALTURA}[v];[v][1:v]overlay=0:0",
        "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(saida),
    ], capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao aplicar o texto: {resultado.stderr.strip()[:300]}")
