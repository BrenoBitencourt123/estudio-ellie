"""Camada de narração (voz + legenda + setas no CTA + trilha) sobre qualquer vídeo montado, tudo local, sem créditos.

- Vídeo: o vídeo montado (1 ou várias cenas), ajustado para 1080x1920. No modo áudio primeiro os cortes já
  seguem a voz e o vídeo tem a duração dela; o quadro congelado só sobra como reserva do lado a lado.
- Legenda: 2 a 3 palavras por vez, palavra falada destacada. "karaoke": MAIÚSCULAS brancas com contorno
  preto e destaque amarelo. "elegante": serifa, sombra suave e destaque dourado (bom para fé e reflexão).
  Desenhada com Pillow (não depende de libass no ffmpeg do Windows), dentro da área segura do TikTok.
- Setas: indicação vermelha na lateral direita, apontando para os botões do TikTok, a partir do CTA (se houver CTA).
- Áudio: narração + trilha opcional que abaixa sozinha quando a voz fala (ducking) + whoosh opcional nos
  cortes, tudo normalizado para -14 LUFS. O áudio gerado pelo modelo de vídeo é descartado.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from studio.montagem import ffmpeg, probe, tem_audio
from studio.narracao import duracao_audio
from studio.processos import rodar

L, A = 1080, 1920
AMARELO, BRANCO, PRETO, DOURADO = (255, 230, 0), (255, 255, 255), (0, 0, 0), (246, 210, 122)
# Fora da coluna de botões do TikTok (direita) e com margem nas bordas
LARGURA_SEGURA = 820
FONTES = ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/impact.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONTES_ELEGANTE = ["C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/BOD_B.TTF", "C:/Windows/Fonts/timesbd.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]
ESTILOS_LEGENDA = ("karaoke", "elegante")
LUFS_ALVO = -14


def fonte(tamanho: int, estilo: str = "karaoke"):
    for caminho in FONTES_ELEGANTE if estilo == "elegante" else FONTES:
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
    escala = min(1.0, LARGURA_SEGURA / max(total, 1))
    if escala < 1:
        return _desenhar_bloco(palavras, ativa, destino, int(tamanho * escala))
    img = Image.new("RGBA", (L, tamanho + contorno * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = (L - total) / 2
    for i, (t, w) in enumerate(zip(textos, larguras)):
        d.text((x, contorno), t, font=f, fill=AMARELO if i == ativa else BRANCO, stroke_width=contorno, stroke_fill=PRETO)
        x += w + espaco
    img.save(destino)


def _desenhar_elegante(palavras: list[str], ativa: int, destino: Path, tamanho: int = 90) -> None:
    """Serifa em caixa normal, sombra desfocada em vez de contorno grosso, palavra falada em dourado."""
    f = fonte(tamanho, "elegante")
    textos = [re.sub(r"[.,;:]+$", "", p.strip("\"“”")) for p in palavras]
    espaco = f.getlength(" ")
    larguras = [f.getlength(t) for t in textos]
    total = sum(larguras) + espaco * (len(textos) - 1)
    escala = min(1.0, LARGURA_SEGURA / max(total, 1))
    if escala < 1:
        return _desenhar_elegante(palavras, ativa, destino, int(tamanho * escala))
    margem = max(24, tamanho // 3)
    tamanho_img = (L, tamanho + margem * 3)
    sombra = Image.new("RGBA", tamanho_img, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sombra)
    x = (L - total) / 2
    for t, w in zip(textos, larguras):
        ds.text((x, margem + 4), t, font=f, fill=(0, 0, 0, 210))
        x += w + espaco
    img = sombra.filter(ImageFilter.GaussianBlur(max(4, tamanho // 10)))
    d = ImageDraw.Draw(img)
    x = (L - total) / 2
    for i, (t, w) in enumerate(zip(textos, larguras)):
        d.text((x, margem), t, font=f, fill=DOURADO if i == ativa else BRANCO, stroke_width=2, stroke_fill=(35, 25, 15))
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


def eventos_legenda(palavras: list[dict], pasta: Path, fim_total: float, estilo: str = "karaoke") -> list[tuple[Path, float, float]]:
    """Uma imagem por palavra falada: o bloco inteiro com aquela palavra destacada."""
    pasta.mkdir(parents=True, exist_ok=True)
    desenhar = _desenhar_elegante if estilo == "elegante" else _desenhar_bloco
    eventos = []
    grupos = blocos(palavras)
    for g, grupo in enumerate(grupos):
        fim_bloco = palavras[grupos[g + 1][0]]["ini"] if g + 1 < len(grupos) else min(fim_total, palavras[grupo[-1]]["fim"] + 0.6)
        for k, i in enumerate(grupo):
            ini = palavras[i]["ini"]
            fim = palavras[grupo[k + 1]]["ini"] if k + 1 < len(grupo) else fim_bloco
            caminho = pasta / f"leg_{i:03d}.png"
            desenhar([palavras[j]["p"] for j in grupo], k, caminho)
            eventos.append((caminho, max(0.0, ini), max(ini + 0.05, fim)))
    return eventos


def gerar_whoosh(destino: Path) -> None:
    """Whoosh curto e baixo (ruído rosa filtrado) que sobe até o corte. Sem arquivo de efeito externo."""
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:duration=0.45:amplitude=0.6",
           "-af", "highpass=f=350,lowpass=f=4500,afade=t=in:d=0.3:curve=exp,afade=t=out:st=0.3:d=0.15,volume=0.22",
           "-ac", "1", "-ar", "48000", "-y", str(destino))


def checar(caminho: Path, esperado: float) -> list[str]:
    """Conferência antes de entregar: duração, quadro congelado e volume no padrão das redes (-14 LUFS)."""
    avisos = []
    info = probe(caminho)
    if abs(info["duracao"] - esperado) > 0.15:
        avisos.append(f"O vídeo tem {info['duracao']:.1f}s e deveria ter {esperado:.1f}s.")
    som = ["-af", "ebur128"] if tem_audio(caminho) else []  # vídeo mudo: só a imagem é conferida
    r = rodar(["ffmpeg", "-hide_banner", "-nostats", "-i", str(caminho), "-vf", "freezedetect=n=-60dB:d=0.6",
               *som, "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
              errors="replace", timeout=180)
    log = r.stderr or ""
    inicios = re.findall(r"freeze_start: ([\d.]+)", log)
    duracoes = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    if len(inicios) > len(duracoes):  # congelado até o fim: o ffmpeg não fecha o trecho
        duracoes.append(info["duracao"] - float(inicios[-1]))
    if duracoes and max(duracoes) >= 0.6:
        avisos.append(f"Imagem parada por {max(duracoes):.1f}s em algum ponto. Confira se é intencional.")
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    if lufs and not LUFS_ALVO - 2.5 <= float(lufs[-1]) <= LUFS_ALVO + 2.5:
        avisos.append(f"Volume final em {float(lufs[-1]):.1f} LUFS (o padrão das redes é {LUFS_ALVO}).")
    return avisos


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
                   setas_ativas: bool = True, altura_legenda: float = 0.60, cta: str = "", minimo: float = 0.0,
                   total: float | None = None, estilo: str = "karaoke", trilha: Path | None = None,
                   volume_trilha: float = 0.2, cortes_sfx: list[float] | None = None) -> dict:
    """total: duração exata (modo áudio primeiro, o vídeo já tem o tempo da voz). Sem ele, a duração sai da
    voz com folga e o último quadro segura o que faltar (lado a lado)."""
    if not palavras:
        raise ValueError("A narração não tem tempos de palavras. Gere a voz ou envie o áudio de novo.")
    trabalho = saida.parent / (saida.stem + "-partes")
    trabalho.mkdir(parents=True, exist_ok=True)
    dur_voz = duracao_audio(audio)
    dur_video = probe(video)["duracao"]
    if total is None:
        total = round(max(dur_voz + 0.6, min(minimo, dur_video)), 2)
    extra = max(0.0, total - dur_video)
    eventos = eventos_legenda(palavras, trabalho / "legenda", total, estilo)
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
    # Áudio: a voz ocupa o vídeo inteiro (silêncio no respiro final); trilha e whoosh entram por baixo dela
    mistura = ["[voz]"]
    if trilha:
        filtros.append(f"[1:a]aresample=48000,apad,atrim=0:{total:.3f},asplit=2[voz][chave]")
        entradas += ["-stream_loop", "-1", "-i", str(trilha)]
        fim_trilha = max(0.0, total - 1.2)
        filtros.append(f"[{n}:a]aresample=48000,atrim=0:{total:.3f},volume={volume_trilha:.3f},"
                       f"afade=t=in:d=0.4,afade=t=out:st={fim_trilha:.3f}:d=1.2[mus]")
        # A trilha abaixa sozinha enquanto a voz fala e volta nas pausas
        filtros.append("[mus][chave]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[trilha]")
        mistura.append("[trilha]")
        n += 1
    else:
        filtros.append(f"[1:a]aresample=48000,apad,atrim=0:{total:.3f}[voz]")
    cortes_sfx = [t for t in cortes_sfx or [] if 0.3 <= t < total]
    if cortes_sfx:
        gerar_whoosh(trabalho / "whoosh.wav")
        entradas += ["-i", str(trabalho / "whoosh.wav")]
        saidas = "".join(f"[w{j}]" for j in range(len(cortes_sfx)))
        filtros.append(f"[{n}:a]aresample=48000," + (f"asplit={len(cortes_sfx)}{saidas}" if len(cortes_sfx) > 1 else "anull[w0]"))
        for j, t in enumerate(cortes_sfx):
            filtros.append(f"[w{j}]adelay=delays={int((t - 0.3) * 1000)}:all=1[d{j}]")  # o pico cai no corte
            mistura.append(f"[d{j}]")
        n += 1
    filtros.append("".join(mistura) + f"amix=inputs={len(mistura)}:normalize=0:duration=first,"
                   f"loudnorm=I={LUFS_ALVO}:TP=-1.5:LRA=11,aresample=48000[a]")
    grafo = ";".join(filtros)
    # -filter_complex_script foi removido no ffmpeg 8. Grafo curto vai direto na linha de comando;
    # longo (limite do Windows ~32 mil caracteres) vai por arquivo com a sintaxe nova "-/filter_complex".
    if len(grafo) < 20000:
        opcao_filtro = ["-filter_complex", grafo]
    else:
        roteiro = trabalho / "filtros.txt"
        roteiro.write_text(grafo, encoding="utf-8")
        opcao_filtro = ["-/filter_complex", str(roteiro)]
    ffmpeg(*entradas, *opcao_filtro, "-map", f"[{atual}]", "-map", "[a]",
           "-t", str(total), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(saida))
    info = probe(saida)
    return {"caminho": str(saida), "duracao": info["duracao"], "width": info.get("width"), "height": info.get("height")}
