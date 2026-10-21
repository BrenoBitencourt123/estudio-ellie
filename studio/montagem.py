"""Montagem local: nunca pede outra geração para alterar cortes ou tipografia."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.processos import rodar


def ffmpeg(*args: str) -> None:
    process = rodar(["ffmpeg", "-hide_banner", "-loglevel", "error", *map(str, args)],
                    capture_output=True, text=True, encoding="utf-8", timeout=180)
    if process.returncode:
        raise ValueError("A edição não concluiu: " + process.stderr[-1200:])


def probe(path: Path) -> dict:
    result = rodar(["ffprobe", "-v", "error", "-show_entries",
                    "stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration,size", "-of", "json", str(path)],
                   capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise ValueError("Arquivo de vídeo inválido ou incompleto: " + path.name)
    data = json.loads(result.stdout)
    stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not stream or float(data["format"].get("duration", 0)) <= 0:
        raise ValueError("O arquivo não contém vídeo utilizável.")
    return {**stream, "duracao": float(data["format"]["duration"]), "bytes": int(data["format"]["size"])}


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def preparar_referencia(source: Path, dest: Path, start: float, duration: float) -> dict:
    data = probe(source)
    if duration < 2 or start + duration > data["duracao"] + .03:
        raise ValueError("O trecho de movimento precisa ter pelo menos 2 s e caber no vídeo original.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Pad preserva a geometria; os recortes estreitos 9:32 do V7 foram recusados pelo serviço.
    ffmpeg("-ss", str(start), "-i", str(source), "-t", str(duration), "-vf",
           "scale=576:1024:force_original_aspect_ratio=decrease,pad=576:1024:(ow-iw)/2:(oh-ih)/2:color=0xe8e3da,setsar=1,fps=30",
           "-an", "-c:v", "libx264", "-crf", "19", "-y", str(dest))
    return probe(dest)


def fonte(size: int, italic: bool = False):
    candidates = (["C:/Windows/Fonts/BOD_I.TTF", "C:/Windows/Fonts/georgiai.ttf"] if italic else
                  ["C:/Windows/Fonts/BOD_R.TTF", "C:/Windows/Fonts/georgia.ttf"])
    candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf" if italic else
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def tem_faixa(config: dict) -> bool:
    return int(config.get("altura", 0) or 0) > 0 and any(
        str(config.get(k, "")).strip() for k in ("sobretitulo", "titulo", "destaque", "pergunta", "esquerda", "direita"))


def overlay(config: dict, dest: Path, divisoria: bool = True) -> None:
    """Faixa de texto no topo (720x1280). Só desenha os campos preenchidos; divisoria = linha do lado a lado."""
    scale = 3
    img = Image.new("RGBA", (720 * scale, 1280 * scale))
    draw = ImageDraw.Draw(img)
    h = int(config.get("altura", 350)) * scale
    paper, ink, yellow = "#F6F0E6", "#3A241D", "#DAD47A"
    draw.rectangle((0, 0, 720 * scale, h), fill=paper)

    def centered(text: str, y: int, size: int, italic: bool = False, highlight: bool = False):
        f = fonte(size * scale, italic)
        while draw.textlength(text, font=f) > 640 * scale and size > 14:
            size -= 1
            f = fonte(size * scale, italic)
        width = draw.textlength(text, font=f)
        x = (720 * scale - width) / 2
        if highlight:
            draw.rectangle((x - 5 * scale, (y + size * .72) * scale,
                            x + width + 5 * scale, (y + size * 1.02) * scale), fill=yellow)
        draw.text((x, y * scale), text, font=f, fill=ink, anchor="lt")

    def campo(k: str) -> str:
        return str(config.get(k, "") or "").strip()

    if h > 0:
        if h >= 300 * scale:
            if campo("sobretitulo"):
                centered(campo("sobretitulo"), 18, 18)
            if campo("titulo"):
                centered(campo("titulo"), 66, 64)
            if campo("destaque"):
                centered(campo("destaque"), 151, 72, True, True)
            if campo("pergunta"):
                centered(campo("pergunta"), 242, 24)
            label_y = int(config.get("altura", 350)) - 35
        else:
            linha = " ".join(v for v in (campo("titulo"), campo("destaque")) if v)
            if linha:
                centered(linha, 20, 42)
            if campo("pergunta"):
                centered(campo("pergunta"), 80, 20)
            label_y = max(110, int(config.get("altura", 132)) - 25)
        rotulos = [(campo("esquerda"), 180), (campo("direita"), 540)]
        if any(t for t, _ in rotulos):
            draw.line((40 * scale, (label_y - 18) * scale, 680 * scale, (label_y - 18) * scale), fill="#CFC5B5", width=scale)
        for text, x in rotulos:
            if not text:
                continue
            f = fonte(20 * scale)
            while draw.textlength(text, font=f) > 300 * scale:
                f = fonte(max(12 * scale, f.size - scale))
                if f.size <= 12 * scale:
                    break
            draw.text((x * scale, label_y * scale), text, font=f, fill=ink, anchor="mt")
    if divisoria:
        draw.line((360 * scale, h, 360 * scale, 1280 * scale), fill="#F6F0E680", width=scale)
    img.resize((720, 1280), Image.Resampling.LANCZOS).save(dest)


def filtro_painel(info: dict, crop: list[int] | None) -> str:
    if crop:
        w, h, x, y = crop
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > info["width"] or y + h > info["height"]:
            raise ValueError("O recorte ultrapassa os limites da tomada.")
        return f"crop={w}:{h}:{x}:{y},scale=360:1280,setsar=1"
    # Recorte central sem deformar. Pode ser ajustado por tomada pelo editor.
    return "scale=360:1280:force_original_aspect_ratio=increase,crop=360:1280,setsar=1"


def montar(production: dict, resolve_asset, output: Path) -> dict:
    shots = {s["id"]: s for s in production["tomadas"]}
    cuts = production["cortes"]
    frames = round(production["duracao_final"] * 30)
    if sum(round(c["duracao"] * 30) for c in cuts) != frames:
        raise ValueError("Os cortes da esquerda precisam preencher exatamente a duração final.")
    summer = next((s for s in shots.values() if s["lado"] == "direita"), None)
    if not summer or not summer.get("arquivo"):
        raise ValueError("Falta a tomada contínua da direita.")
    source_right = resolve_asset(summer["arquivo"])
    right_info = probe(source_right)
    if right_info["duracao"] + .03 < production["duracao_final"]:
        raise ValueError("A tomada da direita é mais curta que a duração final.")
    output.mkdir(parents=True, exist_ok=True)
    version = f"edicao-{production['versao']}"
    work = output / version
    work.mkdir(exist_ok=False)
    names = []
    for i, cut in enumerate(cuts):
        shot = shots.get(cut["tomada"])
        if not shot or shot["lado"] != "esquerda" or not shot.get("arquivo"):
            raise ValueError("Um corte não tem tomada pronta para a metade esquerda.")
        source = resolve_asset(shot["arquivo"])
        info = probe(source)
        if cut["inicio"] + cut["duracao"] > info["duracao"] + .03:
            raise ValueError("O corte ultrapassa a duração real da tomada " + shot["titulo"])
        name = f"parte-{i:02}.mp4"
        ffmpeg("-ss", str(cut["inicio"]), "-i", str(source), "-vf", "fps=30," + filtro_painel(info, cut.get("recorte") or shot.get("recorte")),
               "-frames:v", str(round(cut["duracao"] * 30)), "-an", "-c:v", "libx264", "-crf", "18", "-y", str(work / name))
        names.append(f"file '{name}'")
    (work / "partes.txt").write_text("\n".join(names), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "partes.txt"), "-c", "copy", "-an", "-y", str(work / "esquerda.mp4"))
    overlay(production.get("faixa") or {}, work / "faixa.png")
    filters = ("[1:v]fps=30,trim=end_frame=" + str(frames) + ",setpts=PTS-STARTPTS," +
               filtro_painel(right_info, summer.get("recorte")) + "[right];"
               "[0:v]setpts=PTS-STARTPTS[left];[left][right]hstack=inputs=2[base];"
               "[base][2:v]overlay=0:0:format=auto,format=yuv420p[out]")
    final = output / f"{version}.mp4"
    ffmpeg("-i", str(work / "esquerda.mp4"), "-i", str(source_right), "-i", str(work / "faixa.png"),
           "-filter_complex", filters, "-map", "[out]", "-frames:v", str(frames), "-an", "-c:v", "libx264",
           "-crf", "18", "-movflags", "+faststart", "-y", str(final))
    data = probe(final)
    if data["width"] != 720 or data["height"] != 1280 or abs(data["duracao"] - production["duracao_final"]) > .04:
        raise ValueError("A montagem não corresponde à duração ou resolução escolhida.")
    return {"caminho": str(final), "sha256": sha256(final), **data}


LC, AC = 1080, 1920  # tela cheia

# Movimento de câmera sobre uma imagem parada (grátis, sem Dreamina).
MOVIMENTOS_LOCAIS = ("aproximar", "afastar", "subir", "descer", "esquerda", "direita")


def animar_imagem(imagem: Path, destino: Path, duracao: float, movimento: str = "aproximar",
                  largura: int = LC, altura: int = AC) -> dict:
    """Uma imagem vira cena de vídeo com movimento lento de câmera. A imagem é ampliada 3x antes do
    zoompan, que só anda em pixels inteiros: assim o movimento não treme.

    Velocidade constante (E vai de 0 a 1 em linha reta): o corte pega a câmera em movimento, sem o
    começo e o fim quase parados de uma curva suave."""
    if movimento not in MOVIMENTOS_LOCAIS:
        raise ValueError("Movimento de câmera desconhecido: " + movimento)
    n = max(1, round(duracao * 30))
    e = f"(on/{max(1, n - 1)})"
    centro_x, centro_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    z, x, y = {
        "aproximar": (f"1+0.10*{e}", centro_x, centro_y),
        "afastar": (f"1.10-0.10*{e}", centro_x, centro_y),
        "subir": ("1.12", centro_x, f"(ih-ih/zoom)*(1-{e})"),
        "descer": ("1.12", centro_x, f"(ih-ih/zoom)*{e}"),
        "esquerda": ("1.12", f"(iw-iw/zoom)*(1-{e})", centro_y),
        "direita": ("1.12", f"(iw-iw/zoom)*{e}", centro_y),
    }[movimento]
    w, h = largura * 3, altura * 3
    destino.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(imagem), "-vf",
           f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
           f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={largura}x{altura}:fps=30,format=yuv420p",
           "-frames:v", str(n), "-an", "-c:v", "libx264", "-crf", "18", "-y", str(destino))
    return probe(destino)


def filtro_cheio(info: dict, crop: list[int] | None, largura: int = LC, altura: int = AC) -> str:
    if crop:
        w, h, x, y = crop
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > info["width"] or y + h > info["height"]:
            raise ValueError("O recorte ultrapassa os limites da tomada.")
        return f"crop={w}:{h}:{x}:{y},scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1"
    return f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1"


def tem_audio(path: Path) -> bool:
    result = rodar(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                    str(path)], capture_output=True, text=True, timeout=25)
    return bool(result.stdout.strip())


def montar_sequencia(production: dict, resolve_asset, output: Path, audio_original: bool = False) -> dict:
    """Tela cheia 9:16: os cortes em sequência (1 ou várias cenas), faixa de texto opcional.

    Sem `audio_original` sai mudo (a narração entra depois, ou o vídeo é silencioso de propósito). Com ele, o
    som de cada tomada acompanha o corte; tomada sem faixa entra em silêncio e é listada em `sem_audio`."""
    shots = {s["id"]: s for s in production["tomadas"]}
    sem_audio: list[str] = []
    cuts = production["cortes"]
    frames = round(production["duracao_final"] * 30)
    if sum(round(c["duracao"] * 30) for c in cuts) != frames:
        raise ValueError("Os cortes precisam preencher exatamente a duração final.")
    output.mkdir(parents=True, exist_ok=True)
    version = f"edicao-{production['versao']}"
    work = output / version
    work.mkdir(exist_ok=True)
    names = []
    for i, cut in enumerate(cuts):
        shot = shots.get(cut["tomada"])
        if not shot or not shot.get("arquivo"):
            raise ValueError("Um corte não tem tomada pronta.")
        source = resolve_asset(shot["arquivo"])
        info = probe(source)
        # velocidade < 1: câmera lenta para a tomada cobrir a frase inteira da narração
        velocidade = float(cut.get("velocidade") or 1)
        if cut["inicio"] + cut["duracao"] * velocidade > info["duracao"] + .03:
            raise ValueError("O corte ultrapassa a duração real da tomada " + shot["titulo"])
        name = f"parte-{i:02}.mp4"
        n = round(cut["duracao"] * 30)
        lento = f"setpts=(PTS-STARTPTS)/{velocidade:.4f}," if abs(velocidade - 1) > .001 else ""
        video = lento + "fps=30," + filtro_cheio(info, cut.get("recorte") or shot.get("recorte")) + ",tpad=stop_mode=clone:stop_duration=0.2"
        if audio_original:
            # O som segue o corte: mesmo trecho, mesma velocidade, duração exata da parte
            som = tem_audio(source)
            entradas = ["-ss", str(cut["inicio"]), "-i", str(source)]
            if not som:
                entradas += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                if shot["titulo"] not in sem_audio:
                    sem_audio.append(shot["titulo"])
            tempo = f"atempo={velocidade:.4f}," if abs(velocidade - 1) > .001 and som else ""
            ffmpeg(*entradas, "-map", "0:v", "-map", "0:a" if som else "1:a", "-vf", video,
                   "-af", tempo + f"aresample=48000,apad,atrim=0:{n / 30:.4f}", "-frames:v", str(n),
                   "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                   "-b:a", "192k", "-y", str(work / name))
        else:
            # tpad garante os quadros finais mesmo se o arquivo terminar um pouco antes
            ffmpeg("-ss", str(cut["inicio"]), "-i", str(source), "-vf", video,
                   "-frames:v", str(n), "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-y", str(work / name))
        names.append(f"file '{name}'")
    (work / "partes.txt").write_text("\n".join(names), encoding="utf-8")
    final = output / f"{version}.mp4"
    faixa = production.get("faixa") or {}
    # Som original sai no volume padrão das redes; sem ele, o arquivo é mudo
    audio = (["-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"]
             if audio_original else ["-an"])
    if tem_faixa(faixa):
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "partes.txt"), "-c", "copy", "-y", str(work / "sequencia.mp4"))
        overlay(faixa, work / "faixa.png", divisoria=False)
        ffmpeg("-i", str(work / "sequencia.mp4"), "-i", str(work / "faixa.png"), "-filter_complex",
               f"[1:v]scale={LC}:{AC}[f];[0:v][f]overlay=0:0:format=auto,format=yuv420p[out]", "-map", "[out]",
               *(["-map", "0:a"] if audio_original else []), "-frames:v", str(frames), *audio,
               "-c:v", "libx264", "-crf", "18", "-movflags", "+faststart", "-y", str(final))
    else:
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "partes.txt"), "-frames:v", str(frames), *audio,
               "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(final))
    data = probe(final)
    if abs(data["duracao"] - production["duracao_final"]) > .1:
        raise ValueError("A montagem não corresponde à duração escolhida.")
    return {"caminho": str(final), "sha256": sha256(final), **data, "sem_audio": sem_audio}


# ---------------- Prévia: o storyboard com os tempos, antes de gastar ----------------
LP, AP = 540, 960  # um quarto dos pixels da tela cheia: monta em segundos
CRF_PREVIA = "26"


def _quebrar(draw, texto: str, f, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if atual and draw.textlength(tentativa, font=f) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    return linhas + ([atual] if atual else [])


def cartao_previa(titulo: str, destino: Path) -> None:
    """Cena ainda sem quadro: cartão cinza com o título, para o tempo dela aparecer na prévia."""
    img = Image.new("RGB", (LP, AP), "#9a978e")
    draw = ImageDraw.Draw(img)
    f, menor = fonte(34), fonte(20, italic=True)
    linhas = _quebrar(draw, titulo, f, LP - 80)[:5]
    y = AP / 2 - len(linhas) * 23 - 20
    for linha in linhas:
        draw.text((LP / 2, y), linha, font=f, fill="#fbf8f0", anchor="mt")
        y += 46
    draw.text((LP / 2, y + 18), "ainda sem quadro", font=menor, fill="#ece7dc", anchor="mt")
    img.save(destino)


def selo_previa(destino: Path, texto: str = "vídeo será gerado aqui") -> None:
    """Selo discreto sobre o quadro de uma tomada paga que ainda não existe."""
    img = Image.new("RGBA", (LP, AP), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    f = fonte(19, italic=True)
    largura = draw.textlength(texto, font=f)
    x, y = (LP - largura) / 2, AP * 0.78
    draw.rounded_rectangle((x - 14, y - 9, x + largura + 14, y + 31), radius=20, fill=(30, 28, 24, 150))
    draw.text((x, y), texto, font=f, fill=(255, 255, 255, 235))
    img.save(destino)


def montar_previa(partes: list[dict], trabalho: Path, destino: Path, faixa: dict | None = None) -> dict:
    """Vídeo-rascunho mudo, 540x960, uma parte por corte na ordem do plano.

    Cada parte: {"duracao", "titulo"} e uma destas fontes:
      "video" (Path, + "inicio", "velocidade", "recorte"): a tomada já baixada, no trecho do corte;
      "imagem" (Path, + "movimento", "selo"): o quadro com o movimento local (selo = tomada paga ainda por gerar);
      nenhuma: cartão cinza com o título."""
    if not partes:
        raise ValueError("Não há cenas para a prévia.")
    trabalho.mkdir(parents=True, exist_ok=True)
    codec = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF_PREVIA, "-pix_fmt", "yuv420p"]
    nomes, quadros = [], 0
    for i, parte in enumerate(partes):
        n = max(1, round(float(parte["duracao"]) * 30))
        quadros += n
        nome = trabalho / f"parte-{i:02}.mp4"
        if parte.get("video"):
            info = probe(parte["video"])
            velocidade = float(parte.get("velocidade") or 1)
            lento = f"setpts=(PTS-STARTPTS)/{velocidade:.4f}," if abs(velocidade - 1) > .001 else ""
            # tpad: se o trecho acabar antes do corte, o último quadro segura o tempo (a prévia mostra o tempo, não julga)
            ffmpeg("-ss", str(parte.get("inicio") or 0), "-i", str(parte["video"]), "-vf",
                   lento + "fps=30," + filtro_cheio(info, parte.get("recorte"), LP, AP) + ",tpad=stop_mode=clone:stop_duration=30",
                   "-frames:v", str(n), *codec, "-y", str(nome))
        elif parte.get("imagem"):
            if parte.get("selo"):
                bruto = trabalho / f"parte-{i:02}-quadro.mp4"
                animar_imagem(parte["imagem"], bruto, n / 30, parte.get("movimento") or "aproximar", LP, AP)
                selo_previa(trabalho / "selo.png")
                ffmpeg("-i", str(bruto), "-i", str(trabalho / "selo.png"), "-filter_complex",
                       "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]", "-map", "[v]",
                       "-frames:v", str(n), *codec, "-y", str(nome))
            else:
                animar_imagem(parte["imagem"], nome, n / 30, parte.get("movimento") or "aproximar", LP, AP)
        else:
            cartao = trabalho / f"parte-{i:02}.png"
            cartao_previa(str(parte.get("titulo") or "Cena"), cartao)
            ffmpeg("-loop", "1", "-i", str(cartao), "-vf", "fps=30,setsar=1,format=yuv420p",
                   "-frames:v", str(n), *codec, "-y", str(nome))
        nomes.append(f"file '{nome.name}'")
    (trabalho / "partes.txt").write_text("\n".join(nomes), encoding="utf-8")
    entradas, filtro = ["-f", "concat", "-safe", "0", "-i", str(trabalho / "partes.txt")], ["-vf", "fps=30,format=yuv420p"]
    if faixa and tem_faixa(faixa):
        overlay(faixa, trabalho / "faixa.png", divisoria=False)
        entradas += ["-i", str(trabalho / "faixa.png")]
        filtro = ["-filter_complex", f"[1:v]scale={LP}:{AP}[f];[0:v]fps=30[b];[b][f]overlay=0:0:format=auto,format=yuv420p[v]",
                  "-map", "[v]"]
    # Sempre recodifica: as partes vêm de fontes diferentes, e o total sai no quadro exato
    ffmpeg(*entradas, *filtro, "-frames:v", str(quadros), *codec, "-movflags", "+faststart", "-y", str(destino))
    return probe(destino)


def reduzir_previa(origem: Path, destino: Path) -> dict:
    """A narração sai em 1080x1920 (legenda desenhada para a tela cheia): a prévia volta para 540x960."""
    ffmpeg("-i", str(origem), "-vf", f"scale={LP}:{AP},setsar=1", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", CRF_PREVIA, "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", "-y", str(destino))
    return probe(destino)
