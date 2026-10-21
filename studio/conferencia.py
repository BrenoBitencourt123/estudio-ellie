"""Conferência de coerência: o material cumpre o que a cena exige?

Antes do gasto, o quadro inicial de cada cena é comparado com as exigências dela: quem aparece, a ação,
a câmera e o espaço para o movimento planejado. Depois da geração, a tomada baixada passa por conferência
técnica (duração, formato e faixa de áudio quando o plano pede som original) e visual (folha de quadros
contra a ação planejada). Reprovação segura o próximo passo até corrigir ou aceitar conscientemente.

Uma conferência vale para a versão exata do material e das exigências (assinatura). Mudou a imagem, a
descrição ou a ficha: ela volta a ficar pendente.
"""
from __future__ import annotations

import hashlib
import json

from studio.assistente import extrair_json

SITUACOES = ("pendente", "ok", "aceita", "problema", "indeterminada")


def exigencias(p: dict, s: dict) -> list[str]:
    """O que a cena precisa mostrar. Exigências explícitas valem mais; sem elas, a descrição da cena."""
    itens = [e.strip() for e in s.get("exigencias") or [] if e and e.strip()]
    if not itens:
        itens = [t.strip() for t in (s.get("descricao"), s.get("intencao")) if t and t.strip()]
    if not itens and (s.get("prompt") or "").strip():  # cena antiga, só com o prompt técnico
        itens = [f"Mostrar o que o prompt da cena pede: {s['prompt'].strip()[:300]}"]
    ficha = p.get("ficha") or {}
    return itens + [f"Restrição da produção: {r}" for r in ficha.get("restricoes") or [] if r.strip()]


def assinatura(p: dict, s: dict, midia: dict | None) -> str:
    dados = {"midia": midia, "exigencias": exigencias(p, s), "prompt": s.get("prompt"), "tipo": s.get("tipo"),
             "criterios": (p.get("ficha") or {}).get("criterios")}
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def situacao(conf: dict | None, ass: str) -> str:
    if not conf or conf.get("assinatura") != ass:
        return "pendente"
    if conf.get("aceita"):
        return "aceita"
    return {True: "ok", False: "problema"}.get(conf.get("atende"), "indeterminada")


def _cena(p: dict, s: dict) -> str:
    direcao = p.get("direcao") or {}
    ficha = p.get("ficha") or {}
    return json.dumps({
        "cena": {k: s.get(k) for k in ("titulo", "descricao", "intencao", "fala", "prompt", "tipo")},
        "exigencias": exigencias(p, s),
        "criterios_da_producao": ficha.get("criterios") or [],
        "visual_da_producao": direcao.get("visual", ""),
    }, ensure_ascii=False)


CONTRATO = ('Responda SOMENTE JSON: {"atende": true|false, "itens": [{"exigencia": "...", "ok": true|false, '
            '"observacao": "o que se vê, em português"}], "resumo": "uma frase em português", '
            '"correcao": "instrução em inglês para refazer, vazia se atende"}. '
            'Julgue só o que está visível. "atende" é false se QUALQUER exigência central falhar: protagonista '
            'ausente ou trocado, ação errada, câmera ou enquadramento diferente do pedido, falta de espaço para o '
            'movimento planejado, restrição violada. Estilo e detalhe menor não reprovam sozinhos. '
            'Não suponha o que não aparece.')


def pedido_quadro(p: dict, s: dict) -> str:
    return ("Você é o conferente de continuidade de um estúdio de vídeo. A IMAGEM 1 é o quadro inicial da cena "
            "abaixo: o vídeo vai começar exatamente nele. Confira, exigência por exigência, se ele permite filmar "
            "o que a cena pede.\n" + CONTRATO + "\nCENA:\n" + _cena(p, s))


def pedido_video(p: dict, s: dict) -> str:
    return ("Você é o conferente de continuidade de um estúdio de vídeo. A IMAGEM 1 é uma folha com quadros "
            "numerados, em ordem, da tomada que acabou de chegar do gerador de vídeo. Confira se a tomada mostra a "
            "ação planejada, do começo ao fim, com o protagonista certo e sem defeito grave (corpo deformado, "
            "pessoa trocada, objeto que some).\n" + CONTRATO + "\nCENA:\n" + _cena(p, s))


def veredito(texto: str) -> dict:
    """Normaliza a resposta da IA. Resposta sem veredito claro fica indeterminada, nunca aprovada."""
    try:
        dados = extrair_json(texto)
    except Exception:
        dados = {}
    atende = dados.get("atende") if isinstance(dados.get("atende"), bool) else None
    itens = []
    for item in dados.get("itens") or []:
        if isinstance(item, dict) and str(item.get("exigencia", "")).strip():
            itens.append({"exigencia": str(item["exigencia"])[:200], "ok": item.get("ok") is True,
                          "observacao": str(item.get("observacao") or "")[:300]})
    if atende is True and any(not i["ok"] for i in itens):
        atende = False  # o resumo não pode aprovar o que um item reprovou
    resumo = str(dados.get("resumo") or "").strip()[:300]
    if atende is None and not resumo:
        resumo = "A conferência não devolveu um veredito claro."
    return {"atende": atende, "itens": itens[:10], "resumo": resumo, "correcao": str(dados.get("correcao") or "")[:800]}


def tecnica_video(info: dict, tem_som: bool, s: dict, ficha: dict) -> list[str]:
    """Problemas objetivos da tomada baixada, que nenhuma opinião visual compensa."""
    problemas = []
    if info["duracao"] + 0.15 < float(s.get("duracao") or 0):
        problemas.append(f"veio com {info['duracao']:.1f}s, e o pedido era {s['duracao']}s")
    largura, altura = int(info.get("width") or 0), int(info.get("height") or 0)
    if largura and altura and not 1.6 <= altura / largura <= 1.9:
        problemas.append(f"formato {largura}x{altura}, não vertical 9:16")
    if (ficha or {}).get("audio") == "original" and not tem_som:
        problemas.append("veio sem faixa de áudio, e o plano pede o som original")
    return problemas
