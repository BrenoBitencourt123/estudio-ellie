"""
Autoestudo do Estúdio Ellie: cruza o que foi gerado (registro.csv), como foi pedido (geracoes.json) e como ficou
(avaliacoes.json: 👍/👎 do Breno, problemas, análise da IA e números do TikTok) para dizer:
  - qual modelo vale a pena em cada modo (custo por vídeo APROVADO, não por vídeo gerado)
  - quais problemas se repetem e como corrigir
  - quais configurações deram certo (para reusar)
  - quais vídeos de movimento o Kling rejeita
  - qual pilar traz mais seguidores
Funções puras: o servidor lê os arquivos e passa os dados.
"""

import hashlib
import json

STATUS_COBRADOS = {"ok", "enviado"}

MODOS = {
    "seedance_fotos": "Ellie a partir das fotos (Seedance)",
    "seedance_movimento": "Ellie copiando um vídeo (Seedance)",
    "kling_movimento": "Ellie copiando um vídeo (Kling)",
    "lugar": "Lugar do UK (Seedance)",
}

PROBLEMAS = {
    "maos": ("mãos estranhas", "Deixe as mãos fora do foco, diga a mão que segura o objeto e prefira movimentos sem gestos rápidos."),
    "rosto": ("rosto mudou", "Use 2 fotos de rosto bem consistentes (menos fotos costuma derivar menos) ou enquadre do queixo para baixo."),
    "roupa": ("roupa diferente da peça", "Use foto da peça limpa (sem pessoa, fundo liso) e cite a peça na cena."),
    "movimento": ("movimento ruim", "Um movimento simples e contínuo, 4 a 8s, vídeo de referência sem cortes."),
    "cenario": ("cenário errado", "Use foto do cenário nítida e diga o lugar em poucas palavras."),
    "texto": ("texto ou marca d'água", "Evite vídeo de referência com texto em cima do corpo."),
    "enquadramento": ("enquadramento errado", "Imagem e vídeo de referência com o mesmo enquadramento; diga o enquadramento na cena."),
    "objeto": ("objeto flutuando ou trocando de mão", "Preencha objeto e mão; um objeto por vez."),
    "artefatos": ("artefatos ou distorção", "Menos ações no clipe, sem palavras de velocidade (fast, rapid)."),
    "loop": ("não fecha o loop", "Termine na mesma pose ou posição de câmera do começo."),
    "sem_graca": ("ficou sem graça", "Dê uma direção de câmera clara e uma ação com intenção (ajeitar o casaco, olhar a chuva)."),
}

PILARES_META = {"outfit_clima": 0.7, "pov_london": 0.2, "lugar": 0.1}


def modo_do_pedido(pedido: dict | None, modelo_registro: str = "") -> str:
    if not pedido:
        return "kling_movimento" if modelo_registro.startswith("kling") else ""
    if pedido.get("tipo") == "lugar":
        return "lugar"
    if str(pedido.get("modelo", "")).startswith("kling"):
        return "kling_movimento"
    return "seedance_movimento" if pedido.get("movimento") else "seedance_fotos"


def assinatura(pedido: dict, prompt: str) -> str:
    """Identifica um vídeo idêntico (mesmas referências, modelo e prompt), para avisar antes de pagar de novo."""
    campos = {
        k: pedido.get(k) for k in (
            "tipo", "modelo", "resolucao", "duracao", "peca", "cenario", "movimento",
            "movimento_inicio", "imagem_base", "orientacao",
        )
    }
    campos["persona"] = sorted(pedido.get("persona") or [])
    campos["prompt"] = prompt.strip()
    return hashlib.sha1(json.dumps(campos, sort_keys=True).encode()).hexdigest()[:16]


def _custo(linha: dict) -> float:
    if linha.get("status") not in STATUS_COBRADOS:
        return 0.0
    try:
        return float(linha.get("custo_real_usd") or linha.get("custo_estimado_usd") or 0)
    except ValueError:
        return 0.0


def _num(valor) -> float | None:
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _media(valores: list[float]) -> float | None:
    return round(sum(valores) / len(valores), 2) if valores else None


def montar(registro: list[dict], geracoes: dict, avaliacoes: dict) -> dict:
    por_config: dict[tuple[str, str], dict] = {}
    contagem_problemas: dict[str, int] = {}
    pilares: dict[str, dict] = {p: {"videos": 0, "views": [], "conclusao": [], "seg_por_100": []} for p in PILARES_META}
    rejeicoes_kling: dict[str, int] = {}
    vencedores = []
    sem_avaliacao = 0

    for linha in registro:
        pid = linha.get("prediction_id", "")
        extra = geracoes.get(pid, {})
        pedido = extra.get("pedido")
        modo = modo_do_pedido(pedido, linha.get("modelo", ""))
        modelo = linha.get("modelo", "") or (pedido or {}).get("modelo", "")
        status = linha.get("status", "")
        av = avaliacoes.get(pid, {})

        if status == "falhou" and pedido and modo == "kling_movimento" and "upper body" in (linha.get("erro") or ""):
            mov = pedido.get("movimento") or "?"
            rejeicoes_kling[mov] = rejeicoes_kling.get(mov, 0) + 1

        nota = av.get("nota", "")
        # Avaliação e problemas contam para todo vídeo pronto (inclusive os antigos do gerar.py, sem pedido salvo)
        if status == "ok":
            if not nota:
                sem_avaliacao += 1
            for p in set((av.get("problemas") or []) + ((av.get("analise_ia") or {}).get("problemas") or [])):
                if p in PROBLEMAS:
                    contagem_problemas[p] = contagem_problemas.get(p, 0) + 1

        # Comparação de modelos só com quem tem o modo conhecido
        if not modo or not modelo:
            continue
        c = por_config.setdefault((modo, modelo), {
            "modo": modo, "modelo": modelo, "gerados": 0, "falhas": 0, "bons": 0, "ruins": 0, "custo_total": 0.0,
        })
        if status == "falhou":
            c["falhas"] += 1
            continue
        if status != "ok":
            continue
        c["gerados"] += 1
        c["custo_total"] += _custo(linha)
        if nota == "bom":
            c["bons"] += 1
        elif nota == "ruim":
            c["ruins"] += 1

        pilar = (pedido or {}).get("pilar", "")
        tk = av.get("tiktok") or {}
        views, conclusao, seguidores = _num(tk.get("views")), _num(tk.get("conclusao_pct")), _num(tk.get("seguidores"))
        if pilar in pilares:
            pilares[pilar]["videos"] += 1
            if views:
                pilares[pilar]["views"].append(views)
                if seguidores is not None:
                    pilares[pilar]["seg_por_100"].append(seguidores / views * 100)
            if conclusao is not None:
                pilares[pilar]["conclusao"].append(conclusao)

        if nota == "bom" and pedido:
            vencedores.append({
                "prediction_id": pid, "arquivo": linha.get("arquivo", ""), "data": linha.get("data", ""),
                "modo": modo, "modelo": modelo, "custo_usd": round(_custo(linha), 3), "pilar": pilar,
                "pedido": pedido, "prompt": extra.get("prompt", ""),
                "views": views, "conclusao_pct": conclusao, "seguidores": seguidores,
            })

    configs = []
    for c in por_config.values():
        avaliados = c["bons"] + c["ruins"]
        c["aprovacao"] = round(c["bons"] / avaliados, 2) if avaliados else None
        c["custo_por_aprovado"] = round(c["custo_total"] / c["bons"], 3) if c["bons"] else None
        c["custo_medio"] = round(c["custo_total"] / c["gerados"], 3) if c["gerados"] else None
        c["custo_total"] = round(c["custo_total"], 3)
        configs.append(c)
    configs.sort(key=lambda c: (c["modo"], c["custo_por_aprovado"] if c["custo_por_aprovado"] is not None else 99))

    # Melhor do TikTok primeiro (seguidores, depois conclusão), depois os mais recentes
    vencedores.sort(key=lambda v: (v["seguidores"] or 0, v["conclusao_pct"] or 0, v["data"]), reverse=True)

    resumo_pilares = []
    total_videos = sum(p["videos"] for p in pilares.values())
    for nome, p in pilares.items():
        resumo_pilares.append({
            "pilar": nome, "videos": p["videos"], "meta": PILARES_META[nome],
            "fatia": round(p["videos"] / total_videos, 2) if total_videos else 0,
            "views_media": _media(p["views"]), "conclusao_media": _media(p["conclusao"]),
            "seguidores_por_100_views": _media(p["seg_por_100"]),
        })

    problemas = [
        {"problema": k, "nome": PROBLEMAS[k][0], "vezes": v, "como_corrigir": PROBLEMAS[k][1]}
        for k, v in sorted(contagem_problemas.items(), key=lambda x: -x[1])
    ]

    return {
        "configs": configs,
        "problemas": problemas,
        "pilares": resumo_pilares,
        "vencedores": vencedores[:10],
        "rejeicoes_kling": [{"movimento": k, "vezes": v} for k, v in sorted(rejeicoes_kling.items(), key=lambda x: -x[1])],
        "sem_avaliacao": sem_avaliacao,
        "recomendacoes": _recomendacoes(configs, problemas, resumo_pilares, rejeicoes_kling, sem_avaliacao),
    }


def melhor_modelo(configs: list[dict], modo: str) -> dict | None:
    """O modelo mais barato por vídeo aprovado no modo, com pelo menos 2 avaliados e 60% de aprovação."""
    candidatos = [
        c for c in configs
        if c["modo"] == modo and c["custo_por_aprovado"] is not None and (c["bons"] + c["ruins"]) >= 2
        and (c["aprovacao"] or 0) >= 0.6
    ]
    return min(candidatos, key=lambda c: c["custo_por_aprovado"]) if candidatos else None


def dica_do_modo(configs: list[dict], modo: str, modelo_atual: str) -> str:
    melhor = melhor_modelo(configs, modo)
    if not melhor:
        return ""
    if melhor["modelo"] == modelo_atual:
        return f"Boa escolha: {modelo_atual} é o mais barato que dá certo nesse modo ({int(melhor['aprovacao'] * 100)}% aprovados)."
    return (
        f"Nesse modo, {melhor['modelo']} teve {int(melhor['aprovacao'] * 100)}% aprovados a "
        f"US$ {melhor['custo_por_aprovado']:.2f} por vídeo aprovado. Considere usar ele."
    )


def _recomendacoes(configs, problemas, pilares, rejeicoes_kling, sem_avaliacao) -> list[str]:
    recs = []
    if sem_avaliacao:
        recs.append(
            f"{sem_avaliacao} vídeo(s) sem avaliação. Dê 👍/👎 na Fila: é isso que ensina o sistema a escolher o modelo certo e gastar menos."
        )
    for modo, nome in MODOS.items():
        melhor = melhor_modelo(configs, modo)
        if melhor:
            recs.append(
                f"{nome}: use {melhor['modelo']} ({int(melhor['aprovacao'] * 100)}% aprovados, "
                f"US$ {melhor['custo_por_aprovado']:.2f} por vídeo aprovado)."
            )
    caros = [c for c in configs if c["gerados"] >= 2 and c["aprovacao"] is not None and c["aprovacao"] < 0.4]
    for c in caros:
        recs.append(f"{c['modelo']} em '{MODOS.get(c['modo'], c['modo'])}' aprovou só {int(c['aprovacao'] * 100)}%. Evite ou mude a abordagem.")
    for mov, vezes in rejeicoes_kling.items():
        recs.append(f"O Kling rejeitou {mov} {vezes} vez(es) (tronco ou cabeça não aparecem). Use esse vídeo só no Seedance.")
    if problemas:
        p = problemas[0]
        recs.append(f"Problema mais comum: {p['nome']} ({p['vezes']}x). {p['como_corrigir']}")
    com_dados = [p for p in pilares if p["seguidores_por_100_views"] is not None]
    if len(com_dados) >= 2:
        top = max(com_dados, key=lambda p: p["seguidores_por_100_views"])
        recs.append(f"O pilar que mais converte em seguidores é {top['pilar']} ({top['seguidores_por_100_views']} por 100 views).")
    total = sum(p["videos"] for p in pilares)
    if total >= 3:
        atras = max(pilares, key=lambda p: p["meta"] - p["fatia"])
        if atras["meta"] - atras["fatia"] > 0.1:
            recs.append(f"Pilar atrás da meta: {atras['pilar']} ({int(atras['fatia'] * 100)}% contra meta de {int(atras['meta'] * 100)}%).")
    return recs
