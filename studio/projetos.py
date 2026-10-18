"""
Projetos do Estúdio Ellie: cada vídeo é um projeto que passa por etapas, da estratégia ao post medido.
Aqui ficam o cálculo da etapa e os pedidos de estratégia e de pauta para a IA (funções puras).
"""

ETAPAS = ("estrategia", "midias", "gerar", "gerando", "revisar", "postar", "postado", "medido")
NOMES_ETAPAS = {
    "estrategia": "Estratégia",
    "midias": "Plano e mídias",
    "gerar": "Pronto para gerar",
    "gerando": "Gerando",
    "revisar": "Revisar",
    "postar": "Pronto para postar",
    "postado": "Postado",
    "medido": "Medido",
}
FORMATOS = ("movimento", "fotos", "lugar")
PILARES = ("outfit_clima", "pov_london", "lugar")


def etapa(projeto: dict, pedido_valido: bool, rodando: bool, videos_ok: list[str], metricas: bool) -> str:
    if projeto.get("postado_em"):
        return "medido" if metricas else "postado"
    if projeto.get("video_escolhido"):
        return "postar"
    if rodando:
        return "gerando"
    if videos_ok:
        return "revisar"
    if pedido_valido:
        return "gerar"
    if projeto.get("plano_id") or projeto.get("gancho_en"):
        return "midias"
    return "estrategia"


FORMATO_ESTRATEGIA = """Reply with ONLY valid JSON:
{
  "titulo": "short title in Brazilian Portuguese",
  "pilar": "outfit_clima | pov_london | lugar",
  "formato": "movimento | fotos | lugar",
  "precisa_referencia": true,
  "porque_pt": "why this video helps the profile grow now, in Brazilian Portuguese (2 sentences)",
  "ganchos": [{"en": "on-screen hook in British English", "pt": "Brazilian Portuguese translation"}],
  "legenda_en": "one-line lowercase caption with 2 or 3 hashtags",
  "legenda_pt": "translation",
  "ideia_visual_pt": "what the video shows, in Brazilian Portuguese, 1 or 2 sentences (outfit, place, action)"
}
"formato": movimento = Ellie copies a reference video (best for dances, turns, trends), fotos = Ellie from photos with
a simple described action, lugar = a UK place clip without Ellie. Give exactly 3 hooks."""

REGRAS_TEXTO = """Hook rules (on-screen text): British English (London), tension in the first three words (identity, confession,
a real number or an opinion), one small specific observation, she feels rather than describes, no greeting, never ask
to follow, no dashes, readable in 2 seconds, a real person talking over coffee, not a slogan or a list of fragments.
Caption: one line, all lowercase, 2 or 3 hashtags, no dashes, not a formula question."""


def pedido_estrategia(perfil: str, ideia: str, contexto: str) -> str:
    return (
        "You are the content strategist of the TikTok profile of Ellie Hartley (AI-generated London girl). "
        "Goal: reach 500 followers fast. Turn the creator's idea into a strategy for ONE short video (7 to 9 seconds).\n"
        f"{REGRAS_TEXTO}\n\nContext:\n{contexto}\n\nCreator's idea (Portuguese): {ideia or '(none: propose the best video for today)'}\n\n"
        f"{FORMATO_ESTRATEGIA}\n\n# Profile guide\n{perfil}"
    )


def pedido_pauta(perfil: str, quantidade: int, foco: str, contexto: str) -> str:
    return (
        "You are the content strategist of the TikTok profile of Ellie Hartley (AI-generated London girl). "
        f"Goal: reach 500 followers fast. Plan the next {quantidade} videos (one per day), each 7 to 9 seconds.\n"
        "Balance the content pillars toward the 70/20/10 target, favour what the self-study says works, vary the formats "
        "and the outfits, tie outfits to the real London weather of the season, and keep each video cheap to produce.\n"
        f"{REGRAS_TEXTO}\n\nContext:\n{contexto}\n\nCreator's focus for this week (Portuguese): {foco or '(none)'}\n\n"
        'Reply with ONLY valid JSON: {"videos": [ <one object per video, same shape as below> ]}\n'
        f"Each video object:\n{FORMATO_ESTRATEGIA.split('Reply with ONLY valid JSON:', 1)[1]}\n\n# Profile guide\n{perfil}"
    )


def normalizar_estrategia(dados: dict) -> dict:
    ganchos = []
    for g in (dados.get("ganchos") or [])[:3]:
        if isinstance(g, dict) and str(g.get("en", "")).strip():
            ganchos.append({"en": str(g["en"]).replace("—", ",").strip()[:160], "pt": str(g.get("pt", "")).strip()[:200]})
    pilar = str(dados.get("pilar", "")).strip()
    formato = str(dados.get("formato", "")).strip()
    return {
        "titulo": str(dados.get("titulo", "")).strip()[:80],
        "pilar": pilar if pilar in PILARES else "outfit_clima",
        "formato": formato if formato in FORMATOS else "fotos",
        "precisa_referencia": bool(dados.get("precisa_referencia")),
        "porque_pt": str(dados.get("porque_pt", "")).strip()[:500],
        "ganchos": ganchos,
        "legenda_en": str(dados.get("legenda_en", "")).replace("—", ",").strip().lower()[:220],
        "legenda_pt": str(dados.get("legenda_pt", "")).strip()[:260],
        "ideia_visual_pt": str(dados.get("ideia_visual_pt", "")).strip()[:500],
    }
