"""Áudio primeiro: a voz decide os cortes.

Cada cena dura o tempo de uma frase, e o corte cai no respiro, um instante antes da próxima frase
começar (como um editor corta). O vídeo termina junto com a voz, mais um respiro curto, em vez de
congelar o último quadro ou cortar a fala.
"""
from __future__ import annotations

import math

FPS = 30
CAUDA = 0.5        # respiro depois da última palavra
ANTECIPA = 0.06    # o corte entra um pouco antes da palavra seguinte
MINIMO = 1.2       # cena mais curta que isso parece piscada
MAX_CENAS = 8
VEL_MIN = 0.6      # câmera lenta máxima ao esticar uma tomada paga (60% da velocidade)
FIM_FRASE = ".!?"
PAUSA_CURTA = ",;:—–"


def _q(t: float) -> float:
    """Arredonda para o quadro: os cortes somam exatamente a duração final."""
    return round(round(t * FPS) / FPS, 4)


def duracao_total(palavras: list[dict], duracao_audio: float = 0.0) -> float:
    fim = max([w["fim"] for w in palavras] + [0.0])
    return _q(max(fim + CAUDA, duracao_audio))


def _final(palavra: str) -> str:
    return palavra.rstrip("\"'”’)]")[-1:]


def _fronteiras(palavras: list[dict]) -> list[dict]:
    """Onde dá para cortar: depois de cada palavra. Fim de frase e pausa longa valem mais."""
    saida = []
    for i in range(len(palavras) - 1):
        atual, prox = palavras[i], palavras[i + 1]
        fim = _final(atual["p"])
        peso = 3.0 if fim in FIM_FRASE else 1.5 if fim in PAUSA_CURTA else 0.0
        pausa = max(0.0, prox["ini"] - atual["fim"])
        saida.append({"i": i, "t": _q(max(atual["fim"], prox["ini"] - ANTECIPA)), "forca": peso + min(pausa, 0.6) * 4})
    return saida


def quantas_cenas(palavras: list[dict], duracao_audio: float = 0.0) -> int:
    """Uma cena por frase. Frase longa demais ganha mais cortes; frases curtas demais se juntam."""
    total = duracao_total(palavras, duracao_audio)
    n = 1 + sum(1 for c in _fronteiras(palavras) if _final(palavras[c["i"]]["p"]) in FIM_FRASE)
    if total / n > 4.5:
        n = math.ceil(total / 4.0)
    elif total / n < 1.5:
        n = max(1, math.floor(total / 1.5))
    return max(1, min(MAX_CENAS, len(palavras), n))


def dividir_em(palavras: list[dict], n: int, duracao_audio: float = 0.0) -> list[dict]:
    """Divide a fala em até n cenas, escolhendo os cortes que caem em fim de frase ou pausa e
    deixam as cenas com duração parecida. Devolve [{"ini", "fim", "texto"}] cobrindo a duração total."""
    total = duracao_total(palavras, duracao_audio)
    cands = [c for c in _fronteiras(palavras) if MINIMO * 0.5 <= c["t"] <= total - MINIMO * 0.5]
    n = max(1, min(n, len(cands) + 1))
    cortes: list[float] = []
    if n > 1:
        ideal = total / n
        pos = [0.0] + [c["t"] for c in cands] + [total]
        bonus = [0.0] + [c["forca"] for c in cands] + [0.0]

        def custo(a: int, b: int) -> float:
            d = pos[b] - pos[a]
            return ((d - ideal) / ideal) ** 2 * 4 + (50 if d < MINIMO else 0)

        m = len(pos)
        infinito = float("inf")
        # melhor[k][j]: menor custo usando k cortes, o último na posição j
        melhor = [[infinito] * m for _ in range(n)]
        veio = [[-1] * m for _ in range(n)]
        melhor[0][0] = 0.0
        for k in range(1, n):
            for j in range(1, m - 1):
                for a in range(j):
                    if melhor[k - 1][a] == infinito:
                        continue
                    valor = melhor[k - 1][a] + custo(a, j) - bonus[j] * 0.8
                    if valor < melhor[k][j]:
                        melhor[k][j], veio[k][j] = valor, a
        fim = min(range(1, m - 1), key=lambda j: melhor[n - 1][j] + custo(j, m - 1))
        escolhidos, k = [], n - 1
        while k > 0:
            escolhidos.append(fim)
            fim, k = veio[k][fim], k - 1
        cortes = [pos[j] for j in sorted(escolhidos)]
    marcos = [0.0] + cortes + [total]
    cenas = []
    for ini, fim in zip(marcos, marcos[1:]):
        texto = " ".join(w["p"] for w in palavras if ini - 0.01 <= w["ini"] < fim)
        cenas.append({"ini": _q(ini), "fim": _q(fim), "texto": texto})
    return cenas


def cenas_sugeridas(palavras: list[dict], duracao_audio: float = 0.0) -> list[dict]:
    """As frases da voz como cenas, para a IA planejar uma imagem por frase."""
    if not palavras:
        return []
    return dividir_em(palavras, quantas_cenas(palavras, duracao_audio), duracao_audio)


def sincronizar(cortes: list[dict], tomadas: list[dict], palavras: list[dict], duracao_audio: float = 0.0
                ) -> tuple[list[dict], float, list[str]]:
    """Ajusta os cortes do plano à voz: mesma ordem e mesmas tomadas, durações vindas das frases.

    Cena de imagem (gerada aqui) se estica sem custo. Tomada paga mais curta que a frase ganha câmera
    lenta até VEL_MIN; abaixo disso, pede outra tomada em vez de congelar o quadro."""
    total = duracao_total(palavras, duracao_audio)
    cenas = dividir_em(palavras, len(cortes), duracao_audio)
    avisos = []
    if len(cenas) < len(cortes):
        peso = sum(float(c['duracao']) for c in cortes)
        cenas, acumulado = [], 0.0
        for i, corte in enumerate(cortes):
            inicio = _q(acumulado)
            acumulado += total * float(corte['duracao']) / peso
            cenas.append({'ini': inicio, 'fim': total if i == len(cortes) - 1 else _q(acumulado), 'texto': ''})
        avisos.append('A fala tem poucas pausas; mantive todas as cenas e distribuí o tempo proporcionalmente ao plano.')
    shots = {s["id"]: s for s in tomadas}
    novos = []
    for corte, cena in zip(cortes, cenas):
        dur = _q(cena["fim"] - cena["ini"])
        shot = shots[corte["tomada"]]
        novo = {**corte, "duracao": dur, "velocidade": 1.0}
        if shot.get("tipo") == "imagem":
            novo["inicio"] = 0
        else:
            disponivel = float((shot.get("info") or {}).get("duracao") or shot["duracao"])
            inicio = min(float(corte.get("inicio") or 0), max(0.0, disponivel - dur))
            novo["inicio"] = round(inicio, 3)
            sobra = disponivel - inicio
            if dur > sobra + 0.02:
                velocidade = sobra / dur
                if velocidade < VEL_MIN:
                    raise ValueError(f"A tomada \"{shot['titulo']}\" tem {disponivel:.1f}s e a frase pede {dur:.1f}s. "
                                     "Troque por uma cena de imagem ou gere uma tomada mais longa.")
                novo["velocidade"] = round(velocidade, 3)
                avisos.append(f"\"{shot['titulo']}\" em câmera lenta ({round(velocidade * 100)}%) para cobrir a frase.")
        novos.append(novo)
    return novos, total, avisos
