"""
Estúdio Ellie: API local pra gerar vídeos com Seedance (Atlas Cloud) por uma interface.

Uso (na pasta gemma-videos):
  python -m uvicorn studio.server:app --host 127.0.0.1 --port 8000

Reaproveita o gerar.py (pastas, preços, registro.csv, chave do .env), então o que for gerado
aqui também aparece no registro e entra no teto semanal. A chave nunca sai do servidor.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PASTA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PASTA))

import gerar  # noqa: E402  (precisa do sys.path acima)
from studio import aprendizado, assistente, planejador, projetos, rostos, texto_tela  # noqa: E402

PASTA_DADOS = Path(__file__).resolve().parent / "dados"
ARQUIVO_RECEITAS = PASTA_DADOS / "receitas.json"
ARQUIVO_GERACOES = PASTA_DADOS / "geracoes.json"
PASTA_BRIEFINGS = PASTA_DADOS / "briefings"
ARQUIVO_RASCUNHOS = PASTA_DADOS / "rascunhos.json"
ARQUIVO_AVALIACOES = PASTA_DADOS / "avaliacoes.json"
ARQUIVO_PLANOS = PASTA_DADOS / "planos.json"
ARQUIVO_PROJETOS = PASTA_DADOS / "projetos.json"
ARQUIVO_ROSTOS = PASTA_DADOS / "rostos.json"
ARQUIVO_PERFIL = Path(__file__).resolve().parent / "perfil_ellie.md"
PILARES = ("outfit_clima", "pov_london", "lugar")
# Serviço Node do Estúdio (studio/mcp): também é a ponte com o OpenClaw (IA pela assinatura do Breno)
URL_IA = os.environ.get("ESTUDIO_IA_URL", "http://127.0.0.1:8790")
PASTA_MOVIMENTOS_PREPARADOS = gerar.PASTA_LIMPOS

PASTAS = {
    "persona": gerar.PASTA_PERSONA,
    "pecas": gerar.PASTA_PECAS,
    "cenarios": gerar.PASTA_CENARIOS,
    "movimentos": gerar.PASTA_MOVIMENTOS,
    "base": PASTA / "base",  # imagem única da Ellie (já vestida e no cenário) usada pelo Kling
}

# Kling Motion Control na Atlas Cloud: usa 1 imagem + 1 vídeo de movimento, cobra por segundo de vídeo gerado.
# Preços (US$/s) publicados nas páginas dos modelos em 10/2026; o valor real aparece no registro.csv.
KLING_MODELOS = {
    "kling-2.6-std": "kwaivgi/kling-v2.6-std/motion-control",
    "kling-2.6-pro": "kwaivgi/kling-v2.6-pro/motion-control",
    "kling-3.0-std": "kwaivgi/kling-v3.0-std/motion-control",
    "kling-3.0-pro": "kwaivgi/kling-v3.0-pro/motion-control",
}
KLING_PRECOS = {"kling-2.6-std": 0.06, "kling-2.6-pro": 0.095, "kling-3.0-std": 0.107, "kling-3.0-pro": 0.143}
TAMANHO_MAXIMO_KLING = 10 * 1024 * 1024  # imagem e vídeo: até 10 MB cada
EXT_VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
TAMANHO_MAXIMO_UPLOAD = 300 * 1024 * 1024
MAX_IMAGENS_REFERENCIA = 9
DESCONTO_VIDEO_MOVIMENTO = 0.6  # a Atlas cobra o vídeo de movimento com 40% de desconto

TRAVA = threading.Lock()  # protege registro.csv, geracoes.json e JOBS
JOBS: dict[str, dict] = {}

app = FastAPI(title="Estúdio Ellie")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def config_env() -> dict[str, str]:
    try:
        return gerar.carregar_env()
    except SystemExit:
        raise HTTPException(500, "Arquivo .env não encontrado na pasta gemma-videos.")


def resolver(pasta_chave: str, nome: str) -> Path:
    """Devolve o caminho de um arquivo da biblioteca, sem deixar escapar da pasta."""
    pasta = PASTAS[pasta_chave].resolve()
    caminho = (pasta / nome).resolve()
    if caminho.parent != pasta or not caminho.is_file():
        raise HTTPException(400, f"Arquivo não encontrado em {pasta_chave}/: {nome}")
    return caminho


def listar(pasta: Path, extensoes: set[str]) -> list[str]:
    if not pasta.exists():
        return []
    return sorted(p.name for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in extensoes)


def ler_json(arquivo: Path, padrao):
    if not arquivo.exists():
        return padrao
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except ValueError:
        return padrao


def salvar_json(arquivo: Path, dados) -> None:
    PASTA_DADOS.mkdir(exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")[:40]


def duracao_movimento(caminho: Path, inicio: float, duracao: int) -> float:
    total = gerar.duracao_video(caminho)
    return max(0.0, min(duracao, total - inicio))


def eh_kling(modelo: str) -> bool:
    return modelo in KLING_MODELOS


def custo_estimado(modelo: str, resolucao: str, duracao: int, segundos_movimento: float) -> float:
    if eh_kling(modelo):
        return segundos_movimento * KLING_PRECOS[modelo]  # o vídeo gerado tem a duração do trecho de movimento
    preco = gerar.PRECOS[(modelo, resolucao)]
    if segundos_movimento:
        return (duracao + segundos_movimento) * preco * DESCONTO_VIDEO_MOVIMENTO
    return duracao * preco


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------

class PedidoVideo(BaseModel):
    nome: str = ""
    tipo: Literal["ellie", "lugar"] = "ellie"  # lugar = clipe de um local a partir de uma foto, sem a Ellie
    modelo: str
    resolucao: Literal["480p", "720p"]
    duracao: int = Field(ge=4, le=15)
    persona: list[str] = []
    peca: str | None = None
    cenario: str | None = None
    movimento: str | None = None
    movimento_inicio: float = Field(default=0, ge=0)
    cena: str = ""
    camera: str = ""  # direção de câmera (só quando não há vídeo de movimento: ele já traz a câmera)
    objeto: str = ""
    mao: Literal["", "right", "left"] = ""
    prompt_manual: str | None = None
    aumentar_1080: bool = True
    # Só Kling
    imagem_base: str | None = None
    orientacao: Literal["image", "video"] = "video"
    manter_som: bool = False
    # Crescimento do perfil: pilar de conteúdo do vídeo e rascunho de origem (quando veio do assistente)
    pilar: Literal["", "outfit_clima", "pov_london", "lugar"] = ""
    rascunho_id: str = ""
    projeto_id: str = ""  # quando o vídeo nasce de um projeto, ele entra na lista de vídeos do projeto
    sem_rosto: bool = False  # enquadrada do queixo para baixo (o formato principal da Ellie)


def validar_pedido(p: PedidoVideo) -> None:
    if p.modelo not in gerar.MODELOS and not eh_kling(p.modelo):
        raise HTTPException(400, f"Modelo inválido: {p.modelo}")
    if p.objeto.strip() and not p.mao:
        raise HTTPException(400, "Diga em qual mão ela segura o objeto.")
    if p.tipo == "lugar":
        if eh_kling(p.modelo):
            raise HTTPException(400, "O tipo Lugar usa só o Seedance.")
        if not p.cenario:
            raise HTTPException(400, "Escolha a foto do lugar (passo 1).")
        if not p.cena.strip():
            raise HTTPException(400, "Descreva a câmera e a atmosfera (passo 4).")
        return
    if eh_kling(p.modelo):
        if not p.imagem_base:
            raise HTTPException(400, "O Kling precisa da imagem base da Ellie (passo 1).")
        if not p.movimento:
            raise HTTPException(400, "O Kling precisa do vídeo de movimento (passo 3).")
        return
    if not p.persona and not p.sem_rosto:
        raise HTTPException(400, "Escolha ao menos uma foto da Ellie.")
    if p.sem_rosto:
        com_rosto = [n for n, r in mapa_rostos().items() if r and n in p.persona]
        if com_rosto:
            raise HTTPException(400, "Vídeo sem rosto, mas estas fotos da Ellie mostram o rosto: " + ", ".join(com_rosto)
                                + ". Troque por fotos sem rosto (na Biblioteca dá para criar uma versão recortada).")
    if not p.cena.strip():
        raise HTTPException(400, "Escreva a cena.")
    total = len(p.persona) + (1 if p.peca else 0) + (1 if p.cenario else 0)
    if total > MAX_IMAGENS_REFERENCIA:
        raise HTTPException(400, f"Máximo de {MAX_IMAGENS_REFERENCIA} imagens de referência (você escolheu {total}).")


def cena_com_camera(p: PedidoVideo) -> str:
    """A pesquisa do Seedance 2.0 aponta a direção de câmera como o que mais muda o resultado."""
    cena = p.cena.strip().rstrip(".")
    if p.camera.strip() and not p.movimento:
        cena += f". Camera: {p.camera.strip().rstrip('.')}"
    return cena


def construir_prompt_kling(p: PedidoVideo) -> str:
    """O Kling pega o rosto e a roupa da imagem base e o movimento do vídeo; o texto só complementa."""
    partes = []
    if p.cena.strip():
        partes.append(p.cena.strip().rstrip(".") + ".")
    if p.objeto.strip():
        partes.append(f"She holds {p.objeto.strip().rstrip('.')} in her {p.mao} hand, gripped the whole time.")
    if p.sem_rosto:
        partes.append("Framed from the chin down the whole time, her face stays out of frame.")
    partes.append(
        ("Same hair, outfit and location as the image throughout. " if p.sem_rosto
         else "Same face, hair, outfit and location as the image throughout. ")
        + 
        "Realistic smartphone footage, natural light, sharp focus, clean frame with only the scene."
    )
    return " ".join(partes)


def construir_prompt_lugar(p: PedidoVideo) -> str:
    """Clipe de um lugar: a foto trava o cenário e a cena descreve câmera e atmosfera. Sem pessoas por padrão."""
    partes = [
        "Vertical footage of the place in @Image1: same scenery, colours, architecture, weather and light.",
        cena_com_camera(p) + ".",
    ]
    if p.movimento:
        partes.append("Use @Video1 only for the camera movement; the place comes from @Image1.")
    partes.append(
        "One smooth camera movement, realistic, sharp details, the place on its own, clean frame with only the scene."
    )
    prompt = " ".join(partes)
    if p.modelo != "2.5":
        prompt = re.sub(r"@Image(\d+)", r"image \1", prompt)
        prompt = re.sub(r"@Video(\d+)", r"video \1", prompt)
    return prompt


def construir_prompt(p: PedidoVideo) -> str:
    if p.tipo == "lugar":
        return construir_prompt_lugar(p)
    if eh_kling(p.modelo):
        return construir_prompt_kling(p)
    cena = cena_com_camera(p)
    if not p.peca:  # PECA só vira referência quando há peça escolhida; sem ela, não pode sobrar no prompt
        cena = re.sub(r"\b(the )?PECA\b", "the outfit", cena)
    if p.objeto.strip():
        cena += f". She holds {p.objeto.strip().rstrip('.')} in her {p.mao} hand"
    prompt = gerar.montar_prompt(len(p.persona), bool(p.peca), bool(p.cenario), bool(p.movimento), cena, p.sem_rosto)
    if p.modelo != "2.5":
        # O Seedance 2.0 cita as referências como "image 1" / "video 1", sem @
        prompt = re.sub(r"@Image(\d+)", r"image \1", prompt)
        prompt = re.sub(r"@Video(\d+)", r"video \1", prompt)
    return prompt


# ---------------------------------------------------------------------------
# Rotas de configuração e biblioteca
# ---------------------------------------------------------------------------

@app.get("/api/config")
def obter_config():
    config = config_env()
    cotacao = float(config.get("COTACAO_USD_BRL", "5.5").replace(",", "."))
    teto_usd = float(config.get("TETO_SEMANAL_BRL", "100").replace(",", ".")) / cotacao
    return {
        "modelos": list(gerar.MODELOS),
        "modelos_kling": list(KLING_MODELOS),
        "precos": {
            **{f"{m}|{r}": v for (m, r), v in gerar.PRECOS.items()},
            **{f"{m}|-": v for m, v in KLING_PRECOS.items()},
        },
        "modelo_padrao": config.get("MODELO", "2.0-fast"),
        "resolucao_padrao": config.get("RESOLUCAO", "720p"),
        "chave_configurada": bool(config.get("ATLASCLOUD_API_KEY")),
        "gasto_semana_usd": round(gerar.gasto_da_semana_usd(gerar.ler_registro()), 4),
        "teto_usd": round(teto_usd, 4),
        "cotacao": cotacao,
        "max_imagens": MAX_IMAGENS_REFERENCIA,
        "provedor_prompt": config.get("PROVEDOR_PROMPT", "openclaw").lower(),
    }


@app.get("/api/assets")
def obter_assets():
    return {
        chave: listar(pasta, EXT_VIDEO if chave == "movimentos" else gerar.EXTENSOES_IMAGEM)
        for chave, pasta in PASTAS.items()
    }


def mapa_rostos() -> dict[str, bool]:
    """{foto da Ellie: mostra o rosto?}. Palpite do detector até o Breno marcar."""
    return rostos.mapa(PASTAS["persona"], obter_assets().get("persona", []), ARQUIVO_ROSTOS)


def persona_sem_rosto() -> list[str]:
    """Fotos da Ellie sem rosto; os recortes do queixo para baixo vêm primeiro (corpo inteiro, roupa neutra)."""
    nomes = [n for n, r in mapa_rostos().items() if not r]
    return sorted(nomes, key=lambda n: not Path(n).stem.endswith("_sem_rosto"))


@app.get("/api/persona/rostos")
def listar_rostos():
    return mapa_rostos()


class MarcaRosto(BaseModel):
    nome: str
    rosto: bool


@app.post("/api/persona/rostos")
def marcar_rosto(m: MarcaRosto):
    resolver("persona", m.nome)
    rostos.marcar(ARQUIVO_ROSTOS, m.nome, m.rosto)
    return mapa_rostos()


class PedidoRecorte(BaseModel):
    nome: str


@app.post("/api/persona/sem-rosto")
def criar_versao_sem_rosto(r: PedidoRecorte):
    """Corta a foto logo abaixo do queixo: vira referência de corpo e roupa para vídeo sem rosto."""
    origem = resolver("persona", r.nome)
    destino = origem.with_name(f"{origem.stem}_sem_rosto.png")
    try:
        rostos.recortar_sem_rosto(origem, destino)
    except OSError as erro:
        raise HTTPException(500, f"Não consegui recortar: {erro}")
    rostos.marcar(ARQUIVO_ROSTOS, destino.name, False)
    return {"nome": destino.name, "rostos": mapa_rostos()}


@app.post("/api/assets/{pasta}")
async def enviar_asset(pasta: str, arquivo: UploadFile = File(...)):
    if pasta not in PASTAS:
        raise HTTPException(404, "Pasta desconhecida.")
    permitidas = EXT_VIDEO if pasta == "movimentos" else gerar.EXTENSOES_IMAGEM
    original = Path(arquivo.filename or "arquivo")
    if original.suffix.lower() not in permitidas:
        raise HTTPException(400, f"Formato não aceito em {pasta}/: {original.suffix or '(sem extensão)'}")
    base = re.sub(r"[^A-Za-z0-9_-]", "_", original.stem) or "arquivo"
    pasta_destino = PASTAS[pasta]
    pasta_destino.mkdir(exist_ok=True)
    destino = pasta_destino / f"{base}{original.suffix.lower()}"
    versao = 2
    while destino.exists():  # nunca sobrescreve um arquivo existente
        destino = pasta_destino / f"{base}_{versao}{original.suffix.lower()}"
        versao += 1
    escrito = 0
    with destino.open("wb") as f:
        while bloco := await arquivo.read(1 << 20):
            escrito += len(bloco)
            if escrito > TAMANHO_MAXIMO_UPLOAD:
                f.close()
                destino.unlink()
                raise HTTPException(400, "Arquivo maior que 300 MB.")
            f.write(bloco)
    return {"nome": destino.name}


# ---------------------------------------------------------------------------
# Prompt e custo
# ---------------------------------------------------------------------------

@app.post("/api/prompt")
def gerar_prompt(p: PedidoVideo):
    validar_pedido(p)
    return {"prompt": construir_prompt(p)}


@app.post("/api/estimar")
def estimar(p: PedidoVideo):
    if p.modelo not in gerar.MODELOS and not eh_kling(p.modelo):
        raise HTTPException(400, f"Modelo inválido: {p.modelo}")
    segundos = 0.0
    if p.movimento:
        segundos = duracao_movimento(resolver("movimentos", p.movimento), p.movimento_inicio, p.duracao)
    custo = custo_estimado(p.modelo, p.resolucao, p.duracao, segundos)
    config = config_env()
    cotacao = float(config.get("COTACAO_USD_BRL", "5.5").replace(",", "."))
    try:
        validar_pedido(p)
        prompt = (p.prompt_manual or "").strip() or construir_prompt(p)
        repetidos = repetidos_de(p, prompt)
    except HTTPException:
        repetidos = []
    return {
        "custo_usd": round(custo, 4), "custo_brl": round(custo * cotacao, 2), "segundos_movimento": round(segundos, 1),
        "repetidos": repetidos, "dica": dica_para(p),
    }


# ---------------------------------------------------------------------------
# Assistente de prompt (IA escreve a cena a partir da sua ideia e das referências)
# ---------------------------------------------------------------------------

def perguntar_ia(texto: str, imagens: list[Path], tempo_maximo_s: int = 600) -> str:
    """Pergunta ao agente do Estúdio pela ponte OpenClaw e devolve o texto da resposta."""
    try:
        r = requests.post(
            f"{URL_IA}/ia/perguntar",
            json={"texto": texto, "imagens": [str(i) for i in imagens], "tempo_maximo_s": tempo_maximo_s},
            timeout=tempo_maximo_s + 20,
        )
    except requests.Timeout:
        raise RuntimeError("O OpenClaw excedeu o tempo de resposta. A conversa foi preservada; confira o Gateway antes de enviar novamente.")
    except requests.RequestException:
        raise RuntimeError("O serviço de IA do Estúdio (janela 'Estudio Ellie - MCP') não está aberto.")
    dados = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200:
        raise RuntimeError(dados.get("erro") or f"erro {r.status_code} na ponte com o OpenClaw")
    return dados.get("texto", "")


@app.get("/api/ia/status")
def status_ia():
    try:
        return requests.get(f"{URL_IA}/ia/status", timeout=20).json()
    except (requests.RequestException, ValueError):
        return {"conectado": False, "erro": "O serviço de IA do Estúdio não está aberto."}


class PedidoAssistente(BaseModel):
    pedido: PedidoVideo
    ideia: str = ""


class RespostaColada(BaseModel):
    texto: str


@app.post("/api/assistente")
def assistente_de_prompt(a: PedidoAssistente):
    p = a.pedido
    motor = "kling" if eh_kling(p.modelo) else "seedance"
    caminho_movimento = resolver("movimentos", p.movimento) if p.movimento else None

    # Imagens que a IA vai ver: folha das referências escolhidas e folha de quadros do movimento
    refs: list[Path] = []
    if p.tipo == "lugar":
        refs = [resolver("cenarios", p.cenario)] if p.cenario else []
    elif motor == "kling":
        refs = [resolver("base", p.imagem_base)] if p.imagem_base else []
    else:
        refs = [resolver("persona", n) for n in p.persona[:2]]
        refs += [resolver("pecas", p.peca)] if p.peca else []
        refs += [resolver("cenarios", p.cenario)] if p.cenario else []
    if not refs and not caminho_movimento:
        raise HTTPException(400, "Escolha ao menos uma referência (imagem ou vídeo) antes de pedir o prompt.")

    id_briefing = f"b{int(time.time())}"
    folhas: list[Path] = []
    try:
        if refs:
            folhas.append(assistente.montar_folha(refs, PASTA_BRIEFINGS / f"{id_briefing}_referencias.jpg"))
        if caminho_movimento:
            quadros = assistente.frames_do_video(caminho_movimento, p.movimento_inicio, p.duracao)
            folhas.append(assistente.montar_folha(quadros, PASTA_BRIEFINGS / f"{id_briefing}_movimento.jpg"))
    except (RuntimeError, OSError) as erro:
        raise HTTPException(500, str(erro))

    sistema = assistente.instrucoes(p.tipo, motor, bool(caminho_movimento))
    texto = assistente.contexto(
        a.ideia, p.duracao, [r.name for r in refs], p.movimento, p.movimento_inicio,
        p.orientacao if motor == "kling" else None,
        tem_peca=bool(p.peca),
    )
    config = config_env()
    provedor = config.get("PROVEDOR_PROMPT", "openclaw").lower()
    base = {"provedor": provedor, "folhas": [f"/briefings/{f.name}" for f in folhas]}
    briefing = f"{sistema}\n\n---\n{texto}"

    if provedor == "openclaw":
        try:
            return {**base, "resultado": assistente.interpretar_resposta(perguntar_ia(briefing, folhas))}
        except (RuntimeError, ValueError) as erro:
            # Sem OpenClaw o pedido não se perde: cai no modo manual
            return {
                **base, "provedor": "manual", "resultado": None, "briefing": briefing,
                "aviso": f"Não deu para usar o OpenClaw agora ({erro}). Use o modo manual abaixo.",
            }

    if provedor == "openai":
        chave, modelo = config.get("OPENAI_API_KEY", ""), config.get("OPENAI_MODELO", "")
        if not chave or not modelo:
            raise HTTPException(400, "Para PROVEDOR_PROMPT=openai, preencha OPENAI_API_KEY e OPENAI_MODELO no .env.")
        try:
            return {**base, "resultado": assistente.chamar_openai(chave, modelo, sistema, texto, folhas)}
        except (RuntimeError, ValueError, requests.RequestException) as erro:
            raise HTTPException(502, str(erro))

    # Modo manual: o estúdio entrega o texto pronto pra colar no ChatGPT (anexando as folhas) e depois lê a resposta
    return {**base, "resultado": None, "briefing": briefing}


@app.post("/api/assistente/interpretar")
def interpretar_resposta(r: RespostaColada):
    try:
        return {"resultado": assistente.interpretar_resposta(r.texto)}
    except ValueError as erro:
        raise HTTPException(400, str(erro))


# ---------------------------------------------------------------------------
# Ferramentas para agentes (usadas pelo servidor MCP em studio/mcp)
# O agente vê referências, escreve a cena e deixa RASCUNHOS. Gerar (e gastar) é sempre clique do Breno.
# ---------------------------------------------------------------------------

def dados_aprendizado() -> dict:
    return aprendizado.montar(gerar.ler_registro(), ler_json(ARQUIVO_GERACOES, {}), ler_json(ARQUIVO_AVALIACOES, {}))


def repetidos_de(p: PedidoVideo, prompt: str) -> list[dict]:
    """Vídeos já gerados com exatamente as mesmas referências, modelo e prompt (para não pagar de novo sem querer)."""
    alvo = aprendizado.assinatura(p.model_dump(), prompt)
    geracoes = ler_json(ARQUIVO_GERACOES, {})
    avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
    achados = []
    for linha in gerar.ler_registro():
        extra = geracoes.get(linha["prediction_id"], {})
        if linha["status"] == "ok" and extra.get("assinatura") == alvo:
            achados.append({
                "arquivo": linha.get("arquivo", ""), "data": linha.get("data", ""),
                "nota": avaliacoes.get(linha["prediction_id"], {}).get("nota", ""),
            })
    return achados


def dica_para(p: PedidoVideo) -> str:
    modo = aprendizado.modo_do_pedido(p.model_dump())
    modelo = p.modelo if eh_kling(p.modelo) else f"{p.modelo} {p.resolucao}"
    return aprendizado.dica_do_modo(dados_aprendizado()["configs"], modo, modelo)


class PedidoFolha(BaseModel):
    pasta: str
    nomes: list[str] = []
    pagina: int = Field(default=1, ge=1)


class PedidoQuadros(BaseModel):
    fonte: Literal["movimentos", "saida"]
    arquivo: str
    inicio: float = Field(default=0, ge=0)
    duracao: float | None = Field(default=None, gt=0)
    quantidade: int = Field(default=6, ge=2, le=12)


class PedidoRascunho(BaseModel):
    pedido: PedidoVideo
    nota: str = ""  # por que esse vídeo, em português (o Breno lê antes de gerar)
    origem: str = "assistente"
    substitui: str = ""  # id de um rascunho anterior que este substitui


ITENS_POR_FOLHA = 12


@app.get("/api/regras")
def regras_do_perfil():
    perfil = ARQUIVO_PERFIL.read_text(encoding="utf-8") if ARQUIVO_PERFIL.exists() else ""
    return {"perfil": perfil, "cena": assistente.regras_cena_texto()}


def caminho_saida(nome: str) -> Path:
    pasta = gerar.PASTA_SAIDA.resolve()
    caminho = (pasta / nome).resolve()
    if caminho.parent != pasta or caminho.suffix.lower() != ".mp4" or not caminho.is_file():
        raise HTTPException(400, f"Vídeo não encontrado em saida/: {nome}")
    return caminho


@app.post("/api/folha")
def folha_da_biblioteca(f: PedidoFolha):
    """Folha numerada de uma pasta da biblioteca (de vídeos, mostra um quadro de cada)."""
    if f.pasta not in PASTAS:
        raise HTTPException(400, f"Pasta desconhecida: {f.pasta}. Use: {', '.join(PASTAS)}")
    eh_video = f.pasta == "movimentos"
    todos = listar(PASTAS[f.pasta], EXT_VIDEO if eh_video else gerar.EXTENSOES_IMAGEM)
    nomes = [n for n in todos if n in f.nomes] if f.nomes else todos
    paginas = max(1, (len(nomes) + ITENS_POR_FOLHA - 1) // ITENS_POR_FOLHA)
    pagina = nomes[(f.pagina - 1) * ITENS_POR_FOLHA: f.pagina * ITENS_POR_FOLHA]
    if not pagina:
        return {"url": "", "itens": [], "pagina": f.pagina, "paginas": paginas, "total": len(nomes)}
    try:
        imagens = []
        for nome in pagina:
            caminho = resolver(f.pasta, nome)
            if eh_video:
                total = gerar.duracao_video(caminho)
                imagens += assistente.frames_do_video(caminho, min(1.0, total / 3), 1, quantidade=1)[:1]
            else:
                imagens.append(caminho)
        destino = PASTA_BRIEFINGS / f"folha_{f.pasta}_{f.pagina}_{int(time.time() * 1000)}.jpg"
        assistente.montar_folha(imagens, destino, colunas=4, celula=240, numerar=True)
    except (RuntimeError, OSError, SystemExit) as erro:
        raise HTTPException(500, f"Não consegui montar a folha: {erro}")
    itens = []
    for i, nome in enumerate(pagina):
        item = {"n": i + 1, "nome": nome}
        if eh_video:
            item["duracao_s"] = round(gerar.duracao_video(resolver(f.pasta, nome)), 1)
        itens.append(item)
    return {"url": f"/briefings/{destino.name}", "itens": itens, "pagina": f.pagina, "paginas": paginas, "total": len(nomes)}


@app.post("/api/quadros")
def quadros_de_video(q: PedidoQuadros):
    """Quadros em ordem de um vídeo de movimento (antes de usar) ou de um vídeo gerado (para revisar)."""
    caminho = resolver("movimentos", q.arquivo) if q.fonte == "movimentos" else caminho_saida(q.arquivo)
    try:
        total = gerar.duracao_video(caminho)
    except SystemExit:
        raise HTTPException(500, f"Não consegui ler a duração de {q.arquivo}.")
    inicio = min(q.inicio, max(0.0, total - 1))
    trecho = min(q.duracao or (total - inicio), total - inicio)
    try:
        quadros = assistente.frames_do_video(caminho, inicio, trecho, quantidade=q.quantidade)
        destino = PASTA_BRIEFINGS / f"quadros_{Path(q.arquivo).stem}_{int(time.time() * 1000)}.jpg"
        assistente.montar_folha(quadros, destino, colunas=min(q.quantidade, 6) if q.quantidade <= 6 else 4,
                                celula=220, numerar=True)
    except (RuntimeError, OSError) as erro:
        raise HTTPException(500, str(erro))
    return {
        "url": f"/briefings/{destino.name}", "duracao_total_s": round(total, 2),
        "inicio_s": round(inicio, 2), "trecho_s": round(trecho, 2), "quadros": len(quadros),
    }


class Tiktok(BaseModel):
    views: float | None = Field(default=None, ge=0)
    conclusao_pct: float | None = Field(default=None, ge=0, le=100)
    seguidores: float | None = Field(default=None, ge=0)
    postado_em: str = ""


class AnaliseIa(BaseModel):
    problemas: list[str] = []
    comentario: str = ""


class PedidoAvaliacao(BaseModel):
    prediction_id: str = ""
    arquivo: str = ""  # alternativa ao prediction_id (aceita também a versão _1080)
    nota: Literal["", "bom", "ruim"] | None = None
    problemas: list[str] | None = None
    comentario: str | None = None
    analise_ia: AnaliseIa | None = None
    tiktok: Tiktok | None = None


@app.post("/api/avaliar")
def avaliar(a: PedidoAvaliacao):
    """Guarda o que aconteceu com um vídeo. Só os campos enviados mudam (o resto fica como estava)."""
    registro = gerar.ler_registro()
    pid = a.prediction_id
    if not pid and a.arquivo:
        alvo = a.arquivo.replace("_1080.mp4", ".mp4")
        pid = next((l["prediction_id"] for l in registro if l.get("arquivo") == alvo), "")
    if not pid or not any(l["prediction_id"] == pid for l in registro):
        raise HTTPException(404, f"Vídeo não encontrado no registro: {a.prediction_id or a.arquivo}")
    invalidos = [p for p in (a.problemas or []) + (a.analise_ia.problemas if a.analise_ia else []) if p not in aprendizado.PROBLEMAS]
    if invalidos:
        raise HTTPException(400, f"Problemas desconhecidos: {', '.join(invalidos)}. Use: {', '.join(aprendizado.PROBLEMAS)}")
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(pid, {})
        if a.nota is not None:
            atual["nota"] = a.nota
        if a.problemas is not None:
            atual["problemas"] = a.problemas
        if a.comentario is not None:
            atual["comentario"] = a.comentario.strip()[:500]
        if a.analise_ia is not None:
            atual["analise_ia"] = {**a.analise_ia.model_dump(), "em": datetime.now().isoformat(timespec="seconds")}
        if a.tiktok is not None:
            atual["tiktok"] = {**atual.get("tiktok", {}), **a.tiktok.model_dump(exclude_none=True)}
        atual["atualizado"] = datetime.now().isoformat(timespec="seconds")
        avaliacoes[pid] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": pid, "avaliacao": atual}


class PedidoRevisao(BaseModel):
    prediction_id: str


@app.post("/api/revisar")
def revisar_com_ia(r: PedidoRevisao):
    """O agente olha quadros do vídeo gerado, aponta problemas e o resultado entra no autoestudo (analise_ia)."""
    linha = next((l for l in gerar.ler_registro() if l["prediction_id"] == r.prediction_id), None)
    if not linha or linha.get("status") != "ok" or not linha.get("arquivo"):
        raise HTTPException(404, "Vídeo pronto não encontrado.")
    caminho = caminho_saida(linha["arquivo"])
    try:
        total = gerar.duracao_video(caminho)
        quadros = assistente.frames_do_video(caminho, 0, total, quantidade=8)
        folha = assistente.montar_folha(quadros, PASTA_BRIEFINGS / f"revisao_{caminho.stem}_{int(time.time())}.jpg",
                                        colunas=4, celula=240, numerar=True)
    except (RuntimeError, OSError, SystemExit) as erro:
        raise HTTPException(500, f"Não consegui extrair os quadros: {erro}")
    extra = ler_json(ARQUIVO_GERACOES, {}).get(r.prediction_id, {})
    chaves = ", ".join(f'"{k}" ({v[0]})' for k, v in aprendizado.PROBLEMAS.items())
    pedido_ia = (
        "Review this AI-generated vertical TikTok video of Ellie Hartley. The attached sheet shows 8 numbered frames in order.\n"
        f"The prompt used was: {extra.get('prompt') or '(unknown)'}\n"
        "Check: hands (five fingers, objects held firmly), face or chin-down framing as asked, outfit consistency, "
        "unwanted text or watermarks, background consistency, distortions, whether it would loop, and whether it is engaging.\n"
        f"Allowed problem keys: {chaves}.\n"
        'Reply with ONLY valid JSON: {"problemas": ["key", ...], "comentario": "1 or 2 sentences in Brazilian Portuguese '
        'for the creator: what is good and what to change next time", "nota_sugerida": "bom" or "ruim"}'
    )
    try:
        bruto = perguntar_ia(pedido_ia, [folha])
        dados = assistente.extrair_json(bruto)
    except (RuntimeError, AttributeError, ValueError) as erro:
        raise HTTPException(502, f"A revisão com IA falhou: {erro}")
    problemas = [p for p in dados.get("problemas", []) if p in aprendizado.PROBLEMAS]
    sugerida = dados.get("nota_sugerida") if dados.get("nota_sugerida") in ("bom", "ruim") else ""
    analise = {"problemas": problemas, "comentario": str(dados.get("comentario", ""))[:500], "nota_sugerida": sugerida}
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(r.prediction_id, {})
        atual["analise_ia"] = {**analise, "em": datetime.now().isoformat(timespec="seconds")}
        avaliacoes[r.prediction_id] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": r.prediction_id, "avaliacao": atual}


class PedidoLegenda(BaseModel):
    prediction_id: str


def projeto_do_video(prediction_id: str, projeto_id: str = "") -> dict | None:
    for projeto in ler_projetos():
        if (projeto_id and projeto.get("id") == projeto_id) or prediction_id in projeto.get("videos", []):
            return projeto
    return None


@app.post("/api/legenda")
def sugerir_legenda(r: PedidoLegenda):
    """A IA olha o vídeo pronto e sugere texto na tela e legenda (inglês para postar, português para o Breno)."""
    linha = next((l for l in gerar.ler_registro() if l["prediction_id"] == r.prediction_id), None)
    if not linha or linha.get("status") != "ok" or not linha.get("arquivo"):
        raise HTTPException(404, "Vídeo pronto não encontrado.")
    caminho = caminho_saida(linha["arquivo"])
    try:
        total = gerar.duracao_video(caminho)
        quadros = assistente.frames_do_video(caminho, 0, total, quantidade=6)
        folha = assistente.montar_folha(quadros, PASTA_BRIEFINGS / f"legenda_{caminho.stem}_{int(time.time())}.jpg",
                                        colunas=6, celula=200, numerar=True)
    except (RuntimeError, OSError, SystemExit) as erro:
        raise HTTPException(500, f"Não consegui extrair os quadros: {erro}")
    extra = ler_json(ARQUIVO_GERACOES, {}).get(r.prediction_id, {})
    pedido = extra.get("pedido") or {}
    perfil = ARQUIVO_PERFIL.read_text(encoding="utf-8") if ARQUIVO_PERFIL.exists() else ""
    projeto = projeto_do_video(r.prediction_id, pedido.get("projeto_id", ""))
    do_projeto = None
    contexto_projeto = ""
    if projeto and (projeto.get("gancho_en") or projeto.get("legenda_en")):
        # A estratégia do projeto já escolheu gancho e legenda: ela vira a 1ª opção e guia as outras
        do_projeto = {"texto_tela_en": projeto.get("gancho_en", ""), "texto_tela_pt": projeto.get("gancho_pt", ""),
                      "legenda_en": projeto.get("legenda_en", ""), "legenda_pt": projeto.get("legenda_pt", ""),
                      "origem": "projeto"}
        gancho, legenda = projeto.get("gancho_en", ""), projeto.get("legenda_en", "")
        contexto_projeto = (f"The project strategy already chose this hook: '{gancho}' and this caption: '{legenda}'. "
                            "Write 2 alternatives in the same direction that fit what the frames really show.\n")
    texto = (contexto_projeto +
        "Write the on-screen text and the TikTok caption for this video of Ellie Hartley (the attached sheet shows 6 frames).\n"
        f"Content pillar: {pedido.get('pilar') or 'unknown'}. Scene used: {pedido.get('cena') or extra.get('prompt', '')[:300]}\n"
        "Rules (from the profile guide below): British English (London). On-screen text: the hook, with tension in the first "
        "three words (identity, confession, a real number or an opinion), one small specific observation, she feels rather than "
        "describes, no greeting, never ask to follow, no dashes, short enough to read in 2 seconds. Caption: one line, all "
        "lowercase, ending with 2 or 3 relevant hashtags, no dashes, not a formula question. Sound like a real person talking "
        "over coffee, not a slogan. Give 3 different options and pick the best.\n"
        'Reply with ONLY valid JSON: {"opcoes": [{"texto_tela_en": "", "texto_tela_pt": "", "legenda_en": "", '
        '"legenda_pt": ""}], "recomendada": 0, "porque_pt": "why the recommended one, in Brazilian Portuguese"}\n'
        "The _pt fields are natural Brazilian Portuguese translations for the creator.\n\n"
        f"# Profile guide\n{perfil}"
    )
    try:
        dados = assistente.extrair_json(perguntar_ia(texto, [folha]))
    except (RuntimeError, ValueError) as erro:
        if not do_projeto:
            raise HTTPException(502, f"A sugestão de legenda falhou: {erro}")
        dados = {}  # a IA falhou, mas a opção do projeto já serve
    opcoes = [do_projeto] if do_projeto else []
    for o in (dados.get("opcoes") or [])[:3]:
        if not isinstance(o, dict):
            continue
        # Regras do perfil: sem travessão e legenda minúscula
        limpo = {k: str(o.get(k, "")).replace("—", ",").replace("–", ",").strip()[:220]
                 for k in ("texto_tela_en", "texto_tela_pt", "legenda_en", "legenda_pt")}
        limpo["legenda_en"] = limpo["legenda_en"].lower()
        if limpo["texto_tela_en"] or limpo["legenda_en"]:
            opcoes.append(limpo)
    if not opcoes:
        raise HTTPException(502, "A IA não devolveu nenhuma legenda.")
    try:
        recomendada = min(max(int(dados.get("recomendada", 0)), 0), len(opcoes) - 1)
    except (TypeError, ValueError):
        recomendada = 0
    if do_projeto:
        recomendada = 0  # o gancho escolhido na estratégia continua sendo o do post, até o Breno trocar
    legendas = {
        "opcoes": opcoes, "recomendada": recomendada, "porque_pt": str(dados.get("porque_pt", ""))[:400],
        "em": datetime.now().isoformat(timespec="seconds"),
    }
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(r.prediction_id, {})
        atual["legendas"] = legendas
        avaliacoes[r.prediction_id] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": r.prediction_id, "avaliacao": atual}


class PedidoTextoTela(BaseModel):
    prediction_id: str
    texto: str = Field(min_length=2, max_length=160)
    estilo: Literal["serifa", "sans", "negrito"] = "serifa"
    posicao: Literal["auto", "alto", "meio"] = "auto"


@app.post("/api/texto-na-tela")
def aplicar_texto_na_tela(t: PedidoTextoTela):
    """Grava o texto de gancho no vídeo (posição e cor escolhidas olhando o próprio vídeo). Leva uns 20 a 40s."""
    linha = next((l for l in gerar.ler_registro() if l["prediction_id"] == t.prediction_id), None)
    if not linha or linha.get("status") != "ok" or not linha.get("arquivo"):
        raise HTTPException(404, "Vídeo pronto não encontrado.")
    original = caminho_saida(linha["arquivo"])
    versao_1080 = original.with_name(f"{original.stem}_1080.mp4")
    entrada = versao_1080 if versao_1080.exists() else original
    destino = gerar.PASTA_SAIDA / f"{original.stem}_texto.mp4"
    n = 2
    while destino.exists():
        destino = gerar.PASTA_SAIDA / f"{original.stem}_texto_{n}.mp4"
        n += 1
    texto = t.texto.replace("—", ",").replace("–", ",").strip()
    try:
        info = texto_tela.aplicar(entrada, destino, texto, t.estilo, t.posicao)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as erro:
        raise HTTPException(500, f"Não consegui aplicar o texto: {erro}")
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(t.prediction_id, {})
        atual["video_texto"] = {"arquivo": destino.name, "texto": texto, "estilo": t.estilo,
                                "em": datetime.now().isoformat(timespec="seconds"), **info}
        avaliacoes[t.prediction_id] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": t.prediction_id, "avaliacao": atual}


# Editor de texto na tela: a IA sugere, o Breno ajusta no navegador, o servidor cola a camada desenhada
FONTES_EDITOR = ("classico", "forte", "maquina", "manuscrito", "serifa", "moderna", "impacto")
FUNDOS_EDITOR = ("nenhum", "sombra", "contorno", "caixa_branca", "caixa_preta", "caixa_translucida")


def video_pronto(prediction_id: str) -> tuple[dict, Path, Path]:
    """Linha do registro, arquivo original e a melhor versão (1080 se existir) de um vídeo pronto."""
    linha = next((l for l in gerar.ler_registro() if l["prediction_id"] == prediction_id), None)
    if not linha or linha.get("status") != "ok" or not linha.get("arquivo"):
        raise HTTPException(404, "Vídeo pronto não encontrado.")
    original = caminho_saida(linha["arquivo"])
    versao_1080 = original.with_name(f"{original.stem}_1080.mp4")
    return linha, original, versao_1080 if versao_1080.exists() else original


class PedidoPosicao(BaseModel):
    prediction_id: str
    altura: int = Field(default=240, ge=40, le=1200)
    largura: int = Field(default=470, ge=200, le=900)
    posicao: Literal["auto", "alto", "meio"] = "auto"


@app.post("/api/texto-na-tela/posicao")
def sugerir_posicao(p: PedidoPosicao):
    """Onde o bloco de texto fica mais legível (área lisa e estável, fora das zonas do TikTok) e que cor usar."""
    _, _, entrada = video_pronto(p.prediction_id)
    try:
        return texto_tela.posicao_sugerida(entrada, p.altura, p.largura, p.posicao)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as erro:
        raise HTTPException(500, f"Não consegui analisar o vídeo: {erro}")


class PedidoSugestaoTexto(BaseModel):
    prediction_id: str
    texto: str = ""


@app.post("/api/texto-na-tela/sugerir")
def sugerir_texto_na_tela(s: PedidoSugestaoTexto):
    """A IA escolhe o texto (se não vier), a fonte, o estilo de fundo e o tamanho; o algoritmo acha a posição e a cor."""
    linha, _, entrada = video_pronto(s.prediction_id)
    caminho = caminho_saida(linha["arquivo"])
    try:
        quadros = assistente.frames_do_video(caminho, 0, gerar.duracao_video(caminho), quantidade=4)
        folha = assistente.montar_folha(quadros, PASTA_BRIEFINGS / f"estilo_{caminho.stem}_{int(time.time())}.jpg",
                                        colunas=4, celula=200, numerar=True)
    except (RuntimeError, OSError, SystemExit) as erro:
        raise HTTPException(500, f"Não consegui extrair os quadros: {erro}")
    extra = ler_json(ARQUIVO_GERACOES, {}).get(s.prediction_id, {})
    pedido_ia = (
        "Design the on-screen hook text for this TikTok video of Ellie Hartley (attached: 4 frames).\n"
        + (f"Use exactly this text: {s.texto}\n" if s.texto.strip() else
           "Write the text: British English, tension in the first three words, one small specific observation, "
           "no greeting, no dashes, readable in 2 seconds, 3 to 9 words.\n")
        + f"Scene: {(extra.get('pedido') or {}).get('cena') or extra.get('prompt', '')[:300]}\n"
        f"Choose the style that fits the video's mood and stays readable over it. Fonts (TikTok-like): "
        f"classico (clean bold sans, TikTok default), forte (heavy black sans), maquina (typewriter), manuscrito "
        f"(handwriting), serifa (elegant serif italic), moderna (condensed modern sans), impacto (meme impact). "
        f"Backgrounds: nenhum (plain letters), sombra (soft shadow), contorno (outline), caixa_branca (white box, "
        f"black text), caixa_preta (black box, white text), caixa_translucida (dark translucent box).\n"
        'Reply with ONLY valid JSON: {"texto_en": "", "texto_pt": "", "fonte": "classico", "fundo": "caixa_branca", '
        '"tamanho": 62, "maiusculas": false, "porque_pt": "one sentence in Brazilian Portuguese"}\n'
        "\"tamanho\" is the font size in pixels on a 1080x1920 video (between 44 and 90)."
    )
    try:
        dados = assistente.extrair_json(perguntar_ia(pedido_ia, [folha]))
    except (RuntimeError, ValueError) as erro:
        raise HTTPException(502, f"A sugestão de estilo falhou: {erro}")
    texto = (s.texto.strip() or str(dados.get("texto_en", "")).strip()).replace("—", ",").replace("–", ",")[:160]
    if not texto:
        raise HTTPException(502, "A IA não devolveu o texto.")
    fonte = dados.get("fonte") if dados.get("fonte") in FONTES_EDITOR else "classico"
    fundo = dados.get("fundo") if dados.get("fundo") in FUNDOS_EDITOR else "caixa_branca"
    try:
        tamanho = max(44, min(90, int(dados.get("tamanho", 62))))
    except (TypeError, ValueError):
        tamanho = 62
    linhas = max(1, round(len(texto) * tamanho * 0.52 / 760 + 0.4))  # estimativa de linhas para achar o espaço
    try:
        pos = texto_tela.posicao_sugerida(entrada, int(linhas * tamanho * 1.35 + 30), 800)
    except (RuntimeError, OSError, subprocess.CalledProcessError):
        pos = {"x": 0.5, "y": 0.2, "cor": "#ffffff", "luminosidade": 128}
    return {
        "texto": texto.upper() if dados.get("maiusculas") is True else texto,
        "texto_pt": str(dados.get("texto_pt", ""))[:200], "fonte": fonte, "fundo": fundo, "tamanho": tamanho,
        "x": pos["x"], "y": pos["y"], "cor": pos["cor"] if fundo in ("nenhum", "sombra", "contorno") else "",
        "porque_pt": str(dados.get("porque_pt", ""))[:300],
    }


class PedidoCamadaTexto(BaseModel):
    prediction_id: str
    png: str  # data URL "data:image/png;base64,..." de 1080x1920 desenhada pelo editor
    texto: str = ""
    config: dict = {}


@app.post("/api/texto-na-tela/camada")
def aplicar_camada_de_texto(c: PedidoCamadaTexto):
    """Cola no vídeo a camada que o editor desenhou (o que você viu na prévia é o que sai)."""
    _, original, entrada = video_pronto(c.prediction_id)
    try:
        bruto = base64.b64decode(c.png.split(",", 1)[-1], validate=True)
    except ValueError:
        raise HTTPException(400, "A camada de texto veio corrompida.")
    if len(bruto) > 8 * 1024 * 1024:
        raise HTTPException(400, "A camada de texto é grande demais.")
    camada = PASTA_BRIEFINGS / f"camada_{original.stem}_{int(time.time() * 1000)}.png"
    camada.write_bytes(bruto)
    destino = gerar.PASTA_SAIDA / f"{original.stem}_texto.mp4"
    n = 2
    while destino.exists():
        destino = gerar.PASTA_SAIDA / f"{original.stem}_texto_{n}.mp4"
        n += 1
    try:
        texto_tela.compor(entrada, camada, destino)
    except (RuntimeError, OSError) as erro:
        raise HTTPException(400, str(erro))
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(c.prediction_id, {})
        atual["video_texto"] = {"arquivo": destino.name, "texto": c.texto[:200], "config": c.config,
                                "em": datetime.now().isoformat(timespec="seconds"), "estilo": "editor", "cor": ""}
        avaliacoes[c.prediction_id] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": c.prediction_id, "avaliacao": atual}


class PedidoParaReferencia(BaseModel):
    prediction_id: str


@app.post("/api/video/para-referencia")
def video_para_referencia(r: PedidoParaReferencia):
    """Copia um vídeo gerado (sem o texto na tela) para os vídeos de referência: o movimento que deu certo vira molde."""
    _, original, _ = video_pronto(r.prediction_id)
    PASTAS["movimentos"].mkdir(exist_ok=True)
    base = original.stem if original.stem.startswith("ellie") else f"ellie_{original.stem}"
    destino = PASTAS["movimentos"] / f"{base}.mp4"
    n = 2
    while destino.exists():
        destino = PASTAS["movimentos"] / f"{base}_{n}.mp4"
        n += 1
    shutil.copy2(original, destino)
    with TRAVA:
        avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
        atual = avaliacoes.get(r.prediction_id, {})
        atual["virou_referencia"] = destino.name
        avaliacoes[r.prediction_id] = atual
        salvar_json(ARQUIVO_AVALIACOES, avaliacoes)
    return {"prediction_id": r.prediction_id, "nome": destino.name, "avaliacao": atual}


@app.get("/api/aprendizado")
def obter_aprendizado():
    return {**dados_aprendizado(), "nomes_problemas": {k: v[0] for k, v in aprendizado.PROBLEMAS.items()}, "modos": aprendizado.MODOS}


@app.get("/api/rascunhos")
def listar_rascunhos():
    return ler_json(ARQUIVO_RASCUNHOS, [])


@app.post("/api/rascunhos")
def criar_rascunho(r: PedidoRascunho):
    """Valida o vídeo, monta o prompt final e calcula o custo. Não gera nada: fica esperando o Breno."""
    p = r.pedido
    validar_pedido(p)
    config = config_env()
    c = custo_do_pedido(p, config)
    prompt = (p.prompt_manual or "").strip() or construir_prompt(p)
    with TRAVA:
        rascunhos = [x for x in ler_json(ARQUIVO_RASCUNHOS, []) if x["id"] != r.substitui]
        rascunho = {
            "id": f"r{int(time.time() * 1000)}",
            "criado": datetime.now().isoformat(timespec="seconds"),
            "origem": r.origem[:40],
            "nota": r.nota.strip()[:600],
            "pedido": {**p.model_dump(), "rascunho_id": ""},
            "prompt": prompt,
            "custo_usd": round(c["custo"], 4),
            "custo_brl": round(c["custo"] * c["cotacao"], 2),
            "segundos_movimento": round(c["segundos"], 1),
            "passa_do_teto": c["gasto"] + c["custo"] > c["teto"],
            "repetidos": repetidos_de(p, prompt),
            "dica": dica_para(p),
        }
        rascunho["pedido"]["rascunho_id"] = rascunho["id"]
        rascunhos.append(rascunho)
        salvar_json(ARQUIVO_RASCUNHOS, rascunhos[-30:])  # guarda só os 30 mais recentes
    return rascunho


@app.delete("/api/rascunhos/{rascunho_id}")
def descartar_rascunho(rascunho_id: str):
    with TRAVA:
        rascunhos = ler_json(ARQUIVO_RASCUNHOS, [])
        salvar_json(ARQUIVO_RASCUNHOS, [r for r in rascunhos if r["id"] != rascunho_id])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Planejador: a IA estuda o vídeo de referência e a biblioteca e monta o plano (inclusive as mídias que faltam)
# ---------------------------------------------------------------------------

# Estilo fixo por tipo de mídia: garante imagens que funcionam como referência no Seedance e no Kling
ESTILO_MIDIA = {
    "pecas": "Product photo of the garment alone, on a wooden hanger or as a flat lay, plain light background, "
             "soft daylight, sharp fabric texture, no person, no text, no logo.",
    "cenarios": "The empty place, vertical smartphone photo, natural light, realistic, no people, no text.",
    "base": "Photorealistic vertical smartphone photo of the same young woman as the reference photos (Ellie): "
            "same hair and body, outfit fully visible, natural light, realistic hands, clean background details, no text.",
    "persona": "Photorealistic vertical smartphone photo of the same young woman as the reference photos (Ellie): "
               "same face, hair and body, natural light, no text.",
}


ESTILO_LOOK = (
    "One tidy flat lay of the COMPLETE outfit on a plain light background: every garment (outerwear, top, bottoms), the "
    "shoes and the bag or accessories arranged together and fully visible, soft daylight, sharp fabric texture, no person, "
    "no text, no logo."
)


def gerar_midia_ia(pasta: str, descricao: str, nome: str, referencias: list[Path], instrucao_refs: str = "",
                   estilo: str = "") -> str:
    """Gera uma imagem pelo OpenClaw e salva na pasta da biblioteca. Devolve o nome do arquivo."""
    pedido = f"{descricao.strip()}\nStyle: {estilo or ESTILO_MIDIA[pasta]} Vertical 9:16."
    try:
        r = requests.post(
            f"{URL_IA}/ia/imagem",
            json={"prompt": pedido, "proporcao": "9:16", "referencias": [str(x) for x in referencias],
                  "instrucao_referencias": instrucao_refs},
            timeout=340,
        )
    except requests.RequestException:
        raise HTTPException(502, "O serviço de IA do Estúdio (janela 'Estudio Ellie - MCP') não está aberto.")
    dados = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not dados.get("arquivos"):
        raise HTTPException(502, dados.get("erro") or "A IA não devolveu a imagem.")
    origem = Path(dados["arquivos"][0]).resolve()
    pasta_midia = (Path.home() / ".openclaw" / "media").resolve()
    if pasta_midia not in origem.parents or not origem.is_file():
        raise HTTPException(502, "A imagem gerada não está na pasta esperada do OpenClaw.")
    pasta_destino = PASTAS[pasta]
    pasta_destino.mkdir(exist_ok=True)
    base = slug(nome) or f"ia_{pasta}_{datetime.now():%d%m_%H%M%S}"
    destino = pasta_destino / f"{base}{origem.suffix.lower()}"
    versao = 2
    while destino.exists():  # nunca sobrescreve
        destino = pasta_destino / f"{base}_{versao}{origem.suffix.lower()}"
        versao += 1
    shutil.copy2(origem, destino)
    return destino.name


class PedidoNovaMidia(BaseModel):
    pasta: Literal["persona", "pecas", "cenarios", "base"]
    descricao: str = Field(default="", max_length=1200)
    nome: str = ""
    usar_fotos_ellie: bool = False
    fotos_ellie: list[str] = []  # quais fotos da Ellie servem de referência (padrão: as 2 primeiras)
    # Imagens que o Breno colou (Ctrl+V) ou anexou como referência, em data URL (até 4, 10 MB cada)
    referencias_coladas: list[str] = Field(default=[], max_length=4)
    # Só para peças: "look" recria TODAS as peças visíveis numa imagem; "peca" só a peça principal
    escopo: Literal["look", "peca"] = "look"


O_QUE_COPIAR = {"pecas": "the garment", "cenarios": "the place", "base": "the outfit", "persona": "the look and style"}


def salvar_referencias_coladas(dados: list[str]) -> list[Path]:
    """Grava as imagens coladas na pasta de briefings (dentro do projeto) para irem como anexo à IA."""
    caminhos = []
    for i, data_url in enumerate(dados):
        cabecalho, _, corpo = data_url.partition(",")
        tipo = re.search(r"image/(png|jpe?g|webp)", cabecalho or "")
        if not tipo:
            raise HTTPException(400, "Só dá para colar imagem PNG, JPG ou WEBP.")
        try:
            bruto = base64.b64decode(corpo, validate=True)
        except ValueError:
            raise HTTPException(400, "Uma das imagens coladas veio corrompida.")
        if len(bruto) > 10 * 1024 * 1024:
            raise HTTPException(400, "Imagem colada maior que 10 MB.")
        extensao = ".jpg" if tipo.group(1).startswith("jp") else f".{tipo.group(1)}"
        destino = PASTA_BRIEFINGS / f"colada_{int(time.time() * 1000)}_{i}{extensao}"
        destino.write_bytes(bruto)
        caminhos.append(destino)
    return caminhos


@app.post("/api/midia/gerar")
def gerar_midia(m: PedidoNovaMidia):
    """Cria uma imagem com IA quando o Breno quiser (não depende do plano). Leva de 30s a 1,5 min.
    Aceita imagens coladas como referência: a IA recria a roupa (ou o lugar) igual à imagem."""
    coladas = salvar_referencias_coladas(m.referencias_coladas)
    if not m.descricao.strip() and not coladas:
        raise HTTPException(400, "Descreva a imagem ou cole uma imagem de referência.")
    fotos: list[Path] = []
    if m.usar_fotos_ellie or m.pasta in ("base", "persona"):
        nomes = m.fotos_ellie or obter_assets().get("persona", [])[:2]
        fotos = [resolver("persona", n) for n in nomes[:3]]
    look = m.pasta == "pecas" and m.escopo == "look"
    alvo = "the COMPLETE outfit (every garment, the shoes and the bag or accessories)" if look else O_QUE_COPIAR[m.pasta]
    instrucao = ""
    if coladas:
        instrucao = (
            f"The first {len(coladas)} attached image(s) are references from the creator: recreate {alvo} exactly as "
            "shown (same colours, fabric, pattern, cut, length and details). "
            + ("When there are several reference images, combine the pieces from all of them into ONE outfit. "
               if len(coladas) > 1 else "")
            + "Ignore any person, background, text, price tags and watermarks in them. "
            "Pass all attached images to the image tool as reference images."
        )
        if fotos:
            instrucao += (f" The last {len(fotos)} attached images are photos of Ellie: keep her face, hair and body, "
                          "never the face or body of anyone in the reference images.")
    descricao = m.descricao.strip() or f"Recreate {alvo} from the reference image(s)."
    nome = m.nome or ("look_" if look else "")
    return {"pasta": m.pasta, "nome": gerar_midia_ia(m.pasta, descricao, nome, coladas + fotos, instrucao,
                                                      ESTILO_LOOK if look else "")}


# Criar mídia A PARTIR DO VÍDEO de referência: a roupa, o lugar ou a Ellie com aquela roupa
DO_VIDEO = {
    "pecas": "Recreate ONLY the complete outfit worn by the person in the video frames (every garment, the shoes and the "
             "bag or accessories) as one product flat lay, exactly the same colours, fabric, texture, cut, length and details.",
    "cenarios": "Recreate ONLY the place shown in the video frames, completely empty: same room or street, colours, "
                "furniture and light.",
    "base": "Photorealistic vertical smartphone photo of the same young woman as the Ellie photos, wearing exactly the "
            "outfit seen in the video frames (same colours, fabric, cut and length), in the same kind of place, with the "
            "same framing, camera distance and pose as the first video frame.",
}


def quadros_referencia(movimento: str, inicio: float = 0, quantidade: int = 3) -> list[Path]:
    """Quadros nítidos (720px) do vídeo de referência, espalhados pelo trecho, para a IA ver a roupa em detalhe."""
    caminho = resolver("movimentos", movimento)
    total = gerar.duracao_video(caminho)
    inicio = min(inicio, max(0.0, total - 1))
    pasta = PASTA_BRIEFINGS / f"ref_{Path(movimento).stem}_{int(time.time() * 1000)}"
    pasta.mkdir(parents=True, exist_ok=True)
    trecho = max(total - inicio, 1)
    resultado = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(inicio), "-i", str(caminho),
        "-vf", f"fps={quantidade / trecho:.4f},scale=720:-2", "-frames:v", str(quantidade), "-q:v", "3",
        str(pasta / "q_%02d.jpg"),
    ], capture_output=True, text=True)
    if resultado.returncode != 0:
        raise HTTPException(500, f"Não consegui extrair os quadros do vídeo: {resultado.stderr.strip()[:200]}")
    return sorted(pasta.glob("q_*.jpg"))


def gerar_midia_do_video(pasta: str, movimento: str, extra: str, nome: str, fotos_ellie: list[str],
                         inicio: float = 0) -> str:
    quadros = quadros_referencia(movimento, inicio)
    referencias = list(quadros)
    instrucao = (
        f"The first {len(quadros)} attached images are frames of a reference video: use them ONLY for "
        + {"pecas": "the outfit", "cenarios": "the place", "base": "the outfit, the place, the framing and the pose"}[pasta]
        + ". Ignore any on-screen text, captions, stickers and watermarks in them"
        + ("" if pasta == "base" else ", and leave the person out completely")
        + ". Pass the images to the image tool as reference images."
    )
    if pasta == "base":
        fotos = fotos_ellie or obter_assets().get("persona", [])[:2]
        referencias += [resolver("persona", n) for n in fotos[:2]]
        instrucao += (f" The last {len(fotos[:2])} attached images are photos of Ellie: keep her face, hair and body,"
                      " never the face or body of the person in the video.")
    descricao = DO_VIDEO[pasta] + (f" Extra details from the creator: {extra.strip()}" if extra.strip() else "")
    padrao = {"pecas": "roupa", "cenarios": "cenario", "base": "base"}[pasta]
    return gerar_midia_ia(pasta, descricao, nome or f"{padrao}_de_{Path(movimento).stem[:20]}", referencias, instrucao,
                          ESTILO_LOOK if pasta == "pecas" else "")


class PedidoMidiaDoVideo(BaseModel):
    movimento: str
    pasta: Literal["pecas", "cenarios", "base"]
    extra: str = Field(default="", max_length=600)
    nome: str = ""
    inicio: float = Field(default=0, ge=0)
    fotos_ellie: list[str] = []


@app.post("/api/midia/do-video")
def gerar_midia_a_partir_do_video(m: PedidoMidiaDoVideo):
    """Recria a roupa (ou o lugar, ou a Ellie com a roupa) a partir do vídeo de referência. Leva de 30s a 1,5 min."""
    return {"pasta": m.pasta, "nome": gerar_midia_do_video(m.pasta, m.movimento, m.extra, m.nome, m.fotos_ellie, m.inicio)}


class PedidoPlano(BaseModel):
    movimento: str | None = None
    ideia: str = ""
    inicio: float = Field(default=0, ge=0)
    sem_rosto: bool = False


class PedidoMidiaPlano(BaseModel):
    indice: int = Field(ge=0)
    prompt: str | None = None


def ler_planos() -> list[dict]:
    return ler_json(ARQUIVO_PLANOS, [])


def salvar_plano(registro: dict) -> None:
    with TRAVA:
        planos = [p for p in ler_planos() if p["id"] != registro["id"]]
        planos.append(registro)
        salvar_json(ARQUIVO_PLANOS, planos[-20:])


def buscar_plano(plano_id: str) -> dict:
    registro = next((p for p in ler_planos() if p["id"] == plano_id), None)
    if not registro:
        raise HTTPException(404, "Plano não encontrado.")
    return registro


def completar_plano(registro: dict) -> dict:
    """Acrescenta o pedido de vídeo pronto, o custo e o que ainda falta (sem salvar)."""
    pedido = planejador.pedido_do_plano(registro["plano"], registro.get("movimento"))
    pendentes = [c for c in registro["plano"]["criar"] if not c.get("arquivo")]
    completo = {**registro, "pedido": pedido, "custo_usd": None, "pronto": False, "falta": ""}
    try:
        p = PedidoVideo(**pedido)
        validar_pedido(p)
        completo["custo_usd"] = round(custo_do_pedido(p, config_env())["custo"], 3)
        completo["pronto"] = not pendentes
        completo["falta"] = "Crie as imagens que faltam (ou abra no Criar e escolha outras)." if pendentes else ""
    except HTTPException as erro:
        completo["falta"] = erro.detail if isinstance(erro.detail, str) else "Plano incompleto."
    return completo


@app.get("/api/planos")
def listar_planos():
    return [completar_plano(p) for p in reversed(ler_planos())]


@app.post("/api/plano")
def criar_plano(pp: PedidoPlano):
    """A IA estuda o vídeo (12 quadros) e as pastas da biblioteca e devolve o plano. Leva de 30s a 2 min."""
    assets = obter_assets()
    if pp.sem_rosto:
        # A IA só enxerga (e só pode escolher) fotos da Ellie sem rosto
        assets["persona"] = persona_sem_rosto()
    movimento = pp.movimento or None
    duracao_video = None
    inicio = pp.inicio
    folhas: list[Path] = []
    folhas_bib: list[tuple[str, list[str]]] = []
    id_plano = f"p{int(time.time() * 1000)}"
    try:
        if movimento:
            caminho = resolver("movimentos", movimento)
            duracao_video = gerar.duracao_video(caminho)
            inicio = min(pp.inicio, max(0.0, duracao_video - 2))
            quadros = assistente.frames_do_video(caminho, inicio, duracao_video - inicio, quantidade=12)
            folhas.append(assistente.montar_folha(
                quadros, PASTA_BRIEFINGS / f"{id_plano}_movimento.jpg", colunas=6, celula=200, numerar=True))
        for pasta in ("persona", "pecas", "cenarios", "base"):
            nomes = assets.get(pasta, [])[:12]
            if nomes:
                folhas.append(assistente.montar_folha(
                    [resolver(pasta, n) for n in nomes], PASTA_BRIEFINGS / f"{id_plano}_{pasta}.jpg",
                    colunas=6, celula=200, numerar=True))
                folhas_bib.append((pasta, nomes))
    except (RuntimeError, OSError, SystemExit) as erro:
        raise HTTPException(500, f"Não consegui preparar as imagens do plano: {erro}")

    apr = dados_aprendizado()
    rejeitados = [r["movimento"] for r in apr["rejeicoes_kling"]]
    perfil = ARQUIVO_PERFIL.read_text(encoding="utf-8") if ARQUIVO_PERFIL.exists() else ""
    texto = planejador.instrucoes(perfil, assistente.regras_cena_texto()) + "\n\n---\n" + planejador.contexto(
        pp.ideia, movimento, duracao_video, inicio, folhas_bib, assets, apr["recomendacoes"], rejeitados,
    )
    try:
        bruto = perguntar_ia(texto, folhas, tempo_maximo_s=300)
        dados = assistente.extrair_json(bruto)
    except (RuntimeError, ValueError) as erro:
        raise HTTPException(502, f"Não consegui o plano da IA: {erro}")

    registro = {
        "id": id_plano,
        "criado": datetime.now().isoformat(timespec="seconds"),
        "movimento": movimento,
        "ideia": pp.ideia.strip()[:600],
        "plano": planejador.normalizar(dados, assets, movimento, duracao_video, rejeitados, pp.sem_rosto),
        "folha_movimento": f"/briefings/{id_plano}_movimento.jpg" if movimento else "",
    }
    salvar_plano(registro)
    return completar_plano(registro)


@app.post("/api/plano/{plano_id}/midia")
def criar_midia_do_plano(plano_id: str, m: PedidoMidiaPlano):
    """Gera pelo OpenClaw uma imagem que o plano pediu e já coloca na pasta certa da biblioteca."""
    registro = buscar_plano(plano_id)
    plano = registro["plano"]
    if m.indice >= len(plano["criar"]):
        raise HTTPException(400, "Essa mídia não existe no plano.")
    item = plano["criar"][m.indice]
    if m.prompt and m.prompt.strip():
        item["prompt"] = m.prompt.strip()[:1200]
    if plano["video"].get("sem_rosto") and item["pasta"] in ("base", "persona") and "chin down" not in item["prompt"]:
        item["prompt"] += " Framed from the chin down: her face is out of frame, the photo shows her from the neck to the feet."
    referencias: list[Path] = []
    if item.get("do_video") and registro.get("movimento") and item["pasta"] in DO_VIDEO:
        # A roupa (ou o lugar) vem do próprio vídeo de referência; o prompt da IA entra como detalhe extra
        nome_arquivo = gerar_midia_do_video(
            item["pasta"], registro["movimento"], item["prompt"], item["nome"], plano["usar"]["persona"],
            float(plano["video"].get("movimento_inicio") or 0),
        )
    else:
        if item.get("usar_fotos_ellie"):
            fotos = plano["usar"]["persona"] or (persona_sem_rosto() if plano["video"].get("sem_rosto")
                                                 else obter_assets().get("persona", []))
            referencias = [resolver("persona", n) for n in fotos[:2]]
        nome_arquivo = gerar_midia_ia(item["pasta"], item["prompt"], item["nome"], referencias)

    item["arquivo"] = nome_arquivo
    usar = plano["usar"]
    if item["pasta"] == "pecas":
        usar["peca"] = nome_arquivo
    elif item["pasta"] == "cenarios":
        usar["cenario"] = nome_arquivo
    elif item["pasta"] == "base":
        usar["imagem_base"] = nome_arquivo
    elif item["pasta"] == "persona":
        usar["persona"] = (usar["persona"] + [nome_arquivo])[:4]
    salvar_plano(registro)
    return completar_plano(registro)


class EdicaoPlano(BaseModel):
    usar: dict | None = None
    video: dict | None = None
    modelo: str | None = None


@app.patch("/api/plano/{plano_id}")
def editar_plano(plano_id: str, e: EdicaoPlano):
    registro = buscar_plano(plano_id)
    plano = registro["plano"]
    if e.video and e.video.get("sem_rosto") and not (e.usar and "persona" in e.usar):
        # Ligou o sem rosto: tira as fotos com rosto que o plano tinha escolhido
        sem = set(persona_sem_rosto())
        plano["usar"]["persona"] = [n for n in plano["usar"]["persona"] if n in sem]
        if not plano["usar"]["persona"] and plano["motor"] != "kling":
            plano["usar"]["persona"] = persona_sem_rosto()[:2]
    if e.usar:
        for chave in ("persona", "peca", "cenario", "imagem_base"):
            if chave in e.usar:
                valor = e.usar[chave]
                plano["usar"][chave] = [str(v) for v in valor][:4] if chave == "persona" else str(valor or "")
    if e.video:
        for chave in ("nome", "pilar", "duracao", "movimento_inicio", "cena", "camera", "objeto", "mao", "orientacao",
                      "sem_rosto"):
            if chave in e.video:
                plano["video"][chave] = e.video[chave]
    if e.modelo:
        if e.modelo not in gerar.MODELOS and not eh_kling(e.modelo):
            raise HTTPException(400, f"Modelo inválido: {e.modelo}")
        plano["modelo"] = e.modelo
        plano["motor"] = "kling" if eh_kling(e.modelo) else "seedance"
    salvar_plano(registro)
    return completar_plano(registro)


@app.post("/api/plano/{plano_id}/rascunho")
def rascunho_do_plano(plano_id: str):
    registro = completar_plano(buscar_plano(plano_id))
    if not registro["pronto"]:
        raise HTTPException(400, registro["falta"] or "O plano ainda não está completo.")
    plano = registro["plano"]
    nota = f"Planejado pela IA. {plano['analise']['resumo_pt']} {plano['porque_pt']}".strip()[:600]
    return criar_rascunho(PedidoRascunho(pedido=PedidoVideo(**registro["pedido"]), nota=nota, origem="planejador"))


# ---------------------------------------------------------------------------
# Projetos: cada vídeo passa por estratégia, plano e mídias, geração, revisão, texto e post
# ---------------------------------------------------------------------------

CAMPOS_EDITAVEIS_PROJETO = (
    "titulo", "ideia", "pilar", "formato", "movimento", "gancho_en", "gancho_pt", "legenda_en", "legenda_pt",
    "video_escolhido", "postado_em", "arquivado", "ideia_visual_pt", "sem_rosto",
)


def ler_projetos() -> list[dict]:
    return ler_json(ARQUIVO_PROJETOS, [])


def salvar_projeto(projeto: dict) -> None:
    with TRAVA:
        lista = [p for p in ler_projetos() if p["id"] != projeto["id"]]
        projeto["atualizado"] = datetime.now().isoformat(timespec="seconds")
        lista.append(projeto)
        salvar_json(ARQUIVO_PROJETOS, lista)


def buscar_projeto(projeto_id: str) -> dict:
    projeto = next((p for p in ler_projetos() if p["id"] == projeto_id), None)
    if not projeto:
        raise HTTPException(404, "Projeto não encontrado.")
    return projeto


def vincular_video_ao_projeto(projeto_id: str, prediction_id: str) -> None:
    try:
        projeto = buscar_projeto(projeto_id)
    except HTTPException:
        return
    if prediction_id not in projeto.setdefault("videos", []):
        projeto["videos"].append(prediction_id)
        salvar_projeto(projeto)


def novo_projeto(**campos) -> dict:
    agora = datetime.now()
    projeto = {
        "id": f"j{int(time.time() * 1000)}", "criado": agora.isoformat(timespec="seconds"),
        "titulo": "", "ideia": "", "pilar": "outfit_clima", "formato": "movimento", "movimento": None,
        "gancho_en": "", "gancho_pt": "", "ganchos": [], "legenda_en": "", "legenda_pt": "", "porque_pt": "",
        "ideia_visual_pt": "", "precisa_referencia": False, "plano_id": "", "videos": [], "video_escolhido": "",
        "postado_em": "", "arquivado": False, "sem_rosto": False,
    }
    projeto.update({k: v for k, v in campos.items() if k in projeto})
    salvar_projeto(projeto)
    return projeto


def detalhar_projeto(projeto: dict, historico_por_id: dict | None = None) -> dict:
    if historico_por_id is None:
        historico_por_id = {i["prediction_id"]: i for i in itens_historico()}
    videos = [historico_por_id[v] for v in projeto.get("videos", []) if v in historico_por_id]
    videos_ok = [v["prediction_id"] for v in videos if v["status"] == "ok"]
    with TRAVA:
        rodando = any(j.get("projeto_id") == projeto["id"] and j["status"] == "rodando" for j in JOBS.values())
    rodando = rodando or any(v["status"] == "enviado" for v in videos)
    plano = None
    pedido = None
    pedido_valido = False
    if projeto.get("plano_id"):
        try:
            plano = completar_plano(buscar_plano(projeto["plano_id"]))
            pedido = {**plano["pedido"], "projeto_id": projeto["id"], "pilar": projeto.get("pilar") or plano["pedido"]["pilar"]}
            pedido_valido = plano["custo_usd"] is not None
        except HTTPException:
            plano = None
    escolhido = historico_por_id.get(projeto.get("video_escolhido", ""))
    metricas = bool(escolhido and (escolhido.get("avaliacao") or {}).get("tiktok", {}).get("views"))
    etapa = projetos.etapa(projeto, pedido_valido, rodando, videos_ok, metricas)
    capa = ""
    if videos_ok:
        ultimo = historico_por_id[videos_ok[-1]]
        capa = f"/saida/{ultimo.get('arquivo_1080') or ultimo['arquivo']}"
    return {**projeto, "etapa": etapa, "nome_etapa": projetos.NOMES_ETAPAS[etapa], "plano": plano, "pedido": pedido,
            "videos_detalhe": videos, "capa": capa}


def contexto_estrategia() -> str:
    hoje = datetime.now()
    apr = dados_aprendizado()
    pilares = ", ".join(f"{p['pilar']} {p['videos']} videos ({int(p['fatia'] * 100)}%, target {int(p['meta'] * 100)}%)"
                        for p in apr["pilares"])
    recentes = [p for p in ler_projetos() if not p.get("arquivado")][-10:]
    ja_feitos = "; ".join(f"{p['titulo']} ({p.get('gancho_en', '')})" for p in recentes if p.get("titulo")) or "none"
    melhores = "; ".join(
        f"{v['arquivo']} {v['pilar']} {v['views'] or '?'} views {v['seguidores'] or '?'} followers" for v in apr["vencedores"][:5]
    ) or "no TikTok numbers yet"
    biblioteca = obter_assets()
    return "\n".join([
        f"Today: {hoje:%d/%m/%Y} (London, {['winter', 'winter', 'spring', 'spring', 'spring', 'summer', 'summer', 'summer', 'autumn', 'autumn', 'autumn', 'winter'][hoje.month - 1]}).",
        f"Pillar balance so far: {pilares}.",
        f"Self-study recommendations: {' | '.join(apr['recomendacoes']) or 'none yet'}.",
        f"Best videos on TikTok so far: {melhores}.",
        f"Recent projects (avoid repeating): {ja_feitos}.",
        f"Library: garments {', '.join(biblioteca.get('pecas', [])[:20]) or 'none'}; places {', '.join(biblioteca.get('cenarios', [])[:20]) or 'none'}; "
        f"reference videos {', '.join(biblioteca.get('movimentos', [])[:20]) or 'none'}.",
    ])


def aplicar_estrategia(projeto: dict, est: dict) -> None:
    gancho = est["ganchos"][0] if est["ganchos"] else {"en": "", "pt": ""}
    projeto.update({
        "titulo": projeto.get("titulo") or est["titulo"], "pilar": est["pilar"], "formato": est["formato"],
        "precisa_referencia": est["precisa_referencia"], "porque_pt": est["porque_pt"], "ganchos": est["ganchos"],
        "gancho_en": gancho["en"], "gancho_pt": gancho["pt"], "legenda_en": est["legenda_en"],
        "legenda_pt": est["legenda_pt"], "ideia_visual_pt": est["ideia_visual_pt"],
    })


class PedidoProjeto(BaseModel):
    titulo: str = ""
    ideia: str = ""
    movimento: str | None = None


class PedidoPauta(BaseModel):
    quantidade: int = Field(default=7, ge=1, le=14)
    foco: str = ""


@app.get("/api/projetos")
def listar_projetos():
    historico_por_id = {i["prediction_id"]: i for i in itens_historico()}
    lista = [detalhar_projeto(p, historico_por_id) for p in ler_projetos() if not p.get("arquivado")]
    return sorted(lista, key=lambda p: p.get("atualizado", ""), reverse=True)


@app.post("/api/projetos")
def criar_projeto(p: PedidoProjeto):
    if not p.titulo.strip() and not p.ideia.strip():
        raise HTTPException(400, "Escreva ao menos a ideia do vídeo.")
    if p.movimento:
        resolver("movimentos", p.movimento)
    projeto = novo_projeto(titulo=p.titulo.strip()[:80], ideia=p.ideia.strip()[:1000], movimento=p.movimento)
    return detalhar_projeto(projeto)


@app.get("/api/projetos/{projeto_id}")
def obter_projeto(projeto_id: str):
    return detalhar_projeto(buscar_projeto(projeto_id))


@app.patch("/api/projetos/{projeto_id}")
def editar_projeto(projeto_id: str, campos: dict):
    projeto = buscar_projeto(projeto_id)
    for chave, valor in campos.items():
        if chave not in CAMPOS_EDITAVEIS_PROJETO:
            continue
        if chave == "movimento" and valor:
            resolver("movimentos", str(valor))
        projeto[chave] = valor
        if chave == "sem_rosto" and projeto.get("plano_id"):
            try:  # o plano segue o projeto
                editar_plano(projeto["plano_id"], EdicaoPlano(video={"sem_rosto": bool(valor)}))
            except HTTPException:
                pass
    salvar_projeto(projeto)
    return detalhar_projeto(projeto)


@app.post("/api/projetos/{projeto_id}/estrategia")
def estrategia_do_projeto(projeto_id: str):
    """A IA transforma a ideia em estratégia: pilar, formato, 3 ganchos, legenda e por que agora."""
    projeto = buscar_projeto(projeto_id)
    perfil = ARQUIVO_PERFIL.read_text(encoding="utf-8") if ARQUIVO_PERFIL.exists() else ""
    ideia = f"{projeto.get('titulo', '')}\n{projeto.get('ideia', '')}".strip()
    try:
        dados = assistente.extrair_json(perguntar_ia(projetos.pedido_estrategia(perfil, ideia, contexto_estrategia()), []))
    except (RuntimeError, ValueError) as erro:
        raise HTTPException(502, f"A estratégia com IA falhou: {erro}")
    aplicar_estrategia(projeto, projetos.normalizar_estrategia(dados))
    salvar_projeto(projeto)
    return detalhar_projeto(projeto)


@app.post("/api/projetos/{projeto_id}/planejar")
def planejar_projeto(projeto_id: str):
    """Estratégia pronta: a IA estuda a referência e a biblioteca e monta o plano de produção do projeto."""
    projeto = buscar_projeto(projeto_id)
    if projeto.get("formato") == "lugar":
        raise HTTPException(400, "Projetos de lugar são montados no Criar (modo Lugar). Use o botão 'Abrir no Criar'.")
    ideia = "\n".join(x for x in [
        projeto.get("ideia", ""), f"Visual: {projeto.get('ideia_visual_pt', '')}",
        f"On-screen hook: {projeto.get('gancho_en', '')}", f"Content pillar: {projeto.get('pilar', '')}",
    ] if x.strip() and not x.endswith(": "))
    registro = criar_plano(PedidoPlano(movimento=projeto.get("movimento") or None, ideia=ideia,
                                       sem_rosto=bool(projeto.get("sem_rosto"))))
    plano_salvo = buscar_plano(registro["id"])
    plano_salvo["plano"]["video"]["pilar"] = projeto.get("pilar") or plano_salvo["plano"]["video"]["pilar"]
    if projeto.get("titulo"):
        plano_salvo["plano"]["video"]["nome"] = slug(projeto["titulo"]) or plano_salvo["plano"]["video"]["nome"]
    salvar_plano(plano_salvo)
    projeto["plano_id"] = registro["id"]
    salvar_projeto(projeto)
    return detalhar_projeto(projeto)


class PedidoVideoRapido(BaseModel):
    movimento: str | None = None
    peca: str | None = None
    cenario: str | None = None
    ideia: str = ""
    sem_rosto: bool = True


@app.post("/api/projetos/rapido")
def criar_video_rapido(r: PedidoVideoRapido):
    """O caminho principal do Breno: vídeo de referência + roupa (+ cenário). Cria o projeto, pede gancho e legenda,
    monta o plano já com as mídias escolhidas e devolve o projeto pronto para gerar. Leva de 1 a 2 minutos."""
    if r.movimento:
        resolver("movimentos", r.movimento)
    if r.peca:
        resolver("pecas", r.peca)
    if r.cenario:
        resolver("cenarios", r.cenario)
    if not (r.movimento or r.peca or r.ideia.strip()):
        raise HTTPException(400, "Escolha o vídeo de referência ou a roupa (ou escreva a ideia).")
    pedidos = []
    if r.ideia.strip():
        pedidos.append(r.ideia.strip())
    if r.peca:
        pedidos.append(f"Ela usa a peça {r.peca} da biblioteca (use exatamente esse arquivo em 'peca').")
    if r.cenario:
        pedidos.append(f"No cenário {r.cenario} da biblioteca (use exatamente esse arquivo em 'cenario').")
    if r.movimento:
        pedidos.append(f"A Ellie copia o movimento do vídeo de referência {r.movimento}.")
    if r.sem_rosto:
        pedidos.append("Sem mostrar o rosto: enquadrada do queixo para baixo, o rosto fica fora do quadro.")
    ideia = " ".join(pedidos)
    projeto = novo_projeto(titulo="", ideia=ideia, movimento=r.movimento)
    projeto["formato"] = "movimento" if r.movimento else "fotos"
    projeto["sem_rosto"] = r.sem_rosto
    salvar_projeto(projeto)

    # 1) estratégia: gancho, legenda e pilar (se falhar, segue sem: dá para pedir depois)
    try:
        estrategia_do_projeto(projeto["id"])
    except HTTPException:
        pass
    projeto = buscar_projeto(projeto["id"])
    projeto["formato"] = "movimento" if r.movimento else "fotos"  # a escolha do Breno vale mais que a da IA
    projeto["movimento"] = r.movimento
    salvar_projeto(projeto)

    # 2) plano de produção com as mídias escolhidas
    detalhe = planejar_projeto(projeto["id"])
    plano_id = detalhe.get("plano_id")
    if plano_id and (r.peca or r.cenario):
        registro = buscar_plano(plano_id)
        if r.peca and registro["plano"]["motor"] == "kling":
            # Com roupa escolhida, o Seedance usa a peça direto (o Kling ignoraria e pediria outra imagem base)
            registro["plano"]["motor"] = "seedance"
            registro["plano"]["modelo"] = "2.0-fast"
            registro["plano"]["usar"]["imagem_base"] = ""
            registro["plano"]["usar"]["persona"] = registro["plano"]["usar"]["persona"] or (
                persona_sem_rosto() if r.sem_rosto else obter_assets().get("persona", []))[:2]
            registro["plano"]["criar"] = [c for c in registro["plano"]["criar"] if c["pasta"] != "base"]
            registro["plano"]["porque_pt"] = ("Seedance 2.0-fast com a roupa que você escolheu: ele usa a peça direto e copia o "
                                              "movimento do vídeo, como nos vídeos que deram certo.")
        if registro["plano"]["motor"] != "kling":
            if r.peca:
                registro["plano"]["usar"]["peca"] = r.peca
                registro["plano"]["criar"] = [c for c in registro["plano"]["criar"] if c["pasta"] != "pecas"]
            if r.cenario:
                registro["plano"]["usar"]["cenario"] = r.cenario
                registro["plano"]["criar"] = [c for c in registro["plano"]["criar"] if c["pasta"] != "cenarios"]
            salvar_plano(registro)
    return detalhar_projeto(buscar_projeto(projeto["id"]))


@app.post("/api/pauta")
def gerar_pauta(p: PedidoPauta):
    """A IA monta a pauta dos próximos dias: cada vídeo vira um projeto já com estratégia, gancho e legenda."""
    perfil = ARQUIVO_PERFIL.read_text(encoding="utf-8") if ARQUIVO_PERFIL.exists() else ""
    try:
        dados = assistente.extrair_json(
            perguntar_ia(projetos.pedido_pauta(perfil, p.quantidade, p.foco, contexto_estrategia()), [], tempo_maximo_s=400)
        )
    except (RuntimeError, ValueError) as erro:
        raise HTTPException(502, f"A pauta com IA falhou: {erro}")
    criados = []
    for item in (dados.get("videos") or [])[: p.quantidade]:
        if not isinstance(item, dict):
            continue
        est = projetos.normalizar_estrategia(item)
        projeto = novo_projeto(titulo=est["titulo"] or "Vídeo da pauta", ideia=est["ideia_visual_pt"])
        aplicar_estrategia(projeto, est)
        salvar_projeto(projeto)
        criados.append(projeto["id"])
        time.sleep(0.002)  # ids únicos
    if not criados:
        raise HTTPException(502, "A IA não devolveu nenhum vídeo para a pauta.")
    return {"criados": criados, "projetos": listar_projetos()}


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------

def preparar_movimento(caminho: Path, inicio: float, duracao: int, kling: bool = False, som: bool = False) -> Path:
    """
    Corta o rodapé (aviso de direitos do TikTok), começa em `inicio` e limita à duração.
    No Kling o arquivo precisa ter até 10 MB, então a compressão é maior e a largura limitada a 720px.
    """
    PASTA_MOVIMENTOS_PREPARADOS.mkdir(parents=True, exist_ok=True)
    sufixo = ("_k" + ("_som" if som else "")) if kling else ""
    destino = PASTA_MOVIMENTOS_PREPARADOS / f"{caminho.stem}_i{int(inicio * 10)}_{duracao}s{sufixo}.mp4"
    if destino.exists():
        return destino
    filtro = "crop=iw:trunc(ih*0.94/2)*2:0:0,fps=30"
    if kling:
        filtro += ",scale='min(720,iw)':-2"
    audio = ["-c:a", "aac", "-b:a", "96k"] if (kling and som) else ["-an"]
    comando = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(inicio), "-i", str(caminho), "-t", str(duracao), *audio,
        "-vf", filtro,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23" if kling else "18", str(destino),
    ]
    resultado = gerar.subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao preparar o movimento: {resultado.stderr.strip()[:300]}")
    if kling and destino.stat().st_size > TAMANHO_MAXIMO_KLING:
        destino.unlink()
        raise RuntimeError("O trecho de movimento passou de 10 MB (limite do Kling). Diminua a duração.")
    return destino


def subir_arquivo(chave: str, caminho: Path, tipo: str) -> str:
    """Sobe um vídeo ou imagem pelo uploadMedia da Atlas e devolve a URL."""
    with caminho.open("rb") as f:
        r = requests.post(
            f"{gerar.API}/uploadMedia", headers=gerar.cabecalho(chave),
            files={"file": (caminho.name, f, tipo)}, timeout=120,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Upload de {caminho.name} falhou ({r.status_code}): {r.text[:300]}")
    dados = r.json()
    url = dados.get("url") or (dados.get("data") or {}).get("download_url")
    if not url:
        raise RuntimeError(f"Upload de {caminho.name} sem URL: {str(dados)[:300]}")
    return url


def montar_payload_kling(job_id: str, p: PedidoVideo, prompt: str, chave: str) -> dict:
    imagem = resolver("base", p.imagem_base or "")
    if imagem.stat().st_size > TAMANHO_MAXIMO_KLING:
        raise RuntimeError("A imagem base passou de 10 MB (limite do Kling). Use uma versão menor.")
    atualizar_job(job_id, etapa="Preparando o vídeo de movimento")
    preparado = preparar_movimento(
        resolver("movimentos", p.movimento or ""), p.movimento_inicio, p.duracao, kling=True, som=p.manter_som,
    )
    atualizar_job(job_id, etapa="Enviando imagem e vídeo")
    tipo_imagem = "image/png" if imagem.suffix.lower() == ".png" else "image/jpeg"
    return {
        "model": KLING_MODELOS[p.modelo],
        "image": subir_arquivo(chave, imagem, tipo_imagem),
        "video": subir_arquivo(chave, preparado, "video/mp4"),
        "character_orientation": p.orientacao,
        "prompt": prompt,
        "keep_original_sound": p.manter_som,
    }


def iniciar_na_atlas(chave: str, payload: dict) -> str:
    r = requests.post(
        f"{gerar.API}/generateVideo",
        headers={**gerar.cabecalho(chave), "Content-Type": "application/json"},
        json=payload, timeout=120,
    )
    try:
        corpo = r.json().get("data")
    except ValueError:
        corpo = None
    prediction_id = corpo.get("id") if isinstance(corpo, dict) else None
    if r.status_code != 200 or not prediction_id:
        raise RuntimeError(f"A Atlas Cloud recusou o pedido ({r.status_code}): {r.text[:400]}")
    return prediction_id


def atualizar_job(job_id: str, **campos) -> None:
    with TRAVA:
        JOBS[job_id].update(campos)


def atualizar_registro(prediction_id: str, **campos) -> None:
    with TRAVA:
        registro = gerar.ler_registro()
        for linha in registro:
            if linha["prediction_id"] == prediction_id:
                linha.update(campos)
        gerar.salvar_registro(registro)


def esperar_e_baixar(job_id: str, chave: str, id_video: str, prediction_id: str, aumentar: bool) -> None:
    atualizar_job(job_id, etapa="Gerando na Atlas Cloud (1 a 4 min)")
    status, resultado, preco = gerar.aguardar_resultado(chave, prediction_id)
    if status != "ok":
        atualizar_registro(prediction_id, status=status, custo_real_usd=preco, erro=resultado)
        atualizar_job(job_id, status=status, etapa="Não terminou", erro=resultado)
        return
    atualizar_job(job_id, etapa="Baixando o vídeo")
    arquivo = gerar.baixar(resultado, id_video)
    final = arquivo
    if aumentar:
        atualizar_job(job_id, etapa="Aumentando para 1080p")
        final = gerar.aumentar_para_1080(arquivo)
    atualizar_registro(prediction_id, status="ok", custo_real_usd=preco, arquivo=arquivo.name)
    atualizar_job(
        job_id, status="ok", etapa="Pronto", arquivo=arquivo.name, arquivo_1080=final.name, custo_real_usd=preco,
    )


def executar_job(job_id: str, p: PedidoVideo, prompt: str, chave: str, id_video: str, custo: float) -> None:
    try:
        if eh_kling(p.modelo):
            payload = montar_payload_kling(job_id, p, prompt, chave)
        else:
            if p.tipo == "lugar":
                imagens = [resolver("cenarios", p.cenario or "")]
            else:
                imagens = [resolver("persona", n) for n in p.persona]
                imagens += [resolver("pecas", p.peca)] if p.peca else []
                imagens += [resolver("cenarios", p.cenario)] if p.cenario else []
            payload = {
                "model": gerar.MODELOS[p.modelo],
                "prompt": prompt,
                "reference_images": [gerar.imagem_base64(i) for i in imagens],
                "duration": p.duracao,
                "resolution": p.resolucao,
                "ratio": "9:16",
                "generate_audio": False,
                "watermark": False,
            }
            if p.modelo == "2.5":
                payload["output_format"] = "mp4"
                payload["omni_reference_task_type"] = "reference"
            if p.movimento:
                atualizar_job(job_id, etapa="Preparando o vídeo de movimento")
                preparado = preparar_movimento(resolver("movimentos", p.movimento), p.movimento_inicio, p.duracao)
                atualizar_job(job_id, etapa="Enviando o vídeo de movimento")
                payload["reference_videos"] = [subir_arquivo(chave, preparado, "video/mp4")]
        atualizar_job(job_id, etapa="Enviando o pedido")
        prediction_id = iniciar_na_atlas(chave, payload)
        with TRAVA:
            registro = gerar.ler_registro()
            registro.append({
                "data": datetime.now().isoformat(timespec="seconds"), "id": id_video,
                "modelo": p.modelo if eh_kling(p.modelo) else f"{p.modelo} {p.resolucao}",
                "prediction_id": prediction_id,
                "duracao": str(p.duracao), "custo_estimado_usd": f"{custo:.3f}", "custo_real_usd": "",
                "status": "enviado", "arquivo": "", "erro": "",
            })
            gerar.salvar_registro(registro)
            geracoes = ler_json(ARQUIVO_GERACOES, {})
            geracoes[prediction_id] = {
                "prompt": prompt, "pedido": p.model_dump(),
                "assinatura": aprendizado.assinatura(p.model_dump(), prompt),
            }
            salvar_json(ARQUIVO_GERACOES, geracoes)
        atualizar_job(job_id, prediction_id=prediction_id)
        if p.projeto_id:
            vincular_video_ao_projeto(p.projeto_id, prediction_id)
        esperar_e_baixar(job_id, chave, id_video, prediction_id, p.aumentar_1080)
    except Exception as erro:  # noqa: BLE001  (qualquer falha vira mensagem na tela)
        atualizar_job(job_id, status="falhou", etapa="Erro", erro=str(erro))
    except SystemExit:
        atualizar_job(job_id, status="falhou", etapa="Erro", erro="Falha interna do gerar.py (veja o terminal).")


def custo_do_pedido(p: PedidoVideo, config: dict[str, str]) -> dict:
    """Confere que todos os arquivos existem e calcula custo e folga no teto semanal (nada é cobrado aqui)."""
    for nome in p.persona:
        resolver("persona", nome)
    if p.imagem_base:
        resolver("base", p.imagem_base)
    if p.peca:
        resolver("pecas", p.peca)
    if p.cenario:
        resolver("cenarios", p.cenario)
    segundos = 0.0
    if p.movimento:
        segundos = duracao_movimento(resolver("movimentos", p.movimento), p.movimento_inicio, p.duracao)
        if segundos < 2:
            raise HTTPException(400, "O trecho do movimento ficou curto demais. Diminua o ponto de início.")
    custo = custo_estimado(p.modelo, p.resolucao, p.duracao, segundos)
    cotacao = float(config.get("COTACAO_USD_BRL", "5.5").replace(",", "."))
    teto = float(config.get("TETO_SEMANAL_BRL", "100").replace(",", ".")) / cotacao
    gasto = gerar.gasto_da_semana_usd(gerar.ler_registro())
    return {"custo": custo, "segundos": segundos, "cotacao": cotacao, "teto": teto, "gasto": gasto}


@app.post("/api/gerar")
def gerar_video(p: PedidoVideo):
    validar_pedido(p)
    config = config_env()
    chave = config.get("ATLASCLOUD_API_KEY", "")
    if not chave:
        raise HTTPException(400, "Falta ATLASCLOUD_API_KEY no .env.")
    # Confere os arquivos e o teto antes de aceitar o pedido (e antes de qualquer cobrança)
    c = custo_do_pedido(p, config)
    custo, teto, gasto = c["custo"], c["teto"], c["gasto"]
    if gasto + custo > teto:
        raise HTTPException(
            400, f"Passaria do teto semanal (gasto US$ {gasto:.2f} + este US$ {custo:.2f} > US$ {teto:.2f}). "
                 "Aumente TETO_SEMANAL_BRL no .env se quiser continuar.",
        )
    prompt = (p.prompt_manual or "").strip() or construir_prompt(p)
    id_video = slug(p.nome) or datetime.now().strftime("estudio_%d%m_%H%M%S")
    job_id = f"{id_video}_{int(time.time())}"
    with TRAVA:
        JOBS[job_id] = {
            "id": job_id, "nome": id_video, "status": "rodando", "etapa": "Na fila", "erro": "",
            "arquivo": "", "arquivo_1080": "", "prediction_id": "", "prompt": prompt,
            "custo_estimado_usd": round(custo, 4), "custo_real_usd": "", "criado": time.time(),
            "projeto_id": p.projeto_id,
        }
    threading.Thread(target=executar_job, args=(job_id, p, prompt, chave, id_video, custo), daemon=True).start()
    if p.rascunho_id:  # o rascunho virou vídeo: sai da lista de pendentes
        with TRAVA:
            rascunhos = ler_json(ARQUIVO_RASCUNHOS, [])
            salvar_json(ARQUIVO_RASCUNHOS, [r for r in rascunhos if r["id"] != p.rascunho_id])
    return JOBS[job_id]


@app.get("/api/jobs")
def listar_jobs():
    with TRAVA:
        return sorted(JOBS.values(), key=lambda j: j["criado"], reverse=True)


@app.get("/api/historico")
def historico():
    return itens_historico()[:60]


def itens_historico() -> list[dict]:
    registro = gerar.ler_registro()
    geracoes = ler_json(ARQUIVO_GERACOES, {})
    avaliacoes = ler_json(ARQUIVO_AVALIACOES, {})
    itens = []
    for linha in reversed(registro):
        extra = geracoes.get(linha["prediction_id"], {})
        arquivo = linha.get("arquivo", "")
        versao_1080 = f"{Path(arquivo).stem}_1080.mp4" if arquivo else ""
        itens.append({
            **linha,
            "arquivo_1080": versao_1080 if versao_1080 and (gerar.PASTA_SAIDA / versao_1080).exists() else "",
            "prompt": extra.get("prompt", ""),
            "pedido": extra.get("pedido"),
            "pilar": (extra.get("pedido") or {}).get("pilar", ""),
            "avaliacao": avaliacoes.get(linha["prediction_id"], {}),
        })
    return itens


@app.on_event("startup")
def retomar_pendentes() -> None:
    if os.environ.get("ESTUDIO_RETOMAR_ATLAS_LEGADO") != "1":
        return
    # Compatibilidade Atlas não pode bloquear o chat Dreamina por ausência de .env.
    if not (PASTA / ".env").exists():
        return
    """Pedidos já enviados (e cobrados) que ficaram sem resposta quando o servidor caiu."""
    try:
        chave = gerar.carregar_env().get("ATLASCLOUD_API_KEY", "")
    except SystemExit:
        return
    if not chave:
        return
    for linha in gerar.ler_registro():
        if linha["status"] == "enviado" and linha["prediction_id"]:
            job_id = f"retomado_{linha['prediction_id'][:8]}"
            JOBS[job_id] = {
                "id": job_id, "nome": linha["id"], "status": "rodando", "etapa": "Retomando pedido pendente",
                "erro": "", "arquivo": "", "arquivo_1080": "", "prediction_id": linha["prediction_id"],
                "prompt": "", "custo_estimado_usd": linha["custo_estimado_usd"], "custo_real_usd": "",
                "criado": time.time(),
            }
            threading.Thread(
                target=esperar_e_baixar, args=(job_id, chave, linha["id"], linha["prediction_id"], True), daemon=True,
            ).start()


# ---------------------------------------------------------------------------
# Receitas (configurações salvas pra repetir o mesmo setup e manter a consistência)
# ---------------------------------------------------------------------------

@app.get("/api/receitas")
def listar_receitas():
    return ler_json(ARQUIVO_RECEITAS, {})


@app.put("/api/receitas/{nome}")
def salvar_receita(nome: str, estado: dict):
    with TRAVA:
        receitas = ler_json(ARQUIVO_RECEITAS, {})
        receitas[nome[:60]] = estado
        salvar_json(ARQUIVO_RECEITAS, receitas)
    return {"ok": True}


@app.delete("/api/receitas/{nome}")
def apagar_receita(nome: str):
    with TRAVA:
        receitas = ler_json(ARQUIVO_RECEITAS, {})
        receitas.pop(nome, None)
        salvar_json(ARQUIVO_RECEITAS, receitas)
    return {"ok": True}


# Fluxo conversacional v2: reutiliza biblioteca, extrator de quadros e ponte OpenClaw.
from studio.processo import create_router as criar_processo_router
app.include_router(criar_processo_router(PASTA, perguntar_ia))

# Arquivos servidos pro navegador (só leitura)
for _chave, _pasta in PASTAS.items():
    _pasta.mkdir(exist_ok=True)
    app.mount(f"/files/{_chave}", StaticFiles(directory=_pasta), name=f"files_{_chave}")
PASTA_BRIEFINGS.mkdir(parents=True, exist_ok=True)
app.mount("/briefings", StaticFiles(directory=PASTA_BRIEFINGS), name="briefings")
gerar.PASTA_SAIDA.mkdir(exist_ok=True)
app.mount("/saida", StaticFiles(directory=gerar.PASTA_SAIDA), name="saida")

# O pacote inclui a interface compilada; em desenvolvimento o Vite continua disponível.
_interface = PASTA / "studio" / "web" / "dist"
if _interface.exists():
    app.mount("/", StaticFiles(directory=_interface, html=True), name="interface")
