"""Camada de narração (voz + legenda karaokê + setas no CTA) sobre qualquer vídeo montado, tudo local, sem créditos.

- Vídeo: o vídeo montado (1 ou várias cenas), ajustado para 1080x1920; se a voz for mais longa, segura o último quadro.
- Legenda: 2 a 3 palavras por vez, MAIÚSCULAS, branca com contorno preto, palavra falada em amarelo.
  Desenhada com Pillow (não depende de libass no ffmpeg do Windows).
- Setas: indicação vermelha na lateral direita, apontando para os botões do TikTok, a partir do CTA (se houver CTA).
- Áudio: só a narração (o áudio gerado pelo modelo de vídeo é descartado).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.montagem import ffmpeg, probe
from studio.narracao import duracao_audio

L, A = 1080, 1920
AMARELO, BRANCO, PRETO = (255, 230, 0), (255, 255, 255), (0, 0, 0)
FONTES = ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/impact.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def fonte(tamanho: int):
    for caminho in FONTES:
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(size=tamanho)


def blocos(palavras: list[dict], maximo: int = 3) -> list[list[int]]:
    """Agrupa índices de palavras em blocos de até `maximo`, quebrando após pontuação."""
    grupos, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(i)
        if len(atual) >= maximo or w["p"][-1:] in ".!?,;:":
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def _desenhar_bloco(palavras: list[str], ativa: int, destino: Path, tamanho: int = 92) -> None:
    f = fonte(tamanho)
    contorno = max(6, tamanho // 11)
    textos = [p.upper().strip(".,;:!?\"“”") for p in palavras]
    espaco = f.getlength(" ")
    larguras = [f.getlength(t) for t in textos]
    total = sum(larguras) + espaco * (len(textos) - 1)
    escala = min(1.0, (L - 120) / max(total, 1))
    if escala < 1:
        return _desenhar_bloco(palavras, ativa, destino, int(tamanho * escala))
    img = Image.new("RGBA", (L, tamanho + contorno * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = (L - total) / 2
    for i, (t, w) in enumerate(zip(textos, larguras)):
        d.text((x, contorno), t, font=f, fill=AMARELO if i == ativa else BRANCO, stroke_width=contorno, stroke_fill=PRETO)
        x += w + espaco
    img.save(destino)


def setas(destino: Path, quantidade: int = 5) -> None:
    """Setas vermelhas empilhadas apontando para a direita (coluna de botões do TikTok)."""
    img = Image.new("RGBA", (190, 620), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    passo = 620 // quantidade
    for i in range(quantidade):
        y = passo * i + passo // 2
        d.line([(20, y), (150, y)], fill=(230, 20, 20, 255), width=14)
        d.polygon([(185, y), (138, y - 30), (138, y + 30)], fill=(230, 20, 20, 255))
    img.save(destino)


def eventos_legenda(palavras: list[dict], pasta: Path, fim_total: float) -> list[tuple[Path, float, float]]:
    """Uma imagem por palavra falada: o bloco inteiro com aquela palavra em amarelo."""
    pasta.mkdir(parents=True, exist_ok=True)
    eventos = []
    grupos = blocos(palavras)
    for g, grupo in enumerate(grupos):
        fim_bloco = palavras[grupos[g + 1][0]]["ini"] if g + 1 < len(grupos) else min(fim_total, palavras[grupo[-1]]["fim"] + 0.6)
        for k, i in enumerate(grupo):
            ini = palavras[i]["ini"]
            fim = palavras[grupo[k + 1]]["ini"] if k + 1 < len(grupo) else fim_bloco
            caminho = pasta / f"leg_{i:03d}.png"
            _desenhar_bloco([palavras[j]["p"] for j in grupo], k, caminho)
            eventos.append((caminho, max(0.0, ini), max(ini + 0.05, fim)))
    return eventos


PALAVRAS_CTA = ("comment", "follow", "type", "share", "save", "subscribe", "like", "tag", "send", "write")


def _norm(t: str) -> str:
    return "".join(c for c in t.lower() if c.isalnum() or c == "'")


def inicio_cta(palavras: list[dict], cta: str = "") -> float | None:
    """Quando a chamada para ação começa. Usa a frase de CTA do plano; sem ela, a última frase que começa
    com um verbo típico de CTA. Sem CTA reconhecível: None (sem setas)."""
    alvo = [_norm(t) for t in cta.split() if _norm(t)][:3]
    faladas = [_norm(w["p"]) for w in palavras]
    if alvo:
        for i in range(len(faladas) - 1, -1, -1):
            if faladas[i:i + len(alvo)] == alvo or (faladas[i] == alvo[0] and len(alvo) == 1):
                return palavras[i]["ini"]
        for i in range(len(faladas) - 1, -1, -1):  # o Whisper pode errar: basta a primeira palavra
            if faladas[i] == alvo[0]:
                return palavras[i]["ini"]
    for i, w in enumerate(palavras):
        inicio_frase = i == 0 or palavras[i - 1]["p"][-1:] in ".!?"
        if inicio_frase and faladas[i] in PALAVRAS_CTA:
            return w["ini"]
    return None


def montar_narrado(video: Path, audio: Path, palavras: list[dict], saida: Path, cta_inicio: float | None = None,
                   setas_ativas: bool = True, altura_legenda: float = 0.60, cta: str = "", minimo: float = 0.0) -> dict:
    if not palavras:
        raise ValueError("A narração não tem tempos de palavras. Gere a voz ou envie o áudio de novo.")
    trabalho = saida.parent / (saida.stem + "-partes")
    trabalho.mkdir(parents=True, exist_ok=True)
    dur_voz = duracao_audio(audio)
    dur_video = probe(video)["duracao"]
    total = round(max(dur_voz + 0.6, min(minimo, dur_video)), 2)
    extra = max(0.0, total - dur_video)
    eventos = eventos_legenda(palavras, trabalho / "legenda", total)
    entradas = ["-i", str(video), "-i", str(audio)]
    filtros = [f"[0:v]scale={L}:{A}:force_original_aspect_ratio=increase,crop={L}:{A},setsar=1,fps=30"
               + (f",tpad=stop_mode=clone:stop_duration={extra:.2f}" if extra > 0 else "") + "[v0]"]
    atual, n = "v0", 2
    if cta_inicio is None:
        cta_inicio = inicio_cta(palavras, cta)
    if setas_ativas and cta_inicio is not None:
        setas(trabalho / "setas.png")
        entradas += ["-loop", "1", "-t", str(total), "-i", str(trabalho / "setas.png")]
        filtros.append(f"[{atual}][{n}:v]overlay=x=W-w-150:y=H*0.42:enable='gte(t,{cta_inicio:.2f})'[s]")
        atual, n = "s", n + 1
    for k, (png, ini, fim) in enumerate(eventos):
        entradas += ["-loop", "1", "-t", str(total), "-i", str(png)]
        rotulo = f"l{k}"
        filtros.append(f"[{atual}][{n}:v]overlay=x=0:y=H*{altura_legenda}-h/2:enable='between(t,{ini:.3f},{fim:.3f})'[{rotulo}]")
        atual, n = rotulo, n + 1
    grafo = ";".join(filtros)
    # -filter_complex_script foi removido no ffmpeg 8. Grafo curto vai direto na linha de comando;
    # longo (limite do Windows ~32 mil caracteres) vai por arquivo com a sintaxe nova "-/filter_complex".
    if len(grafo) < 20000:
        opcao_filtro = ["-filter_complex", grafo]
    else:
        roteiro = trabalho / "filtros.txt"
        roteiro.write_text(grafo, encoding="utf-8")
        opcao_filtro = ["-/filter_complex", str(roteiro)]
    ffmpeg(*entradas, *opcao_filtro, "-map", f"[{atual}]", "-map", "1:a",
           "-t", str(total), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(saida))
    info = probe(saida)
    return {"caminho": str(saida), "duracao": info["duracao"], "width": info.get("width"), "height": info.get("height")}
