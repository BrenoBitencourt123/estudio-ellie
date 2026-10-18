"""
Planejador do Estúdio Ellie: a IA estuda o vídeo de referência e a biblioteca e devolve um plano completo
(motor, mídias a usar, mídias a criar com prompt de imagem, cena, riscos). Aqui ficam o pedido para a IA e a
checagem do que ela devolve (nomes de arquivo inventados, modelos inválidos etc. são corrigidos ou viram aviso).
"""

import re

MODELOS_SEEDANCE = ("2.0-mini", "2.0-fast", "2.0", "2.5")
MODELOS_KLING = ("kling-2.6-std", "kling-2.6-pro", "kling-3.0-std", "kling-3.0-pro")
PASTAS_CRIAVEIS = ("pecas", "cenarios", "base", "persona")
PILARES = ("outfit_clima", "pov_london", "lugar")
MAX_CRIAR = 2

FORMATO = """Reply with ONLY valid JSON (no markdown) in this shape:
{
  "analise": {
    "resumo_pt": "2 sentences in Brazilian Portuguese: what happens in the reference video",
    "movimento_en": "the body movement in plain English",
    "enquadramento": "corpo inteiro | meio corpo | do queixo para baixo | close",
    "cabeca_visivel": true,
    "tronco_inteiro": true,
    "texto_sobre_corpo": false,
    "mao_celular": "right",
    "melhor_inicio_s": 0,
    "melhor_duracao_s": 8
  },
  "motor": "seedance",
  "modelo": "2.0-fast",
  "porque_pt": "why this engine and model, in Brazilian Portuguese",
  "usar": {"persona": ["file names"], "peca": "file name or empty", "cenario": "file name or empty", "imagem_base": "file name or empty"},
  "criar": [
    {"pasta": "pecas", "nome": "snake_case_name", "prompt": "English image prompt", "usar_fotos_ellie": false, "do_video": false, "porque_pt": "why"}
  ],
  "video": {
    "nome": "snake_case_video_name", "pilar": "outfit_clima", "duracao": 8, "movimento_inicio": 0,
    "cena": "scene text in English", "camera": "", "objeto": "", "mao": "", "orientacao": "video"
  },
  "passos_pt": ["short steps for the creator, in Brazilian Portuguese"],
  "riscos_pt": ["risks to check in the result, in Brazilian Portuguese"]
}
Allowed values: "motor" is "seedance" or "kling". "modelo" is one of """ + ", ".join(MODELOS_SEEDANCE + MODELOS_KLING) + """.
"mao_celular" and "video.mao" are "right", "left" or "". "pilar" is one of """ + ", ".join(PILARES) + """.
"criar[].pasta" is pecas, cenarios, base or persona. Use only file names that appear in the library lists."""

REGRAS = """You are the production planner of the TikTok profile of Ellie Hartley (AI-generated London girl, UK).
Goal: the best possible short video for the lowest cost. Read the profile guide and the scene rules below.
How to plan:
1. Study the reference video frames (if any): movement, framing, whether head and full torso are visible, text or
   watermarks over the body, which hand holds the phone, and the best continuous part (7 to 9 seconds is ideal).
2. Choose the engine:
   - Kling ("kling-2.6-std") only when the reference video shows head AND full torso the whole time, has no text over
     the body and was never rejected by Kling. It needs ONE base image (pasta "base") of Ellie already wearing the
     outfit in the place, with the SAME framing as the video. The output keeps the framing of the base image.
   - Otherwise Seedance ("2.0-fast", 720p): 1 to 2 Ellie face photos (persona) + optional garment (pecas) + optional
     place (cenarios) + the motion video. Seedance accepts reference videos without a head.
   - Follow the self-study recommendations when they name a cheaper model that works.
3. Reuse library files whenever they fit (it is free and faster). Create new images only when something is missing or
   clearly wrong for this video, at most """ + str(MAX_CRIAR) + """ images. Image prompts: English, vertical 9:16,
   photorealistic smartphone photo, natural light. Garments: the garment alone on a hanger or flat lay, plain background,
   no person, no text. Places: the empty place, no people, no text. Base image (Kling): set "usar_fotos_ellie": true;
   describe Ellie wearing the outfit in the place with the same framing as the reference video (if the creator wants no
   face, framed from the chin down).
   When the creator wants the SAME outfit (or place) as the reference video, or no library garment matches it, create it
   FROM THE VIDEO: add a "criar" item with "do_video": true (pasta "pecas" for the outfit, "cenarios" for the place,
   "base" for Kling); the frames of the video are sent as references, so the prompt only needs extra details.
4. Write the scene following the scene rules for the chosen mode (with a motion video, do not describe the movement).
   Use "PECA" only when a garment file is used AND the shot is about the garment itself.
5. List what the creator must check in the result."""


def instrucoes(perfil: str, regras_cena: str) -> str:
    return f"{REGRAS}\n\n# Profile guide\n{perfil}\n\n# Scene rules\n{regras_cena}\n\n{FORMATO}"


def contexto(
    ideia: str, movimento: str | None, duracao_video: float | None, inicio: float,
    folhas_biblioteca: list[tuple[str, list[str]]], biblioteca: dict[str, list[str]],
    recomendacoes: list[str], rejeitados_kling: list[str],
) -> str:
    linhas = [f"Creator's idea (Portuguese): {ideia.strip() or '(none: propose the best video for the profile right now)'}"]
    n = 1
    if movimento:
        linhas.append(
            f"Attached sheet {n}: 12 numbered frames, in order, of the reference video {movimento} "
            f"(total {duracao_video:.1f}s, frames from {inicio:.1f}s)."
        )
        n += 1
    else:
        linhas.append("No reference video: plan a Seedance video from photos (motion comes from the scene text and camera).")
    for pasta, nomes in folhas_biblioteca:
        linhas.append(f"Attached sheet {n}: library folder '{pasta}', numbered: " + "; ".join(f"{i + 1}. {x}" for i, x in enumerate(nomes)))
        n += 1
    for pasta, nomes in biblioteca.items():
        if pasta != "movimentos" and len(nomes) > 12:
            linhas.append(f"Other files in '{pasta}' (not shown): {', '.join(nomes[12:40])}")
    if rejeitados_kling:
        linhas.append(f"Kling already rejected these reference videos: {', '.join(rejeitados_kling)}.")
    if recomendacoes:
        linhas.append("Self-study recommendations: " + " | ".join(recomendacoes))
    return "\n".join(linhas)


def _slug(texto: str, padrao: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(texto).lower()).strip("_")[:40]
    return padrao if (not s or s in ("snake_case_name", "snake_case_video_name", "short_snake_case_file_name")) else s


def _num(valor, padrao: float, minimo: float, maximo: float) -> float:
    try:
        return max(minimo, min(maximo, float(valor)))
    except (TypeError, ValueError):
        return padrao


def normalizar(dados: dict, biblioteca: dict[str, list[str]], movimento: str | None,
               duracao_video: float | None, rejeitados_kling: list[str], sem_rosto: bool = False) -> dict:
    """Confere o plano da IA contra a biblioteca real e as regras; o que não bate vira aviso em riscos_pt."""
    avisos: list[str] = []
    analise = dados.get("analise") or {}
    usar = dados.get("usar") or {}
    video = dados.get("video") or {}

    motor = "kling" if str(dados.get("motor")) == "kling" else "seedance"
    if motor == "kling" and (not movimento or movimento in rejeitados_kling):
        avisos.append("O plano pedia Kling, mas esse vídeo não serve para ele: troquei para o Seedance.")
        motor = "seedance"
    modelo = str(dados.get("modelo") or "")
    validos = MODELOS_KLING if motor == "kling" else MODELOS_SEEDANCE
    if modelo not in validos:
        modelo = "kling-2.6-std" if motor == "kling" else "2.0-fast"

    def existente(pasta: str, nome) -> str:
        nome = str(nome or "").strip()
        if nome and nome not in biblioteca.get(pasta, []):
            avisos.append(f"A IA citou '{nome}' em {pasta}, mas esse arquivo não existe. Ignorei.")
            return ""
        return nome

    persona = [p for p in (usar.get("persona") or []) if p in biblioteca.get("persona", [])][:4]
    if motor == "seedance" and not persona:
        persona = biblioteca.get("persona", [])[:2]
    if sem_rosto and motor == "seedance" and not persona:
        avisos.append("Vídeo sem rosto, mas não há foto da Ellie sem rosto na biblioteca: vai só com a roupa e o "
                      "movimento. Para manter cabelo e corpo, crie uma versão sem rosto na Biblioteca.")
    usar_ok = {
        "persona": persona,
        "peca": existente("pecas", usar.get("peca")),
        "cenario": existente("cenarios", usar.get("cenario")),
        "imagem_base": existente("base", usar.get("imagem_base")) if motor == "kling" else "",
    }

    criar = []
    for item in (dados.get("criar") or [])[:MAX_CRIAR]:
        pasta = str(item.get("pasta", ""))
        prompt = str(item.get("prompt", "")).strip()
        if pasta not in PASTAS_CRIAVEIS or len(prompt) < 10:
            continue
        if pasta == "base" and motor != "kling":
            continue
        criar.append({
            "pasta": pasta, "nome": _slug(item.get("nome"), f"nova_{pasta}"), "prompt": prompt[:1200],
            "usar_fotos_ellie": bool(item.get("usar_fotos_ellie")) or pasta in ("base", "persona"),
            "do_video": bool(item.get("do_video")) and bool(movimento) and pasta in ("pecas", "cenarios", "base"),
            "porque_pt": str(item.get("porque_pt", ""))[:300], "arquivo": "",
        })

    duracao_max = duracao_video or 15
    inicio = _num(video.get("movimento_inicio", analise.get("melhor_inicio_s", 0)), 0, 0, max(0, duracao_max - 2))
    duracao = int(round(_num(video.get("duracao", analise.get("melhor_duracao_s", 8)), 8, 4, 15)))
    if movimento and duracao_video and inicio + duracao > duracao_video + 0.5:
        duracao = max(4, int(duracao_video - inicio))
    pilar = str(video.get("pilar", ""))
    mao = str(video.get("mao", ""))
    objeto = str(video.get("objeto", "")).strip()
    plano = {
        "analise": {
            "resumo_pt": str(analise.get("resumo_pt", "")),
            "movimento_en": str(analise.get("movimento_en", "")),
            "enquadramento": str(analise.get("enquadramento", "")),
            "cabeca_visivel": bool(analise.get("cabeca_visivel")),
            "tronco_inteiro": bool(analise.get("tronco_inteiro")),
            "texto_sobre_corpo": bool(analise.get("texto_sobre_corpo")),
            "mao_celular": str(analise.get("mao_celular", "")),
        },
        "motor": motor,
        "modelo": modelo,
        "porque_pt": str(dados.get("porque_pt", "")),
        "usar": usar_ok,
        "criar": criar,
        "video": {
            "nome": _slug(video.get("nome"), "v_planejado"),
            "pilar": pilar if pilar in PILARES else "outfit_clima",
            "duracao": duracao,
            "movimento_inicio": round(inicio, 1),
            "cena": str(video.get("cena", "")).replace(";", ",").strip()[:600],
            "camera": "" if movimento else str(video.get("camera", "")).strip()[:120],
            "objeto": objeto[:80],
            "mao": mao if (mao in ("right", "left") and objeto) else "",
            "orientacao": "image" if video.get("orientacao") == "image" else "video",
            "sem_rosto": sem_rosto,
        },
        "passos_pt": [str(p) for p in (dados.get("passos_pt") or [])][:8],
        "riscos_pt": [str(r) for r in (dados.get("riscos_pt") or [])][:8] + avisos,
    }
    return plano


def pedido_do_plano(plano: dict, movimento: str | None) -> dict:
    """Converte o plano no formato de pedido de vídeo do Estúdio (PedidoVideo)."""
    v, u = plano["video"], plano["usar"]
    kling = plano["motor"] == "kling"
    return {
        "nome": v["nome"], "tipo": "ellie", "pilar": v["pilar"], "modelo": plano["modelo"], "resolucao": "720p",
        "duracao": v["duracao"], "persona": [] if kling else u["persona"], "peca": None if kling else (u["peca"] or None),
        "cenario": None if kling else (u["cenario"] or None), "movimento": movimento,
        "movimento_inicio": v["movimento_inicio"], "imagem_base": (u["imagem_base"] or None) if kling else None,
        "orientacao": v["orientacao"], "cena": v["cena"], "camera": v["camera"], "objeto": v["objeto"], "mao": v["mao"],
        "aumentar_1080": True, "sem_rosto": bool(v.get("sem_rosto")),
    }
