"""Narração do formato "narrado": voz do ElevenLabs (com o tempo de cada palavra) ou áudio enviado pelo Breno.

O tempo por palavra é o que deixa a legenda karaokê sincronizada:
- ElevenLabs: o endpoint /with-timestamps devolve o tempo de cada caractere; aqui viram palavras.
- Áudio enviado: alinha com o Whisper local (faster-whisper), se instalado; senão, distribui pelo tamanho das palavras.

Configuração no .env do projeto (lido aqui mesmo, sem depender de quem iniciou o servidor):
  ELEVENLABS_API_KEY=...        chave da conta (usa os créditos do seu plano ElevenLabs)
  ELEVENLABS_VOZ=...            voice_id padrão
  ELEVENLABS_MODELO=...         opcional; padrão eleven_multilingual_v2
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
URL = "https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps"
MODELO_PADRAO = "eleven_multilingual_v2"


def config() -> dict:
    valores = {k: os.environ.get(k, "") for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOZ", "ELEVENLABS_MODELO")}
    arquivo = RAIZ / ".env"
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            chave, _, valor = linha.partition("=")
            if chave.strip() in valores and not valores[chave.strip()]:
                valores[chave.strip()] = valor.strip().strip('"')
    return valores


def disponivel() -> dict:
    c = config()
    return {"elevenlabs": bool(c["ELEVENLABS_API_KEY"]), "voz_padrao": c["ELEVENLABS_VOZ"]}


def palavras_de_caracteres(chars: list[str], inicios: list[float], fins: list[float]) -> list[dict]:
    """Junta o alinhamento por caractere em palavras: [{"p": "God", "ini": 0.0, "fim": 0.31}, ...]."""
    palavras, atual, ini, fim = [], "", None, None
    for ch, a, b in zip(chars, inicios, fins):
        if ch.isspace():
            if atual:
                palavras.append({"p": atual, "ini": round(ini, 3), "fim": round(fim, 3)})
            atual, ini, fim = "", None, None
            continue
        if ini is None:
            ini = a
        atual += ch
        fim = b
    if atual:
        palavras.append({"p": atual, "ini": round(ini, 3), "fim": round(fim, 3)})
    return palavras


def gerar_elevenlabs(texto: str, destino: Path, voz: str = "", modelo: str = "") -> list[dict]:
    c = config()
    if not c["ELEVENLABS_API_KEY"]:
        raise ValueError("Falta ELEVENLABS_API_KEY no .env. Ou envie o áudio gerado no site do ElevenLabs.")
    voz = voz or c["ELEVENLABS_VOZ"]
    if not voz:
        raise ValueError("Escolha a voz: informe o voice_id ou defina ELEVENLABS_VOZ no .env.")
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", voz):
        raise ValueError("voice_id inválido.")
    try:
        r = requests.post(URL.format(voz=voz), headers={"xi-api-key": c["ELEVENLABS_API_KEY"]},
                          json={"text": texto, "model_id": modelo or c["ELEVENLABS_MODELO"] or MODELO_PADRAO},
                          params={"output_format": "mp3_44100_128"}, timeout=120)
    except requests.RequestException as e:
        raise ValueError(f"Não consegui falar com o ElevenLabs: {e}") from None
    if r.status_code != 200:
        try:
            detalhe = r.json().get("detail")
            detalhe = detalhe.get("message") if isinstance(detalhe, dict) else detalhe
        except ValueError:
            detalhe = r.text[:200]
        raise ValueError(f"ElevenLabs recusou ({r.status_code}): {detalhe}")
    dados = r.json()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64decode(dados["audio_base64"]))
    al = dados.get("alignment") or dados.get("normalized_alignment") or {}
    palavras = palavras_de_caracteres(al.get("characters", []), al.get("character_start_times_seconds", []),
                                      al.get("character_end_times_seconds", []))
    return palavras or alinhar_proporcional(texto, duracao_audio(destino))


def duracao_audio(caminho: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(caminho)],
                       capture_output=True, text=True, timeout=25)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError, KeyError):
        raise ValueError("O áudio enviado não é válido.") from None


def alinhar_proporcional(texto: str, duracao: float) -> list[dict]:
    """Sem tempos reais: distribui o tempo pelo tamanho de cada palavra (pausa maior após pontuação)."""
    palavras = texto.split()
    pesos = [len(p) + (4 if p[-1:] in ".!?," else 1) for p in palavras]
    total, t, saida = sum(pesos) or 1, 0.0, []
    for p, w in zip(palavras, pesos):
        d = duracao * w / total
        saida.append({"p": p, "ini": round(t, 3), "fim": round(t + d * 0.85, 3)})
        t += d
    return saida


def usar_texto_do_roteiro(ouvidas: list[dict], texto: str) -> list[dict]:
    """O Whisper erra palavras ("Amen" -> "aim in"); o roteiro é o texto certo. Usa os tempos do áudio e as palavras do roteiro:
    cada palavra do roteiro recebe o tempo do ponto equivalente (proporção de letras) na fala reconhecida."""
    roteiro = texto.split()
    if not roteiro:
        return ouvidas
    if len(roteiro) == len(ouvidas):
        return [{**w, "p": p} for w, p in zip(ouvidas, roteiro)]
    marcas, total = [], 0  # (posição acumulada de letras, tempo)
    for w in ouvidas:
        marcas.append((total, w["ini"]))
        total += len(w["p"])
        marcas.append((total, w["fim"]))
    def tempo(pos: float) -> float:
        for (a, ta), (b, tb) in zip(marcas, marcas[1:]):
            if a <= pos <= b:
                return ta if b == a else ta + (tb - ta) * (pos - a) / (b - a)
        return marcas[-1][1]
    escala = total / max(1, sum(len(p) for p in roteiro))
    saida, pos = [], 0.0
    for p in roteiro:
        ini, fim = tempo(pos * escala), tempo((pos + len(p)) * escala)
        saida.append({"p": p, "ini": round(ini, 3), "fim": round(max(fim, ini + 0.05), 3)})
        pos += len(p)
    return saida


def alinhar_arquivo(audio: Path, texto: str = "") -> list[dict]:
    """Tempo por palavra de um áudio enviado. Usa o Whisper local se estiver instalado."""
    try:
        import wave
        import numpy as np
        from faster_whisper import WhisperModel
        tmp = audio.with_suffix(".16k.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000", str(tmp)],
                       check=True, timeout=60)
        with wave.open(str(tmp)) as w:
            sinal = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        tmp.unlink(missing_ok=True)
        modelo = WhisperModel("base.en", device="cpu", compute_type="int8")
        segmentos, _ = modelo.transcribe(sinal, word_timestamps=True)
        palavras = [{"p": w.word.strip(), "ini": round(w.start, 3), "fim": round(w.end, 3)}
                    for s in segmentos for w in (s.words or []) if w.word.strip()]
        if palavras:
            return usar_texto_do_roteiro(palavras, texto)
    except Exception:  # Whisper ausente ou falhou: segue com a distribuição proporcional
        pass
    if not texto.strip():
        raise ValueError("Não consegui alinhar o áudio. Escreva o texto da narração para eu distribuir a legenda.")
    return alinhar_proporcional(texto, duracao_audio(audio))
