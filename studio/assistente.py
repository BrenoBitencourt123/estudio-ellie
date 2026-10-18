"""
Assistente de prompt do Estúdio Ellie.

Monta o briefing (ideia + quadros do vídeo de referência + imagens escolhidas + regras do projeto) e
devolve a cena pronta. O provedor é trocável (.env, PROVEDOR_PROMPT):
  manual  (padrão) o estúdio monta o texto e a folha de quadros, você cola no ChatGPT e cola a resposta de volta
  openai  chama a API da OpenAI direto (precisa de OPENAI_API_KEY e OPENAI_MODELO no .env)
A IA só escreve a CENA. As partes fixas do prompt (identidade, regras de consistência) continuam vindo do gerar.py.
"""

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

URL_OPENAI = "https://api.openai.com/v1/chat/completions"
QUADROS_POR_VIDEO = 6

FORMATO_RESPOSTA = """Reply with ONLY a JSON object, no markdown, in this exact shape:
{
  "nome": "a short snake_case name for THIS video, e.g. v12_knit_set_mirror",
  "cena": "the scene text in English",
  "camera": "ONE camera direction in English (e.g. slow dolly in, static tripod shot, handheld selfie), or empty string when there is a motion video",
  "objeto": "object she holds, in English, or empty string",
  "mao": "right",
  "resumo_pt": "one sentence in Brazilian Portuguese saying what the video will show",
  "avisos": ["problems you notice in the references, in Brazilian Portuguese; empty list if none"]
}
The value of "mao" must be exactly "right", "left" or "" (empty when she holds no object).
The reply must be valid JSON: double quotes, commas between fields, nothing after the closing brace."""

REGRAS_COMUNS = """You write the scene text for an AI video generator that makes vertical TikTok videos.
The studio already attaches the reference images and adds the fixed parts of the prompt (identity, outfit, location,
motion-copy rules, physical consistency, "no text, no watermark"). Do NOT repeat those. You only write the field "cena".
Style: plain British English, present tense, simple words, one clear action. No semicolons, no dashes, no lists of
fragments, no poster phrases. Never describe her face. Keep it short.
Use positive phrasing (say what you want to see, never "no X" or "don't"). Avoid speed words (fast, rapid, quick):
slow continuous motion renders better. Do not repeat what the reference images already show.
In "avisos" check the reference frames for: text, logos or watermarks over the body; the head cut off or the body
touching the frame edge; which hand holds the phone or object (it must match the "mao" you return); a framing mismatch
between the reference video and the reference images; a reference video shorter than the video length."""

REGRAS_POR_MODO = {
    ("ellie", "seedance", False): """Mode: Ellie Hartley (a fictional London girl in her 20s), Seedance, NO motion video.
Write what she does and where the camera is (mirror selfie, POV, handheld). Up to 45 words.
If the shot is about the garment itself (hanger, POV picking it up), write the word PECA where the garment is mentioned;
otherwise never use the word PECA.""",
    ("ellie", "seedance", True): """Mode: Ellie Hartley (a fictional London girl in her 20s), Seedance, WITH a motion video.
The body movement and the camera motion are copied from the motion video, so do NOT describe the movement.
Describe only the context (place, light, mood) and small details like expression. Up to 30 words.
Use the motion frames to see which hand holds the phone or object and return it in "mao".
If the shot is about the garment itself, write the word PECA where the garment is mentioned; otherwise never use it.""",
    ("ellie", "kling", True): """Mode: Ellie Hartley, Kling Motion Control. The face, outfit and place come from a single base image
and the movement comes from the motion video. The scene text is optional and must be tiny (up to 20 words):
only a light or expression tweak. If nothing needs changing, return an empty "cena".""",
    ("lugar", "seedance", False): """Mode: PLACE edit, Seedance, from one photo of a real place (UK). No people unless the idea asks for them.
Write the camera movement (slow push-in, gentle pan, drift) and the atmosphere (weather, light, season, small life like
falling leaves, steam, birds). Up to 40 words.""",
    ("lugar", "seedance", True): """Mode: PLACE edit, Seedance, from one photo of a real place (UK) with a motion video that gives only the
CAMERA movement. Do not describe the camera movement. Describe only atmosphere (weather, light, season, small life).
Up to 30 words.""",
}


def instrucoes(tipo: str, motor: str, tem_movimento: bool) -> str:
    chave = (tipo, motor, tem_movimento)
    if chave not in REGRAS_POR_MODO:  # combinação não prevista: usa a regra do mesmo tipo e motor
        chave = next(k for k in REGRAS_POR_MODO if k[:2] == (tipo, motor))
    return f"{REGRAS_COMUNS}\n\n{REGRAS_POR_MODO[chave]}\n\n{FORMATO_RESPOSTA}"


def contexto(
    ideia: str, duracao: int, nomes_refs: list[str], movimento: str | None, inicio: float, orientacao: str | None,
    tem_peca: bool = True,
) -> str:
    linhas = [f"Idea from the creator (Portuguese): {ideia.strip() or '(none, propose something that fits the references)'}"]
    linhas.append(f"Video length: {duracao} seconds.")
    if nomes_refs:
        linhas.append("Reference images (see the first attached image sheet, left to right): " + ", ".join(nomes_refs) + ".")
    if movimento:
        linhas.append(
            f"Motion video: {movimento}, using the part from {inicio:.1f}s (the second attached sheet shows frames of it in order)."
        )
    if orientacao:
        linhas.append(f"Kling body orientation setting: follows the {orientacao}.")
    if not tem_peca:
        linhas.append("There is NO garment reference image: never write the word PECA; describe the outfit in plain words if needed.")
    return "\n".join(linhas)


def frames_do_video(video: Path, inicio: float, duracao: float, quantidade: int = QUADROS_POR_VIDEO) -> list[Path]:
    """Extrai quadros espaçados do trecho do vídeo (FFmpeg, grátis)."""
    pasta = Path(tempfile.mkdtemp(prefix="estudio_quadros_"))
    comando = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(inicio), "-i", str(video), "-t", str(max(duracao, 1)),
        "-vf", f"fps={quantidade / max(duracao, 1):.4f},scale=360:-2",
        "-frames:v", str(quantidade), str(pasta / "q_%02d.jpg"),
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao extrair os quadros: {resultado.stderr.strip()[:300]}")
    return sorted(pasta.glob("q_*.jpg"))


def regras_cena_texto() -> str:
    """Todas as regras de cena num texto só (para quem escreve a cena direto, como um agente via MCP)."""
    nomes = {
        ("ellie", "seedance", False): "Ellie · Seedance · sem vídeo de movimento",
        ("ellie", "seedance", True): "Ellie · Seedance · com vídeo de movimento",
        ("ellie", "kling", True): "Ellie · Kling Motion Control",
        ("lugar", "seedance", False): "Lugar · Seedance · sem vídeo de movimento",
        ("lugar", "seedance", True): "Lugar · Seedance · com vídeo de câmera",
    }
    blocos = [REGRAS_COMUNS]
    for chave, regra in REGRAS_POR_MODO.items():
        blocos.append(f"### {nomes[chave]}\n{regra}")
    return "\n\n".join(blocos)


def montar_folha(
    imagens: list[Path], destino: Path, colunas: int = 3, celula: int = 300, numerar: bool = False
) -> Path:
    """Junta várias imagens numa folha só (uma imagem enviada à IA custa menos que várias).
    Com numerar=True cada célula ganha um número (1, 2, 3...) para a IA citar a imagem certa."""
    altura = int(celula * 1.8)
    linhas = (len(imagens) + colunas - 1) // colunas
    folha = Image.new("RGB", (colunas * celula, linhas * altura), (235, 235, 235))
    desenho = ImageDraw.Draw(folha)
    fonte = ImageFont.load_default(size=26)
    for i, caminho in enumerate(imagens):
        with Image.open(caminho) as original:
            miniatura = original.convert("RGB")
            miniatura.thumbnail((celula - 6, altura - 6))
            x = (i % colunas) * celula + (celula - miniatura.width) // 2
            y = (i // colunas) * altura + (altura - miniatura.height) // 2
            folha.paste(miniatura, (x, y))
        if numerar:
            cx, cy = (i % colunas) * celula + 6, (i // colunas) * altura + 6
            desenho.rectangle((cx, cy, cx + 44, cy + 36), fill=(225, 29, 72))
            desenho.text((cx + 22, cy + 18), str(i + 1), fill=(255, 255, 255), font=fonte, anchor="mm")
    destino.parent.mkdir(parents=True, exist_ok=True)
    folha.save(destino, "JPEG", quality=82)
    return destino


def consertar_json(texto: str) -> str:
    """Conserta os erros mais comuns quando a IA copia o modelo de resposta ao pé da letra."""
    # "mao": "right" or "left" or "" (comentário)  →  "mao": "right"
    texto = re.sub(r'("(?:[^"\\]|\\.)*")[ \t]+or[ \t]+[^,\n}]*', r"\1", texto)
    # comentário entre parênteses depois de um valor: "x" (bla)  →  "x"
    texto = re.sub(r'("(?:[^"\\]|\\.)*")[ \t]*\([^)\n]*\)', r"\1", texto)
    # aspas tipográficas e vírgula sobrando antes de fechar
    texto = texto.replace("“", '"').replace("”", '"')
    return re.sub(r",\s*([}\]])", r"\1", texto)


# Nomes de exemplo do modelo de resposta que a IA às vezes copia ao pé da letra
NOMES_DE_EXEMPLO = {"short_snake_case_file_name", "snake_case_name", "snake_case_video_name", "file_name"}


def nome_valido(texto: str) -> str:
    nome = re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")[:40]
    return "" if nome in NOMES_DE_EXEMPLO or nome.startswith("a_short_snake_case") else nome


def extrair_json(texto: str) -> dict:
    """Pega o PRIMEIRO objeto JSON completo da resposta, ignorando texto antes e depois (ex.: comentários da IA)."""
    decodificador = json.JSONDecoder()
    for candidato in (texto, consertar_json(texto)):
        for inicio in [i for i, c in enumerate(candidato) if c == "{"][:20]:
            try:
                dados, _ = decodificador.raw_decode(candidato, inicio)
            except json.JSONDecodeError:
                continue
            if isinstance(dados, dict):
                return dados
    raise ValueError("Não encontrei um JSON válido na resposta da IA.")


def interpretar_resposta(texto: str) -> dict:
    """Aceita a resposta da IA mesmo com texto em volta (ex.: bloco de código markdown)."""
    try:
        dados = extrair_json(texto)
    except ValueError:
        raise ValueError("Não encontrei um JSON válido na resposta. Cole a resposta inteira da IA.")
    mao =str(dados.get("mao", "")).strip().lower()
    objeto = str(dados.get("objeto", "")).strip()
    avisos = dados.get("avisos") or []
    return {
        "nome": nome_valido(str(dados.get("nome", ""))),
        "cena": str(dados.get("cena", "")).replace(";", ",").strip(),
        "camera": str(dados.get("camera", "")).replace(";", ",").strip()[:120],
        "objeto": objeto,
        "mao": mao if (mao in ("right", "left") and objeto) else "",
        "resumo_pt": str(dados.get("resumo_pt", "")).strip(),
        "avisos": [str(a) for a in avisos] if isinstance(avisos, list) else [str(avisos)],
    }


def chamar_openai(chave: str, modelo: str, sistema: str, texto: str, folhas: list[Path]) -> dict:
    conteudo: list[dict] = [{"type": "text", "text": texto}]
    for folha in folhas:
        dados = base64.b64encode(folha.read_bytes()).decode()
        conteudo.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{dados}"}})
    resposta = requests.post(
        URL_OPENAI,
        headers={"Authorization": f"Bearer {chave}"},
        json={
            "model": modelo,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": conteudo}],
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    if resposta.status_code != 200:
        raise RuntimeError(f"A OpenAI recusou o pedido ({resposta.status_code}): {resposta.text[:300]}")
    return interpretar_resposta(resposta.json()["choices"][0]["message"]["content"])
