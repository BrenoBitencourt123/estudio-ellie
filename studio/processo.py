"""Produção conversacional, sem pilares, avaliações ou métricas de rede social."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from studio.cenas_voz import cenas_sugeridas, duracao_total, sincronizar
from studio import conferencia as conf
from studio.dreamina import Dreamina
from studio.montagem import (animar_imagem, montar, montar_previa, montar_sequencia, preparar_referencia, probe,
                             reduzir_previa, sha256, tem_audio)
from studio.producao_store import Store, agora
from studio.planejamento import ajustar_plano, atualizar_direcao, resumir_mudancas
from studio.caderno import Ficha, Referencia, chave, referencias, selecionadas, ficha_atual, revisao

PASTAS = ("persona", "base", "pecas", "cenarios", "movimentos", "saida", "anexos", "quadros", "referencias")
# Destinos de imagem gerada a partir do que o Breno cola no chat
DESTINOS_IMAGEM = ("cenarios", "pecas", "base", "persona", "quadros")
VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO = {".mp3", ".wav", ".m4a", ".ogg"}
# Músicas de fundo do Breno (Epidemic, biblioteca do TikTok etc.). Fica fora da galeria de imagens/vídeos.
PASTA_TRILHAS = "trilhas"

# Faixas de trabalho: cada tipo de operação corre na sua, e só disputa vaga com as do mesmo tipo.
# Assim a conversa nunca espera uma imagem, e uma imagem nunca espera a narração.
#   midia     — imagem do GPT e busca no Pinterest: só criam arquivo novo, podem ir várias juntas
#   voz       — ElevenLabs e sincronização do áudio enviado: uma por vez (escrevem a mesma narração)
#   producao  — cotar, gerar, acompanhar e montar: uma por vez, porque mexem no plano e no dinheiro
#   conversa  — o turno de IA: um por vez, e nunca bloqueado pelas outras faixas
FAIXAS = {"midia": 3, "voz": 1, "producao": 1, "conversa": 1}
FAIXA_OCUPADA = {
    "midia": "Já há três imagens sendo geradas nesta produção. Espere uma terminar.",
    "voz": "A narração já está sendo gerada. Espere ela terminar.",
    "producao": "Esta produção já está cotando, gerando ou montando. Espere essa etapa terminar.",
    "conversa": "Esta conversa já está respondendo. Aguarde a resposta atual.",
}


class Asset(BaseModel):
    pasta: Literal["persona", "base", "pecas", "cenarios", "movimentos", "saida", "anexos", "quadros", "referencias"]
    nome: str = Field(min_length=1, max_length=180, pattern=r"^[^/\\]+$")


class Tomada(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _movimento_so_em_imagens(cls, valor):
        # Movimento local não dirige o Seedance. Um valor "natural"/"none"
        # neste campo irrelevante não deve rejeitar uma tomada de vídeo.
        if (isinstance(valor, dict) and valor.get("tipo", "video") == "video"
                and valor.get('movimento_local') not in ('aproximar', 'afastar', 'subir', 'descer', 'esquerda', 'direita')):
            return {**valor, "movimento_local": "aproximar"}
        return valor

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    titulo: str = Field(min_length=1, max_length=100)
    descricao: str = Field(default='', max_length=800)
    intencao: str = Field(default='', max_length=400)
    fala: str = Field(default='', max_length=800)
    # O que o quadro e a tomada PRECISAM mostrar para a cena funcionar (verificável numa imagem):
    # "Jesus visível na entrada do túmulo", "câmera do lado de fora", "espaço para ele caminhar até a câmera"
    exigencias: list[str] = Field(default_factory=list, max_length=8)
    # cheia: tela inteira. esquerda/direita: só no layout lado_a_lado.
    lado: Literal["esquerda", "direita", "cheia"] = "cheia"
    # None: a modelo aprovada entra se a produção usa a Ellie. False: tomada sem a Ellie (paisagem, objeto, outro assunto).
    ellie: bool | None = None
    # video: gerada no Dreamina (paga). imagem: a primeira imagem ganha movimento de câmera aqui mesmo (grátis).
    tipo: Literal["video", "imagem"] = "video"
    movimento_local: Literal["aproximar", "afastar", "subir", "descer", "esquerda", "direita"] = "aproximar"
    modelo: str = "seedance_2.0_fast"
    modo: Literal["m2v", "first_last_frame"] = "m2v"
    resolucao: Literal["480p", "720p", "1080p"] = "720p"
    # Mínimo/máximo reais da tomada paga vêm do catálogo da CLI (validate); cena de imagem segue a voz
    duracao: int = Field(default=9, ge=1, le=30)
    prompt: str = Field(min_length=10, max_length=14500)

    @field_validator("duracao", mode="before")
    @classmethod
    def _segundos_inteiros(cls, valor):
        """A IA às vezes copia o tempo da frase (6.3 s). A tomada é pedida em segundos inteiros: arredonda
        para cima, para cobrir a frase; o corte da montagem usa o tempo exato."""
        if isinstance(valor, (float, str)):
            try:
                numero = float(valor)
                if math.isfinite(numero):
                    return math.ceil(numero - 1e-6)
            except ValueError:
                pass
        return valor

    @field_validator("exigencias", mode="before")
    @classmethod
    def _exigencias_curtas(cls, valor):
        if isinstance(valor, list):
            return [str(e).strip()[:200] for e in valor if str(e).strip()][:8]
        return valor
    imagens: list[Asset] = Field(default_factory=list, max_length=30)
    movimento: Asset | None = None
    movimento_inicio: float = Field(default=0, ge=0)
    movimento_duracao: float = Field(default=2, ge=2, le=30)
    recorte: list[int] | None = Field(default=None, min_length=4, max_length=4)


class Corte(BaseModel):
    tomada: str
    inicio: float = Field(default=0, ge=0)
    duracao: float = Field(gt=0, le=30)
    recorte: list[int] | None = Field(default=None, min_length=4, max_length=4)
    # < 1: câmera lenta (a tomada estica para cobrir a frase da narração)
    velocidade: float = Field(default=1, ge=0.5, le=2)


class Faixa(BaseModel):
    """Texto fixo na tela (opcional). Campo vazio não é desenhado; altura 0 = sem faixa."""
    altura: int = Field(default=0, ge=0, le=400)
    sobretitulo: str = Field(default="", max_length=45)
    titulo: str = Field(default="", max_length=45)
    destaque: str = Field(default="", max_length=30)
    pergunta: str = Field(default="", max_length=85)
    esquerda: str = Field(default="", max_length=25)
    direita: str = Field(default="", max_length=25)


class Plano(BaseModel):
    # tela_cheia: cortes em sequência na tela inteira. lado_a_lado: tomada contínua à direita + cortes à esquerda.
    layout: Literal["tela_cheia", "lado_a_lado"] = "tela_cheia"
    # Fracionária no narrado: o vídeo dura o tempo da voz, quadro a quadro
    duracao_final: float = Field(default=9, ge=1, le=90)
    tomadas: list[Tomada] = Field(default_factory=list, max_length=12)
    cortes: list[Corte] = Field(default_factory=list, max_length=60)
    faixa: Faixa = Field(default_factory=Faixa)
    legenda: str = Field(default="", max_length=1000)


CAMPOS_PLANO = ("layout", "duracao_final", "tomadas", "cortes", "faixa", "legenda")


class Novo(BaseModel):
    nome: str = Field(default="Novo vídeo", min_length=1, max_length=100)
    # Compatibilidade: "duas_tomadas" só liga a Ellie. O formato do vídeo nasce na conversa, não aqui.
    formato: str | None = Field(default=None, max_length=40)


class Narracao(BaseModel):
    texto: str = Field(default="", max_length=800)
    voz: str = Field(default="", max_length=64)
    setas: bool = True
    # Frase de chamada para ação dentro do texto (as setas entram quando ela começa). Vazio = sem setas.
    cta: str = Field(default="", max_length=200)


class AjustesNarracao(BaseModel):
    """Acabamento da narração: muda só a montagem local, nunca a voz."""
    setas: bool = True
    cta: str = Field(default="", max_length=200)
    estilo_legenda: Literal["karaoke", "elegante"] = "karaoke"
    # Os cortes seguem as frases da voz (áudio primeiro). Desligado: vale o plano como está.
    seguir_voz: bool = True
    trilha: str = Field(default="", max_length=180, pattern=r"^[^/\\]*$")
    volume_trilha: float = Field(default=0.2, ge=0, le=1)
    sfx: bool = False


NARRACAO_VAZIA = {"texto": "", "voz": "", "setas": True, "cta": "", "audio": None, "palavras": [],
                  **AjustesNarracao().model_dump(exclude={"setas", "cta"})}
# Movimento neutro para quando uma imagem vira quadro inicial antes de a conversa descrever a cena
PROMPT_QUADRO = ("Animate the attached first frame as one continuous vertical 9:16 shot with subtle, natural motion. "
                 "No text, no captions, no cuts.")


def layout_de(p: dict) -> str:
    """Produções antigas não têm layout: o formato da Ellie era lado a lado; o narrado, tela cheia."""
    if p.get("layout"):
        return p["layout"]
    return "lado_a_lado" if p.get("formato", "duas_tomadas") == "duas_tomadas" and p.get("tomadas") else "tela_cheia"


def audio_pela_narracao(p: dict) -> dict:
    """Roteiro de voz escrito é uma decisão de áudio: com a ficha ainda indefinida, ela passa a ser narração."""
    ficha = p.get("ficha") or {}
    if ficha.get("audio", "indefinido") == "indefinido" and ((p.get("narracao") or {}).get("texto") or "").strip():
        return {**p, "ficha": {**Ficha(**ficha).model_dump(), "audio": "narracao"}}
    return p


def pronta(s: dict) -> bool:
    """Pronta para montar: arquivo baixado, ou cena de imagem (o movimento é feito na própria montagem)."""
    return bool(s.get("arquivo")) or (s.get("tipo") == "imagem" and bool(s.get("imagens")))


def paga(s: dict) -> bool:
    """Só as tomadas de vídeo passam pelo Dreamina; cena de imagem não tem cotação nem crédito."""
    return s.get("tipo", "video") != "imagem"


def resumo_producao(p: dict) -> dict:
    """O essencial de uma produção para a IA não repetir ideia, texto, cena nem CTA."""
    n = p.get("narracao") or {}
    f = p.get("faixa") or {}
    item = {"nome": p.get("nome", ""), "criado": p.get("criado", "")[:10], "layout": layout_de(p),
            "ellie": bool(p.get("master")), "status": p.get("status", "")}
    if n.get("texto"):
        item["narracao"] = n["texto"][:220]
    if n.get("cta"):
        item["cta"] = n["cta"]
    texto_tela = " ".join(v for v in (f.get("titulo"), f.get("destaque"), f.get("pergunta")) if v)
    if texto_tela:
        item["texto_tela"] = texto_tela[:120]
    if p.get("legenda"):
        item["legenda"] = p["legenda"][:120]
    item["cenas"] = [f"{s.get('titulo', '')}: {s.get('prompt', '')[:140]}" for s in p.get("tomadas", [])][:4]
    return item


class SalvarPlano(BaseModel):
    versao: int
    plano: Plano


class Selecao(BaseModel):
    papel: Literal["movimento", "master", "estado", "bruto"]
    asset: Asset
    tomada: str = ""


class Mensagem(BaseModel):
    texto: str = Field(default="", max_length=6000)
    selecao: Selecao | None = None
    # Imagens coladas (Ctrl+V) e já enviadas para a pasta anexos
    anexos: list[Asset] = Field(default_factory=list, max_length=4)


class Descartar(BaseModel):
    asset: Asset


# ---------------------------------------------------------------------------
# Roteador local: decide o que fazer com imagens coladas SEM gastar uma chamada de IA.
# Só quando a intenção fica ambígua a conversa vai para o modelo.
# ---------------------------------------------------------------------------
def _sem_acento(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


OPCOES_IMAGEM_LIVRE = {
    "Usar como quadro inicial": "usar_quadro",
    "Recriar como quadro (GPT)": "quadros",
    "Criar cenário a partir dela": "cenarios",
    "Só guardar na biblioteca": "guardar",
}
OPCOES_IMAGEM_ELLIE = {
    "Usar como quadro inicial": "usar_quadro",
    "Criar cenário a partir dela": "cenarios",
    "Recriar a roupa": "pecas",
    "Ellie usando essa roupa": "base",
    "Só guardar na biblioteca": "guardar",
}
_PADROES_INTENCAO = (
    ("guardar", r"^(so |apenas )?(guarda|guardar|salva|salvar)\b|so guardar"),
    ("usar_quadro", r"usar? (ela |essa |esta )?como quadro|como quadro inicial|essa (mesma )?imagem mesmo"),
    ("quadros", r"quadro|frame|primeira imagem|cena inicial"),
    ("base", r"ellie (com|usando|vestindo)|ela (com|usando|vestindo)|com essa roupa|vestida"),
    ("cenarios", r"cenario|fundo|lugar|ambiente|locacao|background|quarto|sala|rua|provador"),
    ("pecas", r"roupa|peca|look|outfit|vestido|saia|blusa|camisa|calca|bota|sapato|bolsa|colete|casaco"),
)
# "busca no pinterest jesus na tempestade", "pinterest: god light clouds"
_PADRAO_PINTEREST = r"^(?:(?:busca|buscar|busque|pesquisa|pesquisar|pesquise|procura|procurar|procure)\s+(?:no\s+|na\s+)?pinterest|pinterest)\s*[:,-]?\s+(.+)$"
_PADRAO_VARIACAO = r"outra (versao|opcao|variacao)|de novo|refaz|refazer|variacao|gera outra|mais uma"


def intencao_imagem(texto: str) -> str | None:
    """Intenção para imagens coladas: pasta de destino, 'guardar' ou None (ambíguo)."""
    for opcoes in (OPCOES_IMAGEM_ELLIE, OPCOES_IMAGEM_LIVRE):
        if texto in opcoes:
            return opcoes[texto]
    limpo = _sem_acento(texto.strip())
    for destino, padrao in _PADROES_INTENCAO:
        if re.search(padrao, limpo):
            return destino
    return None


def termo_pinterest(texto: str) -> str | None:
    achado = re.match(_PADRAO_PINTEREST, texto.strip(), re.I | re.S)
    return achado.group(1).strip().strip('"“”') if achado else None


def pede_variacao(texto: str) -> bool:
    return bool(re.search(_PADRAO_VARIACAO, _sem_acento(texto.strip())))


def erro_legivel(e: Exception) -> str:
    """Erro de validação vira uma linha por campo, sem o link da documentação do pydantic."""
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
    return str(e)[:400]


class Gerar(BaseModel):
    cotacao_id: str
    teto: int = Field(gt=0)


class Cotar(BaseModel):
    tomadas: list[str] | None = None


class UsarImagem(BaseModel):
    asset: Asset
    como: Literal["quadro", "recriar"]
    cena: str | None = None


class SalvarCaderno(BaseModel):
    versao: int
    ficha: Ficha
    referencias: list[Referencia] = Field(default_factory=list, max_length=48)


class RevisarStoryboard(BaseModel):
    assinatura: str


class AtivarReferencia(BaseModel):
    """Liga/desliga uma referência no caderno, com o papel que ela cumpre (luz, composição...)."""
    asset: Asset
    ativa: bool = True
    papel: Literal['inspiracao', 'luz', 'composicao', 'personagem', 'cenario', 'roupa', 'movimento'] = 'inspiracao'
    orientacao: str = Field(default='', max_length=600)


class AceitarConferencia(BaseModel):
    """Usar mesmo assim: decisão consciente do Breno sobre um quadro ou tomada reprovada/não conferida."""
    material: Literal["quadro", "video"] = "quadro"


class Reuso(BaseModel):
    tomada: str
    asset: Asset


def nova_tomada(id: str, lado: str, title: str, prompt: str) -> dict:
    return Tomada(id=id, lado=lado, titulo=title, prompt=prompt).model_dump()


def plano_exemplo_ellie() -> dict:
    """Só o histórico do piloto verão/outono (usado em testes). Produção nova NÃO começa daqui."""
    common = ("Use the attached approved woman as the exact identity, long dark wavy hair, athletic hips and muscular thighs. "
              "Preserve the fitting room, natural light and clothing details. Full body centred within the middle 45 percent, "
              "head and shoes visible. A fixed camera, grounded feet and natural weight shifts. No text, split screen, speech or audio. ")
    summer = nova_tomada("verao", "direita", "Verão contínuo", common +
        "One continuous 9-second summer outfit shot: navy open-collar shirt with rolled sleeves, ivory skirt, cognac bag and trainers. "
        "0–2s breathe and release the free hand from the pocket. 2–4s shift support and move one foot a few centimetres. "
        "4–6s glance briefly towards her right then return to camera. 6–9s rest the free hand near the belt and settle into another relaxed stance.")
    autumn = nova_tomada("outono", "esquerda", "Transformação de outono", common +
        "A 9-second styling montage of the SAME woman. Images define clothing states, movement video defines gestures only. "
        "0–1.2s close the navy collar and lower sleeves. 1.2–3s show the cream vest by its shoulders, lift it towards the torso, "
        "then use a hard editorial cut to the vest worn and settle its hem. 3–4.8s present brown tights, cut to tights worn, "
        "bend to adjust and rise. 4.8–6.5s show both brown knee boots, cut to boots worn, bend to adjust one shaft and rise. "
        "6.5–9s present the cognac handbag, lower it into one hand, brush hair once and finish in a new balanced stance. "
        "Each clothing change occurs only at a hard cut, never as a morph. The bag is on the stool until its presentation. "
        "Keep the same bag, boots, body proportions, skirt, room and light. Do not freeze the photographic pose.")
    return Plano(layout="lado_a_lado", tomadas=[Tomada(**summer), Tomada(**autumn)],
                 cortes=[Corte(tomada="outono", duracao=9)]).model_dump()


class Processo:
    def __init__(self, root: Path, ask, cli=None, store=None, imagem=None, conversar=None, pinterest=None):
        self.root = root.resolve()
        self.store = store or Store(root / "studio" / "dados" / "producoes.sqlite3")
        self.ask = ask
        # imagem(pasta, descricao, nome, referencias: list[Path], usar_ellie: bool) -> nome do arquivo gerado
        self.imagem = imagem
        # conversar(pedido: dict, ao_delta) -> {"texto","modelo","modo","usage","segundos","tentativas"}
        self.conversar_ia = conversar
        if pinterest is None:
            from studio.referencias import buscar_e_baixar
            pinterest = lambda termo, destino, qtd: buscar_e_baixar(termo, destino, qtd)
        self.pinterest = pinterest
        self.rascunhos: dict[str, str] = {}
        self.cli = cli or Dreamina()
        self.lock = threading.RLock()
        # produção -> {id do trabalho: {"faixa", "rotulo", "iniciado"}}. Substitui o antigo cadeado único.
        self.trabalhos: dict[str, dict[str, dict]] = {}
        self.chatting: dict[str, int] = {}
        self.migrar()
        example_file = root / "exemplos" / "producao-v7.json"
        if example_file.exists():
            example = json.loads(example_file.read_text(encoding="utf-8"))
            try:
                self.store.get(example["id"])
            except ValueError:
                self.store.create(example)

    def migrar(self) -> None:
        """Produções de antes do layout livre: grava o layout e tira do narrado a faixa verão/outono que ele herdava
        (o narrado antigo nunca desenhava a faixa)."""
        for p in self.store.list():
            antes = (p.get("layout"), (p.get("ficha") or {}).get("audio"))
            if not p.get("layout"):
                p["layout"] = layout_de(p)
                if p.get("formato") == "narrado":
                    p["faixa"] = Faixa().model_dump()
            p = audio_pela_narracao(p)
            if (p.get("layout"), (p.get("ficha") or {}).get("audio")) == antes:
                continue
            try:
                self.store.save(p)
            except ValueError:
                pass

    def asset(self, value: dict) -> Path:
        item = Asset(**value)
        root = (self.root / item.pasta).resolve()
        path = (root / item.nome).resolve()
        if path.parent != root or not path.is_file() or path.suffix.lower() not in VIDEO | IMAGEM:
            raise ValueError("Referência não encontrada na biblioteca: " + item.nome)
        return path

    def library(self) -> dict:
        return {p: sorted(f.name for f in (self.root / p).iterdir() if f.is_file() and f.suffix.lower() in VIDEO | IMAGEM)
                if (self.root / p).exists() else [] for p in PASTAS}

    def trilhas(self) -> list[str]:
        pasta = self.root / PASTA_TRILHAS
        return sorted(f.name for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in AUDIO) if pasta.exists() else []

    def trilha(self, nome: str) -> Path | None:
        if not nome:
            return None
        if nome not in self.trilhas():
            raise ValueError("Trilha não encontrada na pasta trilhas: " + nome)
        return self.root / PASTA_TRILHAS / nome

    # ---------------- Áudio primeiro: a voz decide os cortes ----------------
    def duracao_voz(self, p: dict) -> float:
        from studio.narracao import duracao_audio
        n = p.get("narracao") or {}
        caminho = self.output(p["id"]) / Path(n.get("audio") or "").name if n.get("audio") else None
        try:
            return duracao_audio(caminho) if caminho and caminho.is_file() else 0.0
        except ValueError:  # arquivo que o ffprobe não lê: vale o tempo das palavras
            return 0.0

    @staticmethod
    def segue_voz(p: dict) -> bool:
        n = p.get("narracao") or {}
        return (layout_de(p) == "tela_cheia" and n.get("seguir_voz", True) and bool(n.get("audio"))
                and bool(n.get("palavras")) and bool(p.get("tomadas")))

    def alinhar_voz(self, p: dict) -> tuple[dict, list[str]]:
        """Cortes da tela cheia na duração das frases da voz (mesma ordem e mesmas tomadas).
        Pode recusar (ValueError) quando uma tomada paga é curta demais para a frase dela."""
        if not self.segue_voz(p):
            return p, []
        cortes = p.get("cortes") or [{"tomada": s["id"], "inicio": 0, "duracao": s["duracao"]} for s in p["tomadas"]]
        novos, total, avisos = sincronizar(cortes, p["tomadas"], p["narracao"]["palavras"], self.duracao_voz(p))
        return {**p, "cortes": novos, "duracao_final": total}, avisos

    def cenas_pela_voz(self, p: dict, duracao_audio: float = 0.0) -> dict:
        """Áudio primeiro: uma cena por frase da voz, já no plano, nomeada pela frase. Cena nova é de imagem
        (grátis); o quadro automático que ainda não foi gerado também vira cena de imagem. Nada enviado ao
        Dreamina ou já baixado é mexido."""
        n = p.get("narracao") or {}
        if layout_de(p) != "tela_cheia" or not n.get("seguir_voz", True) or not n.get("palavras"):
            return p
        frases = cenas_sugeridas(n["palavras"], duracao_audio)
        # A pontuação da voz não deve reconstruir uma sequência já dirigida.
        if any(s.get('descricao') or s.get('intencao') or
               (s.get('prompt') != PROMPT_QUADRO and not s.get('prompt', '').startswith('Scene for the narration line:'))
               for s in p['tomadas']):
            return p
        tomadas = [dict(s) for s in p["tomadas"]]
        livre = lambda s: not s.get("submit_id") and not s.get("arquivo")
        convertida = False
        for s in tomadas:
            if livre(s) and s.get("prompt") == PROMPT_QUADRO and paga(s):
                s["tipo"], convertida = "imagem", True
        novas = False
        for k, frase in enumerate(frases):
            if k >= len(tomadas):
                j = k + 1
                while any(s["id"] == f"frase-{j}" for s in tomadas):
                    j += 1
                tomadas.append(Tomada(id=f"frase-{j}", titulo="Frase", tipo="imagem", duracao=1,
                                      ellie=None if p.get("master") else False,
                                      prompt=f"Scene for the narration line: {frase['texto']}"[:14500]).model_dump())
                novas = True
            s = tomadas[k]
            if livre(s):
                s["titulo"] = f"Frase {k + 1}: {' '.join(frase['texto'].split()[:5])}"[:100]
        p = {**p, "tomadas": tomadas}
        if convertida:
            p["cotacao"] = p["autorizacao"] = None
        if novas or convertida:  # um corte por cena, na ordem; a duração de cada um vem da voz ao alinhar
            p["cortes"] = [{"tomada": s["id"], "inicio": 0, "duracao": s["duracao"], "recorte": None, "velocidade": 1}
                           for s in tomadas]
            p["duracao_final"] = sum(s["duracao"] for s in tomadas)
        return p

    def _alinhar_se_der(self, p: dict) -> dict:
        """Na edição do plano/voz: alinha quando dá; o problema (tomada curta) aparece de novo ao montar."""
        try:
            return self.alinhar_voz(p)[0]
        except ValueError:
            return p

    def tomadas_montaveis(self, p: dict) -> list[dict]:
        """Cenas de imagem viram vídeo aqui, sem créditos, na duração que o corte delas pede.
        O arquivo é reaproveitado enquanto imagem, movimento e duração não mudam."""
        precisa: dict[str, float] = {}
        for c in p.get("cortes") or []:
            precisa[c["tomada"]] = max(precisa.get(c["tomada"], 0.0), float(c.get("inicio") or 0) + float(c["duracao"]))
        saida = []
        for s in p["tomadas"]:
            if paga(s):
                saida.append(s)
                continue
            if not s.get("imagens"):
                raise ValueError(f"A cena \"{s['titulo']}\" não tem imagem: gere ou escolha uma antes de montar.")
            imagem = self.asset(s["imagens"][0])
            duracao = round(precisa.get(s["id"], float(s["duracao"])) + 0.1, 2)  # folga para o corte
            chave = hashlib.sha256(f"{sha256(imagem)}:{s['movimento_local']}:{duracao}".encode()).hexdigest()[:10]
            nome = f"{p['id'][:12]}-{s['id']}-local-{chave}.mp4"
            destino = self.root / "saida" / nome
            info = probe(destino) if destino.exists() else animar_imagem(imagem, destino, duracao, s["movimento_local"])
            saida.append({**s, "arquivo": {"pasta": "saida", "nome": nome}, "info": info})
        return saida

    def output(self, id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,70}", id):
            raise ValueError("Identificador inválido.")
        dest = self.root / "saida" / "producoes" / id
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def create(self, name: str, formato: str | None = None) -> dict:
        """Produção nova começa vazia: formato, cenas, texto e CTA nascem na conversa."""
        master = None
        if formato == "duas_tomadas" and (self.root / "persona" / "ellie-aprovada.png").exists():
            master = {"pasta": "persona", "nome": "ellie-aprovada.png"}
        return self.store.create({"id": uuid.uuid4().hex, "nome": name, "criado": agora(), "status": "conversa",
            **Plano().model_dump(), "master": master, "referencia": None, "mensagens": [], "cotacao": None,
            "autorizacao": None, "imports": {}, "canvas_id": "", "canvas_url": "", "erro": "", "historico_creditos": 0,
            "narracao": dict(NARRACAO_VAZIA), "ficha": Ficha().model_dump(),
            "referencias_criativas": [], "fluxo_dirigido": True})

    def usar_ellie(self, p: dict, ligar: bool) -> dict:
        if ligar and not p.get("master"):
            if not (self.root / "persona" / "ellie-aprovada.png").exists():
                raise ValueError("Não encontrei persona/ellie-aprovada.png.")
            if any(s.get("submit_id") for s in p["tomadas"]):
                raise ValueError("Já há tomadas enviadas; abra outra produção para incluir a Ellie.")
            p["master"] = {"pasta": "persona", "nome": "ellie-aprovada.png"}
            p["cotacao"] = p["autorizacao"] = None
        elif not ligar and p.get("master") and not any(s.get("submit_id") for s in p["tomadas"]):
            p["master"] = None
            p["cotacao"] = p["autorizacao"] = None
        return p

    def historico(self, excluir: str, limite: int = 12) -> list[dict]:
        return [resumo_producao(p) for p in self.store.list() if p["id"] != excluir and not p.get("exemplo")][:limite]

    def generation_hash(self, p: dict) -> str:
        payload = []
        for shot in filter(paga, p["tomadas"]):  # cena de imagem não entra no que foi cotado
            data = Tomada(**shot).model_dump(exclude={"recorte", "descricao", "intencao", "fala"})
            data["conteudo_referencias"] = [sha256(self.asset(a)) for a in shot["imagens"]]
            if shot.get("movimento"):
                data["conteudo_movimento"] = sha256(self.asset(shot["movimento"]))
            payload.append(data)
        if p.get("master"):
            payload.append({"master_sha256": sha256(self.asset(p["master"]))})
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def save_plan(self, p: dict, plan: dict, expected: int) -> dict:
        # Só a faixa de produção impede: cotação, geração paga, acompanhamento e montagem dependem deste plano.
        # Imagem, Pinterest e narração correm em paralelo e não têm por que travar uma edição de estrutura.
        self.exigir_livre(p["id"])
        p = copy.deepcopy(p)  # uma validação recusada não altera o registro do chamador
        base = {k: p.get(k) for k in CAMPOS_PLANO}  # o plano como quem chamou leu, para detectar conflito real
        plan = copy.deepcopy(plan)
        if not plan.get("layout"):
            plan["layout"] = layout_de(p)
        validated = Plano(**plan).model_dump()
        ids = [s["id"] for s in validated["tomadas"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Use identificadores únicos para as tomadas.")
        if validated["layout"] == "lado_a_lado" and ids:
            lados = [s["lado"] for s in validated["tomadas"]]
            if lados.count("direita") != 1 or "esquerda" not in lados:
                raise ValueError("Lado a lado precisa de uma tomada contínua à direita e pelo menos uma à esquerda.")
            esquerda = {s["id"] for s in validated["tomadas"] if s["lado"] == "esquerda"}
            if any(c["tomada"] not in esquerda for c in validated["cortes"]):
                raise ValueError("No lado a lado, os cortes usam só tomadas da esquerda (a direita é contínua).")
        elif ids and not validated["cortes"]:
            # Tela cheia sem cortes: cada tomada inteira, na ordem
            validated["cortes"] = [{"tomada": s["id"], "inicio": 0, "duracao": s["duracao"], "recorte": None}
                                   for s in validated["tomadas"]]
            validated["duracao_final"] = sum(s["duracao"] for s in validated["tomadas"])
        if any(c["tomada"] not in ids for c in validated["cortes"]):
            raise ValueError("Um corte aponta para uma tomada inexistente.")
        if ids and sum(round(c["duracao"] * 30) for c in validated["cortes"]) != round(validated["duracao_final"] * 30):
            raise ValueError("Os cortes precisam preencher a duração final.")
        old = {s["id"]: s for s in p["tomadas"]}
        fields = set(Tomada.model_fields) - {"recorte", "titulo", "descricao", "intencao", "fala"}
        changed = set(old) != set(ids)
        for shot in validated["tomadas"]:
            prior = old.get(shot["id"], {})
            same = all(prior.get(k) == shot.get(k) for k in fields)
            if not same and prior.get("submit_id"):
                raise ValueError("Uma tomada já enviada não será gerada de novo automaticamente. Crie outra produção para testar outra direção.")
            changed |= not same
            if same:
                shot.update({k: v for k, v in prior.items() if k not in Tomada.model_fields})
        if changed:
            if any(s.get("submit_id") for s in p["tomadas"] if s["id"] not in ids):
                raise ValueError("Não remova tomadas enviadas: elas guardam a identidade e o custo da geração.")
            p["cotacao"] = p["autorizacao"] = None
        elif any(old.get(s['id'], {}).get('titulo') != s['titulo'] for s in validated['tomadas']):
            # O título faz parte do fingerprint da cotação. Conserva os arquivos,
            # mas não exibe como utilizável uma cotação com outro fingerprint.
            p['cotacao'] = p['autorizacao'] = None
        def montagem(plano):
            estado = Plano(**plano).model_dump(exclude={'legenda'})
            estado['tomadas'] = [{k: s.get(k) for k in Tomada.model_fields if k not in ('titulo', 'descricao', 'intencao', 'fala')}
                                for s in estado['tomadas']]
            return estado
        if montagem(p) != montagem(validated):
            # O arquivo antigo continua no disco, mas já não representa este plano.
            p.pop("resultado", None)
        p.update(validated)
        p['erro'] = ''
        p = self._alinhar_se_der(p)  # com a voz pronta, os cortes seguem as frases dela
        def aplicar(atual: dict) -> dict:
            # Conflito é o PLANO ter mudado, não a conversa ter escrito: uma imagem pronta no meio da
            # edição não invalida mais a edição.
            if expected is not None and any(atual.get(k) != base.get(k) for k in CAMPOS_PLANO):
                raise ValueError("A produção mudou em outra janela. Recarregue antes de salvar.")
            return {**p, "mensagens": atual["mensagens"]}
        return self.store.update(p["id"], aplicar)

    def message(self, id: str, request: Mensagem) -> dict:
        p = self.store.get(id)
        if request.selecao:
            p = self.select_reference(id, request.selecao)
        text = request.texto.strip() or ("Escolhi " + request.selecao.asset.nome if request.selecao else "")
        anexos = [a.model_dump() for a in request.anexos]
        for a in anexos:
            self.asset(a)  # valida que o arquivo existe na biblioteca
        if not text and not anexos:
            raise ValueError("Escreva sua ideia ou escolha uma referência.")
        user = {"id": uuid.uuid4().hex, "papel": "user", "texto": text, "criado": agora()}
        campos: dict = {}
        if anexos:
            user["anexos"] = anexos
            campos = {"anexos_pendentes": anexos, "anexos_idade": 0}
        elif p.get("anexos_pendentes"):
            # Imagens coladas valem para a mensagem em que foram coladas e a seguinte (resposta a um quiz/pergunta)
            idade = p.get("anexos_idade", 0) + 1
            campos = {"anexos_idade": idade, "anexos_pendentes": [] if idade >= 2 else p["anexos_pendentes"]}
        def adicionar(atual):
            refs = {r['id']: r for r in referencias(atual)}
            for a in anexos:
                if chave(a) not in refs:
                    refs[chave(a)] = Referencia(id=chave(a), asset=a, ativa=sum(r['ativa'] for r in refs.values()) < 12).model_dump()
            return {**atual, **campos, 'referencias_criativas': list(refs.values()), 'mensagens': atual['mensagens'] + [user]}
        p = self.store.update(id, adicionar)
        rapido = self.rota_rapida(p, text, bool(anexos))
        if rapido is not None:
            return rapido
        return self.turno_ia(p)

    # ------------------------------------------------------------------
    # Turno de IA (Fase 2): sessão contínua por produção, só o que mudou, modelo com reserva, texto ao vivo
    # ------------------------------------------------------------------
    @staticmethod
    def _hash(valor) -> str:
        return hashlib.sha256(json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]

    @staticmethod
    def resumo_mensagens(mensagens: list[dict]) -> list[dict]:
        """Histórico enxuto para a IA: texto, anexos e o tipo dos cartões (sem listas de arquivos repetidas)."""
        saida = []
        for m in mensagens:
            item = {"papel": m["papel"], "texto": m.get("texto", "")}
            if m.get("anexos"):
                item["anexos"] = [a["nome"] for a in m["anexos"]]
            if m.get("blocos"):
                item["cartoes"] = [b.get("tipo") + (f":{','.join(b.get('nomes') or [])}" if b.get("tipo") == "imagem" else "")
                                   for b in m["blocos"]]
            saida.append(item)
        return saida

    def _contexto(self, p: dict) -> tuple[dict, list[Path]]:
        context = {k: p.get(k) for k in ["nome", "master", "referencia", "duracao_final", "tomadas", "cortes", "faixa", "legenda", "cotacao", "status"]}
        context["layout"] = layout_de(p)
        context['direcao'] = p.get('direcao') or {}
        context['ficha_producao'] = ficha_atual(p)
        context['revisao_storyboard'] = revisao(p)
        context["usa_ellie"] = bool(p.get("master"))
        context["ellie_disponivel"] = (self.root / "persona" / "ellie-aprovada.png").exists()
        n = p.get("narracao") or {}
        narr = {"texto": n.get("texto", ""), "cta": n.get("cta", ""), "audio_pronto": bool(n.get("audio")),
                "setas": n.get("setas", True), "estilo_legenda": n.get("estilo_legenda", "karaoke"),
                "trilha": n.get("trilha", ""), "sfx": n.get("sfx", False), "seguir_voz": n.get("seguir_voz", True)}
        if n.get("audio") and n.get("palavras"):
            # Áudio primeiro: a IA planeja uma cena por frase, já sabendo quanto tempo cada uma dura
            duracao = self.duracao_voz(p)
            narr["duracao_voz"] = round(duracao_total(n["palavras"], duracao), 2)
            narr["frases"] = cenas_sugeridas(n["palavras"], duracao)
        context["narracao"] = narr
        context["trilhas_disponiveis"] = self.trilhas()
        photos: list[Path] = []
        visuais = []
        for r in selecionadas(p):
            if not self._existe(r['asset']):
                visuais.append({**r, 'indisponivel': True})
                continue
            path = self.asset(r['asset'])
            if path.suffix.lower() in IMAGEM:
                if path not in photos:
                    photos.append(path)
                visuais.append({**r, 'imagem_anexada': photos.index(path) + 1})
        context['referencias_visuais'] = visuais
        # Resultado da última busca, ainda fora do caderno: uma folha numerada para a IA dizer o que serve e para quê
        candidatas = [r for r in referencias(p) if not r['ativa'] and r['asset']['pasta'] == 'referencias'
                      and r.get('orientacao', '').startswith('Busca:') and self._existe(r['asset'])][-8:]
        if candidatas:
            from studio.assistente import montar_folha
            folha = self.output(p['id']) / 'referencias-candidatas.jpg'
            marca, arquivo_marca = json.dumps([r['asset']['nome'] for r in candidatas]), folha.with_suffix('.json')
            # refaz só quando a busca muda: a folha reescrita seria reenviada à IA a cada turno
            if not folha.exists() or not arquivo_marca.exists() or arquivo_marca.read_text(encoding='utf-8') != marca:
                montar_folha([self.asset(r['asset']) for r in candidatas], folha, colunas=4, celula=240, numerar=True)
                arquivo_marca.write_text(marca, encoding='utf-8')
            photos.append(folha)
            context['referencias_candidatas'] = {
                'imagem_anexada': len(photos), 'como_ler': 'folha numerada; número N = item N desta lista',
                'itens': [{'numero': i + 1, 'nome': r['asset']['nome'], 'busca': r['orientacao']} for i, r in enumerate(candidatas)]}
        # Todos os quadros atuais também entram na visão, não apenas como nomes de arquivo.
        for s in p.get('tomadas', []):
            for a in s.get('imagens', []):
                if not self._existe(a):
                    continue
                path = self.asset(a)
                if path not in photos:
                    photos.append(path)
        context['ordem_imagens'] = [str(f.relative_to(self.root)) for f in photos]
        if p.get("master"):
            photos.append(self.asset(p["master"]))
        if p.get("referencia"):
            # Reaproveita o extrator de quadros; refaz a folha só quando a referência muda (ffmpeg é lento).
            source = self.asset(p["referencia"])
            sheet = self.output(p["id"]) / "referencia-quadros.jpg"
            marca = f"{p['referencia']['nome']}:{source.stat().st_size}:{int(source.stat().st_mtime)}"
            if not sheet.exists() or p.get("referencia_folha") != marca:
                from studio.assistente import frames_do_video, montar_folha
                meta = probe(source)
                frames = frames_do_video(source, 0, min(30, meta["duracao"]), quantidade=12)
                montar_folha(frames, sheet, colunas=4, celula=240, numerar=True)
                p["referencia_folha"] = marca
                p["referencia_duracao"] = meta["duracao"]
            photos.append(sheet)
            context["referencia_duracao"] = p.get("referencia_duracao")
        if p.get("anexos_pendentes"):
            context["anexos_colados"] = p["anexos_pendentes"]
        return context, photos

    def salvar_plano_da_ia(self, p: dict, proposta: dict, contexto: dict) -> dict:
        """Preserva anexos que chegaram durante a resposta e tenta reparar o contrato uma vez.

        O reparo só propõe dados: nunca executa ações, aprova créditos ou gera mídia.
        """
        from studio.assistente import extrair_json

        def preparar(proposta):
            plano = {k: copy.deepcopy(p.get(k)) for k in CAMPOS_PLANO}
            plano.update(copy.deepcopy(proposta))
            antes = {s['id']: s for s in contexto.get('tomadas') or []}
            atuais = {s['id']: s for s in p['tomadas']}
            cenas = []
            for cena in plano.get('tomadas') or []:
                anterior = antes.get(cena.get('id'), {})
                atual = atuais.get(cena.get('id'), {})
                nova = {**{k: v for k, v in atual.items() if k in Tomada.model_fields}, **cena}
                # A IA ainda não viu o quadro que terminou enquanto ela respondia.
                if atual.get('imagens') != anterior.get('imagens') and cena.get('imagens', []) == anterior.get('imagens', []):
                    nova['imagens'] = copy.deepcopy(atual.get('imagens', []))
                cenas.append(nova)
            plano['tomadas'] = cenas
            return plano

        anteriores = {s['id']: s for s in p['tomadas']}
        trocadas = [s for s in proposta.get('tomadas', []) if s.get('tipo') == 'imagem'
                    and anteriores.get(s.get('id'), {}).get('tipo', 'video') == 'video'
                    and s.get('id') in anteriores]
        ultima = next((m.get('texto', '') for m in reversed(p['mensagens']) if m['papel'] == 'user'), '')
        texto_pedido = _sem_acento(ultima)
        escolhas = re.finditer(r'\b(usar|use|trocar|troque|transformar|converter|prefiro|quero|pode|fazer|faz)\b[^.!?;,\n]{0,55}'
                               r'(imagem animada|imagens animadas|imagem com (zoom|movimento)|imagens com (zoom|movimento)|so imagens)',
                               texto_pedido)
        escolha_imagem = any(not re.search(r'\b(nao|nunca|nem|evite|sem)(?:\s+\w+){0,3}\s*$',
                                          texto_pedido[max(0, m.start() - 35):m.start()]) for m in escolhas)
        if trocadas and not escolha_imagem:
            raise ValueError('A proposta trocava vídeo gerado por imagem com movimento de câmera. '
                             'Mantive o vídeo; escolha essa alternativa explicitamente se quiser mudar.')
        try:
            return self.save_plan(p, preparar(proposta), p['versao'])
        except ValueError as primeiro:
            self.store.event(p['id'], 'plano_reparo', {'erro': erro_legivel(primeiro)})
            pedido = ('Corrija somente os dados inválidos deste plano de vídeo. Retorne JSON com "plano" completo. '
                      'Não execute ferramentas nem ações. Preserve IDs, tipo de cena (video/imagem), imagens, '
                      'prompts, intenção e duração solicitada. Movimento_local só vale para imagem e aceita '
                      'aproximar, afastar, subir, descer, esquerda, direita. Duração bruta é inteira de 1 a 30. '
                      'Os cortes devem preencher a duração final.\nERRO: ' + erro_legivel(primeiro)
                      + '\nPLANO PROPOSTO:\n' + json.dumps(preparar(proposta), ensure_ascii=False))
            try:
                if self.conversar_ia:
                    r = self.conversar_ia({'sessao': f"reparo-{p['id'][:24]}-{uuid.uuid4().hex[:8]}",
                                          'completo': pedido, 'delta': None, 'imagensCompleto': [],
                                          'imagensDelta': [], 'modeloAnterior': None}, lambda *_: None)
                    corrigido = extrair_json(r['texto']).get('plano')
                else:
                    corrigido = extrair_json(self.ask(pedido, [])).get('plano')
                if not isinstance(corrigido, dict):
                    raise ValueError('O reparo não devolveu um plano.')
                tipos = {s['id']: s.get('tipo', 'video') for s in preparar(proposta)['tomadas']}
                if {s['id']: s.get('tipo', 'video') for s in corrigido.get('tomadas', [])} != tipos:
                    raise ValueError('O reparo mudou o tipo ou a identidade das cenas.')
                atualizado = self.store.get(p['id'])
                if any(atualizado.get(k) != p.get(k) for k in CAMPOS_PLANO):
                    raise ValueError('O plano mudou durante o reparo. Revise a estrutura atual.')
                return self.save_plan(atualizado, preparar(corrigido), atualizado['versao'])
            except Exception as reparo:
                self.store.event(p['id'], 'plano_rejeitado', {'erro': erro_legivel(reparo)})
                raise ValueError(erro_legivel(primeiro)) from reparo

    def turno_ia(self, p: dict) -> dict:
        id = p["id"]
        context, fotos = self._contexto(p)
        # _contexto pode ter refeito a folha de quadros; isso só existe no dicionário local até gravar
        folha = {k: p[k] for k in ("referencia_folha", "referencia_duracao") if k in p}
        library = self.library()
        instruction = (self.root / "studio" / "processo-prompt.md").read_text(encoding="utf-8")
        anexos = [self.asset(a) for a in p.get("anexos_pendentes") or []]
        user = p["mensagens"][-1]
        ia = p.get("ia_sessao") or {}
        h = {"instr": self._hash(instruction), "estado": self._hash(context), "lib": self._hash(library),
             "fotos": self._hash([str(f) + str(f.stat().st_mtime) for f in fotos])}
        geracao = ia.get("geracao", 0)
        if not ia or ia.get("h_instr") != h["instr"]:
            geracao += 1  # contrato novo (ou primeira vez): sessão nova no OpenClaw
            ia = {}
        completo = (instruction + "\n\nESTADO REAL:\n" + json.dumps(context, ensure_ascii=False)
                    + "\nBIBLIOTECA REAL:\n" + json.dumps(library, ensure_ascii=False)
                    + "\nPRODUÇÕES ANTERIORES (mais recentes primeiro; use para NÃO repetir ideia, texto, cena nem CTA):\n"
                    + json.dumps(self.historico(id), ensure_ascii=False)
                    + "\nCONVERSA RECENTE:\n" + json.dumps(self.resumo_mensagens(p["mensagens"][-14:]), ensure_ascii=False))
        delta = None
        imagens_delta: list[Path] = []
        if ia.get("modelo"):
            ids = [m["id"] for m in p["mensagens"]]
            desde = ids.index(ia["ultima_msg"]) + 1 if ia.get("ultima_msg") in ids else max(0, len(ids) - 6)
            entre = p["mensagens"][desde:-1]
            partes = []
            if entre:
                partes.append("NO APLICATIVO, DESDE A SUA ÚLTIMA RESPOSTA:\n" + json.dumps(self.resumo_mensagens(entre), ensure_ascii=False))
            if ia.get("h_estado") != h["estado"]:
                partes.append("ESTADO ATUALIZADO:\n" + json.dumps(context, ensure_ascii=False))
            if ia.get("h_lib") != h["lib"]:
                partes.append("BIBLIOTECA ATUALIZADA:\n" + json.dumps(library, ensure_ascii=False))
            if ia.get("h_fotos") != h["fotos"]:
                imagens_delta += fotos
                partes.append("Imagens de referência atualizadas anexadas (modelo aprovada e/ou folha de quadros).")
            novos = [a for a, d in zip(anexos, p.get("anexos_pendentes") or []) if d["nome"] not in ia.get("anexos", [])]
            if novos:
                imagens_delta += novos
                partes.append(f"{len(novos)} imagem(ns) colada(s) pelo Breno anexada(s) a esta mensagem.")
            partes.append("MENSAGEM DO BRENO:\n" + json.dumps(self.resumo_mensagens([user])[0], ensure_ascii=False))
            partes.append("Responda no mesmo contrato JSON (mensagem_pt primeiro).")
            delta = "\n\n".join(partes)
        sessao = f"prod-{id[:32]}-g{geracao}"
        etapa = "openclaw"  # depois que a IA responde, um erro é do aplicativo, não da conexão
        try:
            from studio.assistente import extrair_json
            if self.conversar_ia:
                self.rascunhos[id] = ""
                r = self.conversar_ia({"sessao": sessao, "completo": completo, "delta": delta,
                                       "imagensCompleto": [str(f) for f in fotos + anexos],
                                       "imagensDelta": [str(f) for f in imagens_delta],
                                       "modeloAnterior": ia.get("modelo") if ia.get("geracao") == geracao else None},
                                      lambda texto, substituir: self._ao_delta(id, texto, substituir))
                bruto, meta = r["texto"], {k: r.get(k) for k in ("modelo", "modo", "segundos", "usage")}
                meta["tentativas"] = len(r.get("tentativas") or [])
            else:  # modo antigo (sem sessão contínua)
                bruto, meta = self.ask(completo, fotos + anexos), {"modo": "completo"}
            meta["caracteres"] = len(delta if meta.get("modo") == "delta" else completo)
            etapa = "aplicar"
            # A resposta levou de 30 s a 10 min. Nesse tempo uma imagem ou a narração podem ter ficado
            # prontas e escrito aqui: relê antes de aplicar, senão o turno apaga o que elas gravaram.
            p = {**self.store.get(id), **folha}
            response = extrair_json(bruto)
            message = str(response.get("mensagem_pt", "")).strip()
            if not message:
                raise ValueError("O OpenClaw não retornou uma mensagem.")
            antes_da_resposta = copy.deepcopy(p)
            nova_direcao = atualizar_direcao(p.get('direcao'), response['direcao']) if isinstance(response.get('direcao'), dict) else None
            if isinstance(response.get("ellie"), bool):
                p = self._gravar(self.usar_ellie(p, response["ellie"]))
            erro_plano = ""
            if response.get("plano") or response.get('ajustes'):
                try:
                    if response.get('plano') and response.get('ajustes'):
                        raise ValueError('Envie o plano inicial ou os ajustes pontuais, não os dois juntos.')
                    proposta = ajustar_plano(p, response['ajustes'], set(Tomada.model_fields)) if response.get('ajustes') else response['plano']
                    p = self.salvar_plano_da_ia(p, proposta, context)
                except ValueError as e:
                    erro_plano = erro_legivel(e)
                    message = ("Não apliquei a mudança de estrutura. O plano anterior está salvo. "
                               "Nenhuma nova geração foi iniciada por esta resposta.\n"
                               + erro_plano)
                    response['acao'] = None
                    response['blocos'] = [{'tipo': 'plano', 'titulo': 'Revisar estrutura'}]
            if nova_direcao is not None and not erro_plano:
                p['direcao'] = nova_direcao
            if not erro_plano and isinstance(response.get('caderno'), dict):
                try:
                    p = self.caderno_da_ia(p, response['caderno'])
                except (ValueError, ValidationError) as e:
                    message += f"\n\n(Não atualizei o caderno: {erro_legivel(e)}.)"
            texto_mudou = False
            if not erro_plano and isinstance(response.get("narracao"), dict):
                pedido_n = response["narracao"]
                atual_n = {**NARRACAO_VAZIA, **(p.get("narracao") or {})}
                if "cta" in pedido_n:
                    atual_n["cta"] = str(pedido_n.get("cta") or "")[:200]
                if pedido_n.get("estilo_legenda") in ("karaoke", "elegante"):
                    atual_n["estilo_legenda"] = pedido_n["estilo_legenda"]
                if isinstance(pedido_n.get("sfx"), bool):
                    atual_n["sfx"] = pedido_n["sfx"]
                if "trilha" in pedido_n and (not pedido_n["trilha"] or pedido_n["trilha"] in self.trilhas()):
                    atual_n["trilha"] = str(pedido_n["trilha"] or "")
                if "texto" in pedido_n:
                    novo = str(pedido_n.get("texto") or "")[:800]
                    if novo != atual_n.get("texto"):
                        texto_mudou = True
                        p.pop('resultado', None)
                        # Texto novo invalida o áudio antigo (a voz é gerada só pelo botão, que usa créditos do ElevenLabs)
                        atual_n.update(texto=novo, audio=None, palavras=[])
                p["narracao"] = atual_n
                p = audio_pela_narracao(p)
            cards = self.cards(response.get("blocos", []), library)
            if not erro_plano and nova_direcao and not p['tomadas'] and not any(c['tipo'] == 'direcao' for c in cards):
                cards.insert(0, {'tipo': 'direcao', 'titulo': 'Direção do vídeo'})
            if not erro_plano and (response.get('plano') or response.get('ajustes')) and not any(c['tipo'] == 'plano' for c in cards):
                cards.insert(0, {'tipo': 'plano', 'titulo': 'Sequência de cenas'})
            # Narrado: o cartão da narração só aparece quando o texto muda (ou quando ainda não há áudio e ela fala do texto)
            sem_audio = not (p.get("narracao") or {}).get("audio")
            if texto_mudou and (p.get("narracao") or {}).get("texto"):
                if not any(c.get("tipo") == "narracao" for c in cards):
                    cards.insert(0, {"tipo": "narracao", "titulo": "Texto da narração"})
            elif not (sem_audio and re.search(r"narra[çc][ãa]o|roteiro", message, re.I)):
                cards = [c for c in cards if c.get("tipo") != "narracao"]
            resposta = {"id": uuid.uuid4().hex, "papel": "assistant", "texto": message, "blocos": cards,
                        "criado": agora(), "ia": meta,
                        'mudancas': resumir_mudancas(antes_da_resposta, p) if not erro_plano else []}
            p["erro"] = erro_plano
            # O que a IA já viu: o estado DEPOIS da resposta dela (o plano que ela mesma propôs não precisa voltar)
            depois, _ = self._contexto(p)
            p["ia_sessao"] = {"geracao": geracao, "modelo": meta.get("modelo") or "padrao", "h_instr": h["instr"],
                              "h_estado": self._hash(depois), "h_lib": h["lib"], "h_fotos": h["fotos"],
                              "ultima_msg": resposta["id"],
                              "anexos": [a["nome"] for a in p.get("anexos_pendentes") or []]}
            self.store.event(id, "turno_ia", meta)
            p = self._gravar(p, [resposta])
            # Cena, exigência ou ficha mudou: os quadros já feitos voltam para a conferência
            if not erro_plano and any(response.get(k) for k in ("plano", "ajustes", "caderno")):
                self.agendar_conferencias(id)
            if response.get("acao") == "montar" and p["tomadas"] and all(pronta(s) for s in p["tomadas"]):
                # Montagem é ffmpeg: vai para a faixa de produção em vez de segurar a conversa até o fim
                self.background(id, self._montar, faixa="producao", rotulo="Montando o vídeo")
                return self.com_estado(self.store.get(id))
            elif response.get("acao") == "buscar_referencias" and isinstance(response.get("busca"), dict):
                busca = response["busca"]
                termo = str(busca.get("termo", "")).strip()[:120]
                if termo:
                    return self.buscar_referencias(p, termo, int(busca.get("quantidade") or 10), aviso=False)
            elif response.get("acao") == "gerar_imagem" and isinstance(response.get("imagem"), dict):
                pedido = response["imagem"]
                destino = pedido.get("pasta") if pedido.get("pasta") in DESTINOS_IMAGEM else "cenarios"
                usar_anexos = pedido.get("usar_anexos", True)
                refs = (p.get("anexos_pendentes") or []) if usar_anexos else []
                # cena: a tomada que recebe o quadro (uma imagem por frase no narrado)
                cena = pedido.get("cena") if any(s["id"] == pedido.get("cena") for s in p["tomadas"]) else None
                return self.pedir_imagem(p, destino, str(pedido.get("prompt", ""))[:1200], refs,
                                         bool(pedido.get("usar_ellie")), aviso=False, cena=cena)
        except Exception as e:
            if etapa == "openclaw":
                erro = "Não consegui continuar pelo OpenClaw. Confira a conexão e a assinatura.\n" + str(e).replace(" | ", "\n")[:1500]
                blocos = [{"tipo": "conexao"}]
            else:
                erro = "A IA respondeu, mas não consegui aplicar a resposta: " + erro_legivel(e) + "\nA produção está salva; peça de novo com outras palavras."
                blocos = []
            aviso = {"id": uuid.uuid4().hex, "papel": "assistant", "texto": erro, "blocos": blocos, "criado": agora()}
            return self.store.update(id, lambda atual: {**atual, "erro": erro,
                                                        "mensagens": atual["mensagens"] + [aviso]})
        finally:
            self.rascunhos.pop(id, None)
        return p

    def _ao_delta(self, id: str, texto: str, substituir: bool):
        self.rascunhos[id] = texto if substituir else self.rascunhos.get(id, "") + texto

    def rascunho(self, id: str) -> str:
        """Só o texto de mensagem_pt que já chegou, extraído do JSON ainda incompleto."""
        bruto = self.rascunhos.get(id, "")
        achado = re.search(r'"mensagem_pt"\s*:\s*"((?:[^"\\]|\\.)*)', bruto)
        if not achado:
            return ""
        parcial = achado.group(1)
        if parcial.endswith("\\"):
            parcial = parcial[:-1]
        try:
            return json.loads('"' + parcial + '"')
        except ValueError:
            return parcial.replace("\\n", "\n").replace('\\"', '"')

    def responder(self, p: dict | str, texto: str, blocos: list | None = None, mudar=None) -> dict:
        """Acrescenta a resposta ao registro FRESCO: outra faixa pode ter escrito enquanto esta esperava.

        `mudar` aplica as demais alterações dentro da mesma transação (nada se perde entre as duas)."""
        mensagem = {"id": uuid.uuid4().hex, "papel": "assistant", "texto": texto,
                    "blocos": blocos or [], "criado": agora(), "local": True}
        id = p if isinstance(p, str) else p["id"]
        def aplicar(atual: dict) -> dict:
            atual = mudar(atual) if mudar else atual
            return {**atual, "mensagens": atual["mensagens"] + [mensagem], "erro": ""}
        return self.store.update(id, aplicar)

    def rota_rapida(self, p: dict, text: str, colou_agora: bool) -> dict | None:
        """Resolve sem IA o que for óbvio: destino de imagem colada, variação da última imagem, ou quiz de 1 clique."""
        decisao = self.decisao_conferencia(p, text) if not colou_agora else None
        if decisao is not None:
            return decisao
        termo = termo_pinterest(text) if text and not colou_agora else None
        if termo and len(termo) <= 70 and "\n" not in termo:
            return self.buscar_referencias(p, termo)
        # termo longo (ex.: o roteiro inteiro): a IA resume num termo curto em inglês e pede a busca
        pendentes = p.get("anexos_pendentes") or []
        if pendentes:
            destino = intencao_imagem(text) if text else None
            if destino == "usar_quadro":
                return self.usar_como_quadro(p, pendentes[0])
            if destino == "guardar":
                nomes = ", ".join(a["nome"] for a in pendentes)
                return self.responder(p, f"Guardei na biblioteca, em anexos: {nomes}.",
                                      mudar=lambda atual: {**atual, "anexos_pendentes": []})
            if destino:
                escolha = text in OPCOES_IMAGEM_ELLIE or text in OPCOES_IMAGEM_LIVRE
                return self.pedir_imagem(p, destino, "" if escolha else text, pendentes,
                                         destino in ("base", "persona"))
            if colou_agora and len(text) < 25:
                opcoes = OPCOES_IMAGEM_ELLIE if p.get("master") else OPCOES_IMAGEM_LIVRE
                return self.responder(p, "O que eu faço com essa imagem?", [{
                    "tipo": "quiz", "titulo": "", "pergunta": "Escolha um caminho ou explique no chat.",
                    "opcoes": list(opcoes)}])
            return None  # tem pedido mais elaborado: a IA decide com a imagem anexada
        ultimo = p.get("ultimo_pedido_imagem")
        # "mais uma" com cena ainda sem imagem quer dizer a PRÓXIMA cena, não outra versão da última: a IA decide
        proxima = re.search(r"mais uma", _sem_acento(text or "")) and any(not s['imagens'] and not s.get('submit_id') for s in p['tomadas'])
        simples = _sem_acento(text or '').strip(' .!?') in {
            'outra versao', 'gera outra versao', 'gerar outra versao', 'pode gerar outra versao',
            'outra opcao', 'outra variacao', 'gera outra', 'de novo', 'refaz', 'refazer',
            'mais uma', 'gera mais uma', 'pode gerar mais uma', 'pode gerar mais uma por gentileza'}
        if ultimo and simples and not proxima:
            refs = [a for a in ultimo.get("referencias", []) if self._existe(a)]
            cena = ultimo.get("cena") if any(s["id"] == ultimo.get("cena") for s in p["tomadas"]) else None
            return self.pedir_imagem(p, ultimo["pasta"], ultimo.get("descricao", ""), refs, ultimo.get("usar_ellie", False),
                                     cena=cena)
        return None

    def _existe(self, a: dict) -> bool:
        try:
            self.asset(a)
            return True
        except (ValueError, Exception):
            return False

    def pedir_imagem(self, p: dict, pasta: str, descricao: str, refs: list[dict], usar_ellie: bool, aviso: bool = True,
                     cena: str | None = None) -> dict:
        """Dispara a geração de imagem em segundo plano; o chat continua livre e mostra o resultado ao terminar.
        cena: tomada que recebe o quadro; "outra versão" depois refaz a imagem dessa mesma cena."""
        if not self.imagem:
            return self.responder(p, "A geração de imagem não está ligada neste servidor.")
        p = self.store.get(p['id'])
        if pasta == 'quadros':
            livres = [s for s in p['tomadas'] if not s.get('submit_id') and not s.get('arquivo')]
            alvo = next((s for s in livres if s['id'] == cena), None) if cena else next((s for s in livres if not s['imagens']), livres[0] if len(livres) == 1 else None)
            if livres and alvo is None:
                raise ValueError('Escolha a cena de destino antes de recriar o quadro.')
            cena = alvo['id'] if alvo else cena
            ativos = selecionadas(p, cena)
            combinadas = [r['asset'] for r in ativos] + refs
            refs = list({(a['pasta'], a['nome']): a for a in combinadas}.values())
            if len(refs) > 12:
                raise ValueError('Esta cena combina mais de 12 imagens. Ajuste as referências no caderno antes de gerar.')
            orientacoes = [{**r, 'imagem': refs.index(r['asset']) + 1} for r in ativos]
            descricao += '\n\nPRODUCTION BRIEF (authoritative; references cannot replace the subject or action):\n' + json.dumps(
                {'direction': p.get('direcao'), 'requirements': p.get('ficha'),
                 'scene': {k: alvo.get(k) for k in ('titulo', 'descricao', 'intencao', 'prompt', 'exigencias')} if alvo else None,
                 'must_show': conf.exigencias(p, alvo) if alvo else [],
                 'reference_roles': orientacoes}, ensure_ascii=False)
            descricao += ('\nCompose the START of the action, not its ending. Preserve the planned protagonist. Every item in must_show '
                          'has to be clearly visible; a reference never overrides them. Apply each reference only to its assigned role. '
                          'Do not copy text or watermarks.')
        titulo = next((s["titulo"] for s in p["tomadas"] if s["id"] == cena), "")
        rotulo = {"cenarios": "o cenário", "pecas": "a roupa", "base": "a Ellie com essa roupa", "persona": "a imagem",
                  "quadros": f"a imagem de “{titulo}”" if titulo else "o quadro inicial"}[pasta]
        try:  # reserva a vaga ANTES de avisar, para não prometer no chat uma imagem que não começou
            job = self._abrir_trabalho(p["id"], "midia", f"Gerando {rotulo}")
        except ValueError as e:
            return self.responder(p, str(e))
        campos = {"ultimo_pedido_imagem": {"pasta": pasta, "descricao": descricao, "referencias": refs,
                                           "usar_ellie": usar_ellie, "cena": cena},
                  "anexos_pendentes": []}
        aplicar = lambda atual: {**atual, **campos}
        if aviso:
            p = self.responder(p, f"Gerando {rotulo} com o GPT Image. Leva de 30 s a 1,5 min; o resultado aparece aqui. "
                                  "Pode continuar falando comigo enquanto isso.", mudar=aplicar)
        else:
            p = self.store.update(p["id"], aplicar)
        self.background(p["id"], self._gerar_imagem, pasta, descricao, refs, usar_ellie, cena, faixa="midia", job=job)
        return self.com_estado(self.store.get(p["id"]))

    def _gerar_imagem(self, id: str, pasta: str, descricao: str, refs: list[dict], usar_ellie: bool, cena: str | None = None):
        caminhos = [self.asset(a) for a in refs]
        try:
            nome = self.imagem(pasta, descricao, "", caminhos, usar_ellie)
        except Exception as e:
            detalhe = getattr(e, "detail", None) or str(e)
            self.responder(id, f"A imagem não saiu: {str(detalhe)[:300]}. Peça de novo quando quiser.", [{"tipo": "conexao"}])
            return
        self.store.event(id, "imagem_gerada", {"pasta": pasta, "nome": nome, "referencias": [a["nome"] for a in refs]})
        cartao = [{"tipo": "imagem", "titulo": "", "pasta": pasta, "nomes": [nome], "gerada": True}]
        # Só o que o próprio sistema gerou pode ser descartado (nunca a modelo aprovada ou arquivos do Breno)
        gerada = {"pasta": pasta, "nome": nome}
        self.store.update(id, lambda atual: {**atual, "geradas": (atual.get("geradas") or []) + [gerada]})
        onde = ""
        if pasta == "quadros":
            try:
                p = self._com_retentativa(id, lambda atual: self._definir_quadro(atual, gerada, cena))
            except ValueError as e:  # a imagem existe: avisa em vez de sumir com o resultado
                self.responder(id, f"A imagem ficou pronta, mas não entrou em nenhuma cena: {e}", cartao)
                return
            alvo = next((s for s in p["tomadas"] if gerada in s["imagens"]), None)
            if alvo:
                onde = f" Entrou em “{alvo['titulo']}”."
                faltam = [s["titulo"] for s in p["tomadas"] if not paga(s) and not s["imagens"]]
                if faltam:
                    onde += " Ainda sem imagem: " + ", ".join(faltam) + "."
        self.responder(id, "Pronto." + onde + " Agora confiro se ele atende à cena." if pasta == "quadros" and onde else
                       "Pronto." + onde + " Se não ficou bom, peça outra versão ou descarte.", cartao)
        if pasta == "quadros" and onde:
            self.conferir_quadro(id, alvo["id"])  # mesma faixa de mídia: a imagem só vale depois de conferida

    # ---------------- Referências do Pinterest ----------------
    def buscar_referencias(self, p: dict, termo: str, quantidade: int = 10, aviso: bool = True) -> dict:
        quantidade = max(1, min(16, quantidade))
        try:
            job = self._abrir_trabalho(p["id"], "midia", f"Buscando “{termo}” no Pinterest")
        except ValueError as e:
            return self.responder(p, str(e))
        if aviso:
            p = self.responder(p, f"Buscando “{termo}” no Pinterest. Leva uns 20 a 60 s; as imagens aparecem aqui. "
                                  "Pode seguir conversando enquanto isso.")
        self.background(p["id"], self._buscar_referencias, termo, quantidade, faixa="midia", job=job)
        return self.com_estado(self.store.get(p["id"]))

    def _buscar_referencias(self, id: str, termo: str, quantidade: int):
        try:
            nomes = self.pinterest(termo, self.root / "referencias", quantidade)
        except Exception as e:
            self.responder(id, f"A busca no Pinterest não deu certo: {str(e)[:300]}")
            return
        self.store.event(id, "pinterest", {"termo": termo, "imagens": len(nomes)})
        if not nomes:
            self.responder(id, f"O Pinterest não devolveu imagens para “{termo}”. Tente outro termo (em inglês costuma render mais).")
            return
        def registrar(atual):
            refs = {r['id']: r for r in referencias(atual)}
            for nome in nomes:
                a = {'pasta': 'referencias', 'nome': nome}
                if chave(a) not in refs and len(refs) < 48:
                    refs[chave(a)] = Referencia(id=chave(a), asset=a, ativa=False, orientacao=f'Busca: {termo}').model_dump()
            return {**atual, 'referencias_criativas': list(refs.values())}
        self.store.update(id, registrar)
        self.responder(id, f"{len(nomes)} referências do Pinterest para “{termo}”. Escolha uma para virar quadro inicial "
                          "ou para o GPT recriar.", [{"tipo": "imagem", "titulo": "", "pasta": "referencias", "nomes": nomes,
                                                     "referencias": True, "termo": termo}])

    def usar_imagem(self, id: str, pedido: UsarImagem) -> dict:
        p = self.store.get(id)
        asset = pedido.asset.model_dump()
        self.asset(asset)
        if pedido.como == "quadro":
            return self.usar_como_quadro(p, asset)
        return self.pedir_imagem(p, 'quadros', 'Create an original vertical 9:16 first frame for the planned scene. '
                                 'Use the selected reference only as inspiration; the production brief defines the subject and action.',
                                 [asset], False, cena=pedido.cena)

    def salvar_caderno(self, id: str, pedido: SalvarCaderno) -> dict:
        self.exigir_livre(id)
        refs = [r.model_dump() for r in pedido.referencias]
        if len({r['id'] for r in refs}) != len(refs) or len({chave(r['asset']) for r in refs}) != len(refs):
            raise ValueError('Cada referência deve aparecer uma única vez no caderno.')
        if sum(r['ativa'] for r in refs) > 12:
            raise ValueError('Selecione até 12 referências ativas. As outras continuam guardadas no caderno.')
        p = self.store.get(id)
        ids = {s['id'] for s in p['tomadas']}
        for r in refs:
            self.asset(r['asset'])
            if not set(r['cenas']).issubset(ids):
                raise ValueError('Uma referência aponta para uma cena que não existe.')
        def aplicar(atual):
            if atual['versao'] != pedido.versao:
                raise ValueError('A produção mudou. Reabra o caderno antes de salvar.')
            ficha = pedido.ficha.model_dump()
            mudou = ficha != atual.get('ficha') or refs != referencias(atual)
            return {**atual, 'ficha': ficha, 'referencias_criativas': refs, 'fluxo_dirigido': True,
                    **({'revisao': None, 'cotacao': None, 'autorizacao': None, 'resultado': None} if mudou else {})}
        p = self.store.update(id, aplicar)
        self.agendar_conferencias(id)  # restrição ou critério novo: os quadros são conferidos de novo
        return p

    def revisar_storyboard(self, id: str, assinatura: str) -> dict:
        self.exigir_livre(id)
        def aplicar(p):
            if self.ocupado(id, 'midia'):
                raise ValueError('Espere os quadros em geração antes de revisar o storyboard.')
            if revisao(p)['assinatura'] != assinatura:
                raise ValueError('O storyboard mudou. Confira a versão atual antes de revisar.')
            if not p['tomadas'] or any(not s.get('imagens') and not s.get('arquivo') for s in p['tomadas']):
                raise ValueError('Complete os quadros de todas as cenas antes de revisar.')
            if (p.get('ficha') or {}).get('audio', 'indefinido') == 'indefinido':
                raise ValueError('Defina o áudio no caderno: original, narração ou silêncio intencional.')
            # O quadro de cada cena precisa ter passado na conferência (ou ter sido aceito por você)
            barradas = [s['titulo'] for s in p['tomadas'] if not s.get('arquivo')
                        and self.situacoes(p)[s['id']]['quadro'] not in ('ok', 'aceita')]
            if barradas:
                raise ValueError('Estes quadros ainda não passaram na conferência: ' + ', '.join(barradas)
                                 + '. Corrija, confira de novo ou escolha usar mesmo assim.')
            return {**p, 'revisao': {'assinatura': assinatura, 'criado': agora()}}
        return self.store.update(id, aplicar)

    # ---------------- Conferência: o material cumpre o que a cena exige? ----------------
    def _visao(self, sessao: str, pedido: str, imagens: list[Path]) -> dict:
        """Pergunta de conferência numa sessão própria, sem o histórico do chat: só o pedido e a imagem."""
        try:
            if self.conversar_ia:
                r = self.conversar_ia({"sessao": sessao, "completo": pedido, "delta": None,
                                       "imagensCompleto": [str(i) for i in imagens], "imagensDelta": [],
                                       "modeloAnterior": None}, lambda *_: None)
                return conf.veredito(r["texto"])
            return conf.veredito(self.ask(pedido, imagens))
        except Exception as e:  # sem conferência não há aprovação: fica indeterminada
            return {"atende": None, "itens": [], "resumo": f"Não consegui conferir agora ({str(e)[:160]}).", "correcao": ""}

    def situacoes(self, p: dict) -> dict:
        """Situação de cada cena: quadro (antes do gasto) e vídeo recebido (depois da geração)."""
        saida = {}
        for s in p.get("tomadas", []):
            quadro = s["imagens"][0] if s.get("imagens") else None
            item = {"quadro": conf.situacao((p.get("conferencias") or {}).get(s["id"]), conf.assinatura(p, s, quadro))
                    if quadro else "sem_quadro"}
            if s.get("arquivo") and paga(s):
                item["video"] = conf.situacao((p.get("conferencias_video") or {}).get(s["id"]),
                                              conf.assinatura(p, s, s["arquivo"]))
            saida[s["id"]] = item
        return saida

    @staticmethod
    def _texto_conferencia(s: dict, r: dict, material: str) -> str:
        nome = "o quadro" if material == "quadro" else "a tomada"
        if r["atende"] is True:
            return f"Conferi {nome} de “{s['titulo']}”: atende. {r['resumo']}".strip()
        falhas = "".join(f"\n✗ {i['exigencia']}: {i['observacao']}" for i in r["itens"] if not i["ok"])
        if r["atende"] is False:
            extra = "" if material == "quadro" else "\nPara refazer esta tomada, peça no chat: ela volta para cotação."
            return f"{nome[0].upper() + nome[1:]} de “{s['titulo']}” não atende: {r['resumo']}{falhas}{extra}"
        return f"Não consegui conferir {nome} de “{s['titulo']}”. {r['resumo']} Olhe você e decida."

    @staticmethod
    def _botoes_conferencia(s: dict, r: dict, material: str) -> list[dict]:
        if r["atende"] is True:
            return []
        t = s["titulo"]
        opcoes = [f"Refazer “{t}” com a correção"] if r["atende"] is False and material == "quadro" else []
        if r["atende"] is None:
            opcoes.append(f"Conferir “{t}” de novo")
        opcoes.append(f"Usar “{t}” mesmo assim")
        return [{"tipo": "quiz", "titulo": "", "pergunta": "Como seguimos com esta cena?", "opcoes": opcoes}]

    def conferir_quadro(self, id: str, cena: str, forcar: bool = False) -> dict | None:
        """Compara o quadro inicial com as exigências da cena e conta o resultado no chat."""
        p = self.store.get(id)
        s = next((t for t in p["tomadas"] if t["id"] == cena), None)
        if not s or not s.get("imagens") or not self._existe(s["imagens"][0]):
            return None
        midia = s["imagens"][0]
        ass = conf.assinatura(p, s, midia)
        if not forcar and conf.situacao((p.get("conferencias") or {}).get(cena), ass) != "pendente":
            return p["conferencias"][cena]
        r = {**self._visao(f"conferencia-{id[:20]}-{uuid.uuid4().hex[:8]}", conf.pedido_quadro(p, s), [self.asset(midia)]),
             "assinatura": ass, "midia": midia, "criado": agora(), "aceita": False}
        self.store.event(id, "conferencia_quadro", {"cena": cena, "atende": r["atende"]})
        self.responder(id, self._texto_conferencia(s, r, "quadro"), self._botoes_conferencia(s, r, "quadro"),
                       mudar=lambda atual: {**atual, "conferencias": {**(atual.get("conferencias") or {}), cena: r}})
        return r

    def conferir_tomada(self, id: str, cena: str, forcar: bool = False) -> dict | None:
        """Tomada recebida do Dreamina: pedido aceito não quer dizer vídeo certo. Confere técnica e ação."""
        p = self.store.get(id)
        s = next((t for t in p["tomadas"] if t["id"] == cena), None)
        if not s or not s.get("arquivo") or not paga(s):
            return None
        ass = conf.assinatura(p, s, s["arquivo"])
        if not forcar and conf.situacao((p.get("conferencias_video") or {}).get(cena), ass) != "pendente":
            return p["conferencias_video"][cena]
        caminho = self.asset(s["arquivo"])
        info = probe(caminho)
        tecnicos = conf.tecnica_video(info, tem_audio(caminho), s, p.get("ficha") or {})
        try:
            from studio.assistente import frames_do_video, montar_folha
            folha = self.output(id) / f"conferencia-{cena}.jpg"
            montar_folha(frames_do_video(caminho, 0, info["duracao"], quantidade=8), folha, colunas=4, celula=240, numerar=True)
            visual = self._visao(f"conferencia-{id[:20]}-{uuid.uuid4().hex[:8]}", conf.pedido_video(p, s), [folha])
        except Exception as e:
            visual = {"atende": None, "itens": [], "resumo": f"Não consegui montar os quadros da tomada ({str(e)[:120]}).", "correcao": ""}
        r = {**visual, "tecnico": tecnicos, "assinatura": ass, "midia": s["arquivo"], "criado": agora(), "aceita": False}
        if tecnicos:
            r["atende"] = False
            r["resumo"] = ("Problema técnico: " + "; ".join(tecnicos) + ". " + r["resumo"]).strip()
        self.store.event(id, "conferencia_video", {"cena": cena, "atende": r["atende"], "tecnico": tecnicos})
        self.responder(id, self._texto_conferencia(s, r, "video"), self._botoes_conferencia(s, r, "video"),
                       mudar=lambda atual: {**atual, "conferencias_video": {**(atual.get("conferencias_video") or {}), cena: r}})
        return r

    def agendar_conferencias(self, id: str) -> None:
        """Confere em segundo plano os quadros novos ou que ficaram desatualizados (cena ou ficha mudou)."""
        pendentes = [c for c, sit in self.situacoes(self.store.get(id)).items() if sit["quadro"] == "pendente"]
        if not pendentes:
            return
        try:
            self.background(id, self._conferir_lista, pendentes, faixa="midia", rotulo="Conferindo os quadros")
        except ValueError:
            pass  # faixa de mídia cheia: o próximo passo mostra o que falta conferir

    def _conferir_lista(self, id: str, cenas: list[str]) -> None:
        for cena in cenas:
            self.conferir_quadro(id, cena)

    def _reconferir(self, id: str, cena: str, material: str) -> None:
        (self.conferir_tomada if material == "video" else self.conferir_quadro)(id, cena, forcar=True)

    def aceitar_conferencia(self, id: str, cena: str, material: str = "quadro") -> dict:
        """"Usar mesmo assim": a decisão é sua e fica registrada; a conferência não some."""
        p = self.store.get(id)
        s = next((t for t in p["tomadas"] if t["id"] == cena), None)
        if not s:
            raise ValueError("Cena não encontrada.")
        midia = s.get("arquivo") if material == "video" else (s["imagens"][0] if s.get("imagens") else None)
        if not midia:
            raise ValueError("Esta cena ainda não tem material para aceitar.")
        campo = "conferencias_video" if material == "video" else "conferencias"
        ass = conf.assinatura(p, s, midia)
        anterior = (p.get(campo) or {}).get(cena) or {}
        registro = {"atende": None, "itens": [], "resumo": "Não conferido.", "correcao": "",
                    **(anterior if anterior.get("assinatura") == ass else {}),
                    "assinatura": ass, "midia": midia, "aceita": True, "aceita_em": agora()}
        self.store.event(id, "conferencia_aceita", {"cena": cena, "material": material})
        return self.responder(id, f"Combinado: “{s['titulo']}” segue mesmo assim. Fica registrado que foi decisão sua.",
                              mudar=lambda atual: {**atual, campo: {**(atual.get(campo) or {}), cena: registro}})

    def refazer_quadro(self, p: dict, s: dict) -> dict:
        """Gera de novo o quadro da cena, com a correção apontada pela conferência como exigência."""
        r = (p.get("conferencias") or {}).get(s["id"]) or {}
        falhas = [i["exigencia"] for i in r.get("itens", []) if not i.get("ok")]
        ultimo = p.get("ultimo_pedido_imagem") or {}
        refs = [a for a in ultimo.get("referencias", []) if ultimo.get("cena") == s["id"] and self._existe(a)]
        descricao = ("Recreate the first frame of this scene. The previous attempt failed the continuity check."
                     + (f"\nMUST FIX: {r['correcao']}" if r.get("correcao") else "")
                     + ("\nFailed requirements: " + "; ".join(falhas) if falhas else ""))
        return self.pedir_imagem(p, "quadros", descricao, refs, bool(p.get("master")) and s.get("ellie") is not False,
                                 cena=s["id"])

    def decisao_conferencia(self, p: dict, text: str) -> dict | None:
        """Respostas de 1 clique aos cartões de conferência (refazer, usar mesmo assim, conferir de novo)."""
        m = re.fullmatch(r"(Refazer|Usar|Conferir) “(.+)” (com a correção|mesmo assim|de novo)", (text or "").strip())
        if not m:
            return None
        s = next((t for t in p["tomadas"] if t["titulo"] == m.group(2)), None)
        if not s:
            return self.responder(p, "Não achei essa cena: ela pode ter mudado de nome. Abra as cenas e escolha de novo.")
        material = "video" if s.get("arquivo") and paga(s) else "quadro"
        if m.group(1) == "Refazer":
            return self.refazer_quadro(p, s)
        if m.group(1) == "Usar":
            return self.aceitar_conferencia(p["id"], s["id"], material)
        try:
            self.background(p["id"], self._reconferir, s["id"], material, faixa="midia",
                            rotulo=f"Conferindo “{s['titulo']}”")
        except ValueError as e:
            return self.responder(p, str(e))
        return self.responder(p, f"Conferindo “{s['titulo']}” de novo.")

    def ativar_referencia(self, id: str, pedido: AtivarReferencia) -> dict:
        """Liga uma referência no caderno direto do cartão do Pinterest, com o papel que ela cumpre."""
        asset = pedido.asset.model_dump()
        self.asset(asset)
        def aplicar(atual):
            refs = {r['id']: r for r in referencias(atual)}
            item = refs.get(chave(asset)) or Referencia(id=chave(asset), asset=asset).model_dump()
            ativas = sum(r['ativa'] for k, r in refs.items() if k != item['id'])
            if pedido.ativa and ativas >= 12:
                raise ValueError('O caderno já tem 12 referências ativas. Desligue uma antes.')
            item.update(ativa=pedido.ativa, papel=pedido.papel, orientacao=pedido.orientacao or item.get('orientacao', ''))
            refs[item['id']] = item
            return {**atual, 'referencias_criativas': list(refs.values())}
        return self.store.update(id, aplicar)

    def caderno_da_ia(self, p: dict, dados: dict) -> dict:
        """A IA explica e ajusta o caderno: papel e orientação de cada referência, ficha (público, restrições,
        critérios, áudio). Só mexe no que existe; nunca passa de 12 referências ativas."""
        if isinstance(dados.get("ficha"), dict):
            p['ficha'] = Ficha(**{**(p.get('ficha') or {}), **{k: v for k, v in dados['ficha'].items() if k in Ficha.model_fields}}).model_dump()
        refs = {r['id']: dict(r) for r in referencias(p)}
        por_nome = {r['asset']['nome']: r['id'] for r in refs.values()}
        ids_cenas = {s['id'] for s in p['tomadas']}
        for item in dados.get("referencias") or []:
            if not isinstance(item, dict):
                continue
            rid = item.get('id') if item.get('id') in refs else por_nome.get(item.get('nome', ''))
            if not rid:
                continue
            ref = refs[rid]
            novo = {**ref, **{k: item[k] for k in ('ativa', 'papel', 'orientacao') if k in item}}
            if 'cenas' in item:
                novo['cenas'] = [c for c in item['cenas'] if c in ids_cenas]
            refs[rid] = Referencia(**novo).model_dump()
        if sum(r['ativa'] for r in refs.values()) > 12:
            raise ValueError('O caderno passaria de 12 referências ativas.')
        p['referencias_criativas'] = list(refs.values())
        return p

    def _definir_quadro(self, p: dict, asset: dict, cena: str | None = None) -> dict:
        """Coloca a imagem como quadro inicial. Com `cena`, nela. Sem: na primeira tomada ainda sem imagem; com
        uma tomada só, substitui a dela; com várias já preenchidas, recusa (não troca a imagem de uma frase no
        chute). Sem tomada disponível, abre uma cena nova (invalida cotação antiga, se houver)."""
        plano = {k: p.get(k) for k in CAMPOS_PLANO}
        plano["layout"] = layout_de(p)
        tomadas = [dict(s) for s in p["tomadas"]]
        livres = [s for s in tomadas if not s.get("submit_id") and not s.get("arquivo")]
        if cena:
            alvo = next((s for s in livres if s["id"] == cena), None)
            if not alvo:
                raise ValueError("essa cena não existe mais ou já foi gerada no Dreamina.")
        else:
            alvo = next((s for s in livres if not s["imagens"]), livres[0] if len(livres) == 1 else None)
            if not alvo and len(livres) > 1:
                raise ValueError("todas as cenas já têm imagem. Diga em qual frase usar esta, e eu troco.")
        if alvo:
            alvo["imagens"] = [asset]
            if paga(alvo) and not alvo.get("movimento"):
                alvo["modo"] = "first_last_frame"
        else:
            n = len(tomadas) + 1
            while any(s["id"] == f"cena-{n}" for s in tomadas):
                n += 1
            tomadas.append(Tomada(id=f"cena-{n}", titulo=f"Cena {n}", modo="first_last_frame", duracao=10,
                                  prompt=PROMPT_QUADRO, imagens=[Asset(**asset)],
                                  lado="direita" if plano["layout"] == "lado_a_lado" and not tomadas else "cheia",
                                  ellie=False if not p.get("master") else None).model_dump())
            if plano["layout"] == "tela_cheia":
                if plano["cortes"]:
                    plano["cortes"] = list(plano["cortes"]) + [{"tomada": f"cena-{n}", "inicio": 0, "duracao": 10, "recorte": None}]
                    plano["duracao_final"] = float(plano["duracao_final"]) + 10
        plano["tomadas"] = tomadas
        return self.save_plan(p, plano, p["versao"])

    def usar_como_quadro(self, p: dict, asset: dict) -> dict:
        p["anexos_pendentes"] = []
        p = self._definir_quadro(p, asset)
        p = self.responder(p, "Pronto, essa imagem é o quadro inicial da cena. Vou conferir se ela atende ao que a cena pede.",
                           [{"tipo": "plano", "titulo": "Cenas"}])
        self.agendar_conferencias(p["id"])
        return p

    def descartar(self, id: str, asset: dict) -> dict:
        """Tira um arquivo da biblioteca sem apagar: move para a pasta lixeira (dá pra recuperar).
        Só vale para imagens que o sistema gerou ou que o Breno colou; nunca para a modelo aprovada."""
        p = self.store.get(id)
        if asset == p.get("master") or asset not in (p.get("geradas") or []) and asset["pasta"] != "anexos":
            raise ValueError("Esse arquivo não foi gerado nesta conversa; não vou tirá-lo da biblioteca.")
        path = self.asset(asset)
        lixeira = self.root / "lixeira" / asset["pasta"]
        lixeira.mkdir(parents=True, exist_ok=True)
        destino = lixeira / path.name
        if destino.exists():
            destino = lixeira / f"{path.stem}-{uuid.uuid4().hex[:6]}{path.suffix}"
        path.replace(destino)
        def aplicar(atual: dict) -> dict:
            # Marca o descarte nas mensagens FRESCAS: outra faixa pode ter escrito enquanto o arquivo ia pra lixeira
            mensagens = []
            for m in atual["mensagens"]:
                m = dict(m)
                for b in m.get("blocos") or []:
                    if b.get("tipo") == "imagem" and b.get("pasta") == asset["pasta"] and asset["nome"] in (b.get("nomes") or []):
                        b["descartado"] = True
                if asset in (m.get("anexos") or []):
                    m["anexos"] = [a for a in m["anexos"] if a != asset]
                mensagens.append(m)
            return {**atual, "mensagens": mensagens,
                    "anexos_pendentes": [a for a in atual.get("anexos_pendentes") or [] if a != asset]}
        self.store.event(id, "descartado", asset)
        return self.store.update(id, aplicar)

    # ---------------- Narração (formato narrado) ----------------
    def gerar_narracao(self, id: str, pedido: Narracao) -> None:
        from studio.narracao import gerar_elevenlabs
        p = self.store.get(id)
        texto = pedido.texto.strip() or (p.get("narracao") or {}).get("texto", "")
        if not texto:
            raise ValueError("Escreva o texto da narração.")
        nome = f"narracao-{uuid.uuid4().hex[:6]}.mp3"
        palavras = gerar_elevenlabs(texto, self.output(id) / nome, pedido.voz)
        cta = pedido.cta.strip()
        def gravar(atual: dict) -> dict:
            narracao = {**NARRACAO_VAZIA, **(atual.get("narracao") or {}), "texto": texto, "voz": pedido.voz,
                        "setas": pedido.setas, "audio": nome, "palavras": palavras, "origem": "elevenlabs"}
            if cta:
                narracao["cta"] = cta
            return {**atual, "narracao": narracao}
        self.store.event(id, "narracao", {"origem": "elevenlabs", "palavras": len(palavras)})
        self._voz_pronta(id, "Voz pronta", palavras, self.output(id) / nome, gravar)

    def salvar_audio_narracao(self, id: str, origem: Path, texto: str, setas: bool) -> None:
        from studio.narracao import alinhar_arquivo
        palavras = alinhar_arquivo(origem, texto)
        def gravar(atual: dict) -> dict:
            return {**atual, "narracao": {
                **NARRACAO_VAZIA, **(atual.get("narracao") or {}), "texto": texto or " ".join(w["p"] for w in palavras),
                "setas": setas, "audio": origem.name, "palavras": palavras, "origem": "arquivo"}}
        self.store.event(id, "narracao", {"origem": "arquivo", "palavras": len(palavras)})
        self._voz_pronta(id, "Áudio recebido e sincronizado", palavras, origem, gravar)

    def _voz_pronta(self, id: str, inicio: str, palavras: list[dict], audio: Path, gravar) -> None:
        """Grava a voz, monta uma cena por frase (áudio primeiro) e conta no chat o que falta: as imagens."""
        from studio.narracao import duracao_audio
        try:
            duracao = duracao_audio(audio)
        except ValueError:  # o ffprobe não leu: conta só pelas palavras
            duracao = 0.0
        frases = cenas_sugeridas(palavras, duracao)
        mudar = lambda atual: self._alinhar_se_der(self.cenas_pela_voz(audio_pela_narracao(gravar(atual)), duracao))
        p = self.responder(id, "", [{"tipo": "narracao"}], mudar=mudar)
        texto = f"{inicio}: {duracao_total(palavras, duracao):.1f}s de vídeo, {len(frases)} frases. Ouça no cartão da narração."
        blocos = [{"tipo": "narracao"}]
        if self.segue_voz(p):
            linhas = [s['titulo'] + ("" if pronta(s) else " (falta imagem)") for s in p['tomadas']]
            texto += "\n\nA sequência de cenas foi preservada e os cortes foram ajustados à voz:\n" + "\n".join(linhas)
            if any(not pronta(s) for s in p["tomadas"]):
                blocos.append({"tipo": "quiz", "titulo": "", "pergunta": "Próximo passo: a imagem de cada frase.",
                               "opcoes": ["Sugerir as imagens das cenas", "Gerar a imagem da próxima cena"]})
            blocos.append({"tipo": "plano", "titulo": "Cenas pela voz"})
        # a mensagem vazia acima garante que voz e cenas foram gravadas juntas; aqui ela ganha o texto
        msg_id = p["mensagens"][-1]["id"]
        self.store.update(id, lambda atual: {**atual, "mensagens": [
            {**m, "texto": texto, "blocos": blocos} if m["id"] == msg_id else m for m in atual["mensagens"]]})

    def ajustar_narracao(self, id: str, ajustes: AjustesNarracao) -> dict:
        """Estilo da legenda, trilha, whoosh e "cortes seguem a voz": só acabamento local, sem créditos."""
        self.exigir_livre(id)
        self.trilha(ajustes.trilha)  # valida o nome
        def aplicar(atual: dict) -> dict:
            n = {**NARRACAO_VAZIA, **(atual.get("narracao") or {}), **ajustes.model_dump()}
            return self._alinhar_se_der({**atual, "narracao": n})
        return self.store.update(id, aplicar)

    def chat(self, id: str, request: Mensagem) -> dict:
        """A conversa tem faixa própria: imagem, voz ou montagem em andamento não impedem falar."""
        with self.lock:
            if id in self.chatting:
                raise ValueError(FAIXA_OCUPADA["conversa"])
            job = self._abrir_trabalho(id, "conversa", "Pensando na resposta")
            self.chatting[id] = threading.get_ident()
        try:
            return self.message(id, request)
        finally:
            with self.lock:
                self.chatting.pop(id, None)
            self._fechar_trabalho(id, job)

    @staticmethod
    def cards(values: list, library: dict) -> list[dict]:
        cards = []
        if not isinstance(values, list):
            return cards
        for item in values[:4]:
            if not isinstance(item, dict):
                continue
            kind = item.get("tipo")
            if kind not in ("direcao", "galeria", "quiz", "plano", "custo", "resultado", "upload", "edicao", "imagem", "narracao"):
                continue
            card = {"tipo": kind, "titulo": str(item.get("titulo", ""))[:150]}
            if kind == "imagem":
                folder = item.get("pasta")
                if folder not in PASTAS:
                    continue
                card.update(pasta=folder, nomes=[n for n in item.get("nomes", []) if n in library[folder]][:8])
                if not card["nomes"]:
                    continue
            elif kind in ("galeria", "upload"):
                folder = item.get("pasta", "movimentos")
                if folder not in PASTAS:
                    continue
                card.update(pasta=folder, papel=item.get("papel") if item.get("papel") in ("movimento", "master", "estado", "bruto") else "estado")
                card["nomes"] = [n for n in item.get("nomes", library[folder]) if n in library[folder]][:60]
            elif kind == "quiz":
                card["pergunta"] = str(item.get("pergunta", ""))[:300]
                card["opcoes"] = [str(v)[:120] for v in item.get("opcoes", [])][:5]
            cards.append(card)
        return cards

    def prepare_quote(self, id: str, selected: list[str] | None = None) -> dict:
        p = self.store.get(id)
        pending = [s for s in p["tomadas"] if paga(s) and not s.get("arquivo") and not s.get("submit_id")]
        if selected is not None:
            if not selected or not set(selected).issubset({s['id'] for s in pending}):
                raise ValueError("Escolha somente tomadas novas deste plano para cotar.")
            pending = [s for s in pending if s['id'] in selected]
        if not pending:
            if any(not paga(s) for s in p["tomadas"]):
                raise ValueError("Nada para cotar: as cenas de imagem não usam créditos. É só montar.")
            raise ValueError("Não há novas tomadas para cotar. Use os arquivos existentes para montar.")
        if len(pending) > 3 and not p.get("permitir_plano_extenso"):
            raise ValueError("O primeiro lote aceita até três tomadas. Simplifique antes de cotar para evitar o custo do V7.")
        # Uma consulta nova substitui a anterior mesmo se falhar. Nunca deixar
        # o botão de autorização apontar para o orçamento antigo após um erro.
        p['cotacao'] = p['autorizacao'] = None
        p['erro'] = ''
        p = self._gravar(p)
        # _gravar devolve o registro salvo; os rascunhos abaixo precisam pertencer
        # a essa cópia para que os IDs retornados pela CLI sejam persistidos.
        selecionadas = {s['id'] for s in pending}
        pending = [s for s in p['tomadas'] if s['id'] in selecionadas]
        for shot in pending:
            if not shot["imagens"] and not (p.get("master") and shot.get("ellie") is not False):
                raise ValueError(f"A tomada \"{shot['titulo']}\" não tem imagem: gere/cole um quadro ou escolha as referências.")
            for a in shot["imagens"]:
                self.asset(a)
            effective = dict(shot)
            effective["imagens"] = list(shot["imagens"])
            if p.get("master") and shot.get("ellie") is not False and p["master"] not in effective["imagens"]:
                effective["imagens"].append(p["master"])
            # Reserva espaço para os placeholders tipados adicionados pelo adaptador.
            effective["prompt"] += " " * (70 * (len(effective["imagens"]) + int(bool(shot.get("movimento")))))
            self.cli.validate(effective)
        fingerprint = self.generation_hash(p)
        if not p["canvas_id"]:
            p["canvas_id"] = str(uuid.uuid4())
            p = self._gravar(p)
        if not p.get("canvas_url"):
            created = self.cli.canvas(p["canvas_id"], p["nome"])
            p["canvas_url"] = created.get("webUrl", "")
            p = self._gravar(p)

        def imported(path: Path, media: str) -> str:
            kind = "external_generated" if media == "image" else "local_upload"
            key = sha256(path)
            item = p["imports"].setdefault(key, {"resource": str(uuid.uuid4()), "submit": str(uuid.uuid4())})
            if not item.get("imported"):
                item.pop("node", None)  # IDs inventados por versões antigas eram recusados pela CLI
            self._gravar(p)
            if not item.get("uploaded"):
                result = self.cli.upload(path, p["canvas_id"], item["resource"], kind)
                if result.get("resourceId") != item["resource"]:
                    raise ValueError("O upload não corresponde à referência planejada.")
                item["uploaded"] = True
                self._gravar(p)
            if not item.get("imported"):
                criado = self.cli.import_node(media, item["resource"], None, p["canvas_id"], item["submit"], path.stem, kind)
                item["node"] = Dreamina.node_id(criado)
                if not item["node"]:
                    raise ValueError("A CLI criou a referência mas não devolveu o node_id. Resposta: " + json.dumps(criado)[:300])
                item["imported"] = True
                self._gravar(p)
            return item["node"]

        for shot in pending:
            refs = [imported(self.asset(a), "image") for a in shot["imagens"]]
            if p.get("master") and shot.get("ellie") is not False and p["master"] not in shot["imagens"]:
                refs.append(imported(self.asset(p["master"]), "image"))
            if shot.get("movimento"):
                source = self.asset(shot["movimento"])
                target = self.output(id) / f"movimento-{shot['id']}.mp4"
                preparar_referencia(source, target, shot["movimento_inicio"], shot["movimento_duracao"])
                refs.append(imported(target, "video"))
            if not shot.get("node_id_cli"):
                shot.pop("node_id", None)  # sem ID: a CLI cria; com ID dela, atualiza o mesmo rascunho
            criado = self.cli.draft(shot, p["canvas_id"], refs)
            if not shot.get("node_id_cli"):
                shot["node_id"] = Dreamina.node_id(criado)
                if not shot["node_id"]:
                    raise ValueError("A CLI criou a tomada mas não devolveu o node_id. Resposta: " + json.dumps(criado)[:300])
                shot["node_id_cli"] = True
            shot["estado"] = "rascunho"
            self._gravar(p)
        quote = self.cli.quote(p["canvas_id"], [s["node_id"] for s in pending])
        p["cotacao"] = {"id": uuid.uuid4().hex, "hash": fingerprint, "criado": agora(), "draft_version": quote.get("draftVersion"),
                         "total": quote["totalMaxCredits"], "itens": quote["items"], "tomadas": [s['id'] for s in pending], "unidade": "creditos_dreamina"}
        p["autorizacao"] = None
        p["status"] = "orcamento"
        p["erro"] = ""
        self.store.event(id, "cotacao", {"total": quote["totalMaxCredits"], "hash": fingerprint})
        return self._gravar(p)

    def generate(self, id: str, request: Gerar) -> dict:
        p = self.store.get(id)
        q = p.get("cotacao")
        if q and q.get("executada"):
            raise ValueError("As tomadas deste lote já foram enviadas. Use Acompanhar.")
        if p.get("exemplo"):
            raise ValueError("O exemplo é histórico. Crie um novo vídeo para gerar outra versão.")
        if not q or request.cotacao_id != q["id"] or q["hash"] != self.generation_hash(p):
            raise ValueError("O plano mudou ou a cotação venceu. Consulte o custo novamente.")
        # Nada é gasto sem o storyboard revisado na versão atual (quadros conferidos e áudio decidido)
        if p.get("fluxo_dirigido") and not revisao(p)["atual"]:
            raise ValueError("Revise o storyboard antes de gerar: ele mudou desde a última revisão, ou ainda não foi revisado.")
        if request.teto < q["total"]:
            raise ValueError("O custo ultrapassa o teto que você autorizou.")
        pending = [s for s in p["tomadas"] if paga(s) and not s.get("arquivo") and not s.get("submit_id")]
        if q.get("tomadas"):
            pending = [s for s in pending if s['id'] in q['tomadas']]
        if not pending:
            raise ValueError("As tomadas deste lote já foram enviadas. Use Acompanhar para recuperar os resultados.")
        fresh = self.cli.quote(p["canvas_id"], [s["node_id"] for s in pending])
        if fresh["totalMaxCredits"] > request.teto or fresh["totalMaxCredits"] != q["total"] or fresh.get("draftVersion") != q.get("draft_version"):
            raise ValueError("O preço mudou. Atualize a cotação antes de gerar.")
        quoted = {i["nodeId"]: i["maxCredits"] for i in fresh["items"]}
        p["autorizacao"] = {"em": agora(), "teto": request.teto, "hash": q["hash"], "origem": "clique_humano", "cotacao_id": q["id"]}
        for shot in pending:
            shot["submit_id"] = str(uuid.uuid4())
            shot["estado"] = "envio_incerto"
            shot["reserva_creditos"] = quoted[shot["node_id"]]
        p["status"] = "gerando"
        q["executada"] = True
        self._gravar(p)  # Identidade e reserva existem ANTES da chamada que pode gastar.
        self.store.event(id, "autorizacao", {"teto": request.teto, "cotacao_id": q["id"]})
        try:
            self.cli.run(p["canvas_id"], pending, request.teto)
            for shot in pending:
                shot["estado"] = "enviado"
            p["erro"] = ""
        except Exception:
            p["status"] = "envio_incerto"
            p["erro"] = "O envio não foi confirmado. Os identificadores estão preservados. Use Acompanhar; não gerar novamente."
        return self._gravar(p)

    def sync(self, id: str) -> dict:
        p = self.store.get(id)
        if p.get("status") == "concluido" and p.get("resultado") and all(pronta(s) for s in p["tomadas"]):
            return p
        prontas_antes = {s["id"] for s in p["tomadas"] if s.get("arquivo")}
        falhas_antes = {s["id"] for s in p["tomadas"] if s.get("estado") in ("failed", "canceled", "cancelled")}
        for shot in p["tomadas"]:
            if not shot.get("submit_id") or shot.get("arquivo"):
                continue
            op = self.cli.operation(p["canvas_id"], shot["submit_id"])
            shot["estado"] = op.get("state", "incerto")
            resources = [r for r in op.get("resources", []) if r.get("state") in ("succeeded", "success")]
            if resources:
                resource = resources[0]["resourceId"]
                shot["resource_id"] = resource
                facts = self.cli.resource(p["canvas_id"], resource)
                if facts.get("type") != "video" or facts.get("status") != "success":
                    raise ValueError("O recurso retornado ainda não é um vídeo concluído.")
                if isinstance(facts.get("creditsAmount"), (int, float)):
                    shot["creditos_registrados"] = facts["creditsAmount"]
                self._gravar(p)
                filename = f"{id[:12]}-{shot['id']}.mp4"
                dest = self.root / "saida" / filename
                partial = dest.with_name(dest.stem + ".download.mp4")
                if not dest.exists():
                    self.cli.download(p["canvas_id"], resource, partial)
                    data = probe(partial)
                    if data["duracao"] + .1 < shot["duracao"]:
                        raise ValueError("Download incompleto. O recurso remoto foi preservado; use Acompanhar para baixar o mesmo recurso.")
                    partial.replace(dest)
                data = probe(dest)
                shot.update(arquivo={"pasta": "saida", "nome": filename}, sha256=sha256(dest), estado="baixado", info=data)
                p["erro"] = ""
            self._gravar(p)
        # Pedido aceito não quer dizer vídeo certo: cada tomada nova é conferida antes de entrar na montagem
        for cena in [s["id"] for s in p["tomadas"] if s.get("arquivo") and s["id"] not in prontas_antes and paga(s)]:
            self.conferir_tomada(id, cena)
        p = self.store.get(id)
        sits = self.situacoes(p)
        barradas = [s["titulo"] for s in p["tomadas"] if sits.get(s["id"], {}).get("video") == "problema"]
        avisos = self._avisar_tomadas(p, prontas_antes, falhas_antes, barradas)
        if all(pronta(s) for s in p["tomadas"]):
            p["status"] = "conferir_tomadas" if barradas else "pronto_para_montar"
            p = self._gravar(p, avisos)
            if barradas or self._falta_voz(p):
                return p  # monta quando a voz estiver pronta e as tomadas passarem na conferência
            return self.render(id)
        elif any(s.get("estado") in ("failed", "canceled", "cancelled") for s in p["tomadas"]):
            p["status"] = "parcial"
            p["erro"] = "Uma tomada não concluiu. Os resultados e custos conhecidos foram preservados. Nenhuma repetição foi feita; estorno ainda não foi confirmado."
        elif not any(s.get("submit_id") and not s.get("arquivo") for s in p["tomadas"]):
            p["status"] = "proxima_tomada"
        return self._gravar(p, avisos)

    def _avisar_tomadas(self, p: dict, prontas_antes: set, falhas_antes: set, barradas: list[str] | None = None) -> list[dict]:
        """Monta o aviso de chat, sem IA, quando uma tomada fica pronta ou falha, com o cartão de produção atualizado.

        Devolve as mensagens em vez de gravar: quem grava é o `_gravar` do `sync`, que junta o que a
        conversa escreveu em paralelo."""
        novas = [s for s in p["tomadas"] if s.get("arquivo") and s["id"] not in prontas_antes]
        falhas = [s for s in p["tomadas"] if s.get("estado") in ("failed", "canceled", "cancelled") and s["id"] not in falhas_antes]
        if not novas and not falhas:
            return []
        faltam = [s["titulo"] for s in p["tomadas"] if not pronta(s)]
        partes = []
        for s in novas:
            gasto = f", {s['creditos_registrados']} créditos" if isinstance(s.get("creditos_registrados"), (int, float)) else ""
            partes.append(f"A tomada \"{s['titulo']}\" ficou pronta ({s.get('info', {}).get('duracao', s['duracao']):.0f}s{gasto}). Assista abaixo antes de seguir.")
        for s in falhas:
            partes.append(f"A tomada \"{s['titulo']}\" não concluiu no Dreamina. Nada foi repetido; os custos conhecidos ficaram registrados.")
        sem_voz = self._falta_voz(p)
        partes.append(("Falta: " + ", ".join(faltam) + ".") if faltam else
                      ("Antes de montar, resolva a conferência de: " + ", ".join(barradas) + ".") if barradas else
                      "Tomadas prontas. Falta a voz: gere ou envie no cartão da narração, depois monte." if sem_voz else
                      "Todas as tomadas estão prontas; vou montar o vídeo.")
        return [{"id": uuid.uuid4().hex, "papel": "assistant", "texto": " ".join(partes),
                 "blocos": [{"tipo": "custo", "titulo": "Produção das tomadas"}], "criado": agora(), "local": True}]

    def reuse(self, p: dict, id: str, asset: dict) -> dict:
        path = self.asset(asset)
        info = probe(path)
        shot = next((s for s in p["tomadas"] if s["id"] == id), None)
        if not shot:
            raise ValueError("Tomada não encontrada.")
        if shot.get("submit_id"):
            raise ValueError("Esta tomada tem envio remoto. Use Acompanhar para recuperar o próprio resultado.")
        shot.update(arquivo=asset, estado="reaproveitado", info=info, sha256=sha256(path))
        p["cotacao"] = p["autorizacao"] = None
        return self._gravar(p)

    def select_reference(self, id: str, selection: Selecao) -> dict:
        p = self.store.get(id)
        self.exigir_livre(id)
        value = selection.asset.model_dump()
        path = self.asset(value)
        if selection.papel == "bruto":
            return self.reuse(p, selection.tomada, value)
        if selection.papel == "master":
            if path.suffix.lower() not in IMAGEM or any(s.get("submit_id") for s in p["tomadas"]):
                raise ValueError("Use uma imagem aprovada antes de enviar as tomadas.")
            p["master"] = value
        elif selection.papel == "movimento":
            if path.suffix.lower() not in VIDEO:
                raise ValueError("A referência de movimento precisa ser vídeo.")
            p["referencia"] = value
            for shot in p["tomadas"]:
                if not shot.get("submit_id"):
                    shot["movimento"] = value
        elif selection.papel == "estado":
            if path.suffix.lower() not in IMAGEM:
                raise ValueError("O estado da roupa precisa ser uma imagem.")
            livres = [s for s in p["tomadas"] if not s.get("submit_id")]
            alvos = ([s for s in livres if s["id"] == selection.tomada] or
                     ([s for s in livres if s["lado"] == "esquerda"] if layout_de(p) == "lado_a_lado" else livres[:1]))
            if not alvos:
                raise ValueError("Não há tomada livre para receber essa imagem.")
            for shot in alvos:
                if value not in shot["imagens"]:
                    shot["imagens"].append(value)
        p["cotacao"] = p["autorizacao"] = None
        p = self._gravar(p)
        if selection.papel == "estado":
            self.agendar_conferencias(id)
        return p

    @staticmethod
    def _falta_voz(p: dict) -> bool:
        n = p.get("narracao") or {}
        return bool(n.get("texto", "").strip()) and not n.get("audio")

    def render(self, id: str) -> dict:
        p = self.store.get(id)
        if not p["tomadas"] or not all(pronta(s) for s in p["tomadas"]):
            raise ValueError("Ainda faltam tomadas prontas para montar.")
        n = p.get("narracao") or {}
        if self._falta_voz(p):
            raise ValueError("Falta a narração: gere a voz ou envie o áudio (ou apague o texto da narração) antes de montar.")
        # Áudio primeiro: os cortes seguem as frases da voz e o vídeo dura o tempo dela (sem quadro congelado)
        segue = self.segue_voz(p)
        p, avisos = self.alinhar_voz(p)
        # O áudio decidido no caderno manda: original mantém o som das tomadas; narração entra por cima
        audio_plano = (p.get("ficha") or {}).get("audio", "indefinido")
        narrado = bool(n.get("audio") and n.get("palavras"))
        original = audio_plano == "original" and not narrado
        pendencias: list[str] = []
        producao = {**p, "tomadas": self.tomadas_montaveis(p)}
        if layout_de(p) == "lado_a_lado":
            result = montar(producao, self.asset, self.output(id))
            if original:
                pendencias.append("O lado a lado ainda sai sem o som original das tomadas.")
        else:
            if not p.get("cortes"):
                raise ValueError("O plano não tem cortes.")
            result = montar_sequencia(producao, self.asset, self.output(id), audio_original=original)
            if result.get("sem_audio"):
                pendencias.append("Sem som original em: " + ", ".join(result["sem_audio"]) + " (entraram em silêncio).")
        if narrado:
            from studio.montagem_narrada import checar
            numero = sum(1 for f in self.output(id).glob("narrado-*.mp4")) + 1
            result = self._narrar(p, Path(result["caminho"]), self.output(id) / f"narrado-{numero}.mp4", segue)
            avisos += checar(Path(result["caminho"]), float(p["duracao_final"]) if segue else result["duracao"])
        else:
            from studio.montagem_narrada import checar
            avisos += checar(Path(result["caminho"]), result["duracao"])
        # Conferência final: o arquivo entregue tem o áudio que o plano pede e tomadas que passaram na conferência
        if (audio_plano in ("original", "narracao") or narrado) and not tem_audio(Path(result["caminho"])):
            pendencias.append("O vídeo final saiu sem faixa de áudio, e o plano pede som.")
        if audio_plano == "narracao" and not narrado:
            pendencias.append("O plano pede narração, mas a voz ainda não está pronta.")
        if audio_plano == "indefinido" and not narrado:
            avisos.append("O áudio não foi decidido no caderno: o vídeo saiu sem som.")
        sits = self.situacoes(p)
        for s in p["tomadas"]:
            situacao_video = sits.get(s["id"], {}).get("video")
            if situacao_video == "problema":
                pendencias.append(f"A tomada “{s['titulo']}” não passou na conferência.")
            elif situacao_video in ("pendente", "indeterminada"):
                avisos.append(f"A tomada “{s['titulo']}” não foi conferida visualmente: assista antes de postar.")
        p["resultado"] = {**{k: v for k, v in result.items() if k != "sem_audio"}, "nome": Path(result["caminho"]).name,
                          "avisos": avisos, "pendencias": pendencias, "aprovado": not pendencias}
        p["status"] = "concluido" if not pendencias else "com_pendencias"
        p["erro"] = ""
        self.store.event(id, "montagem_local", {"arquivo": result["nome"] if "nome" in result else Path(result["caminho"]).name, "creditos": 0})
        return self._gravar(p)

    def _montar(self, id: str) -> None:
        """Montagem pedida pela conversa: corre na faixa de produção e conta o resultado no chat."""
        try:
            self.render(id)
        except (ValueError, RuntimeError, OSError) as e:
            self.responder(id, f"Não consegui montar agora: {str(e)[:300]}")
            return
        resultado = self.store.get(id).get("resultado") or {}
        pendencias, avisos = resultado.get("pendencias") or [], resultado.get("avisos") or []
        texto = ("Vídeo montado, mas com pendências:\n" + "\n".join(f"✗ {x}" for x in pendencias) if pendencias
                 else "Vídeo montado e conferido. Está aí embaixo.") + ("\nAtenção: " + " ".join(avisos) if avisos else "")
        self.responder(id, texto, [{"tipo": "resultado", "titulo": "Seu vídeo"}])

    def _narrar(self, p: dict, video: Path, saida: Path, segue: bool) -> dict:
        """Voz, legenda, setas, trilha e whoosh por cima do vídeo montado (o mesmo acabamento na prévia e no final)."""
        from studio.montagem_narrada import montar_narrado
        n = p["narracao"]
        # Sem seguir a voz: uma cena só acompanha a voz; várias mantêm a sequência inteira.
        minimo = float(p["duracao_final"]) if len(p.get("cortes") or []) > 1 else 0.0
        cortes_sfx = []
        if n.get("sfx") and layout_de(p) == "tela_cheia":
            t = 0.0
            for c in p["cortes"][:-1]:
                t += c["duracao"]
                cortes_sfx.append(round(t, 3))
        return montar_narrado(video, self.output(p["id"]) / n["audio"], n["palavras"], saida,
                              setas_ativas=n.get("setas", True), cta=n.get("cta", ""), minimo=minimo,
                              total=float(p["duracao_final"]) if segue else None,
                              estilo=n.get("estilo_legenda", "karaoke"), trilha=self.trilha(n.get("trilha", "")),
                              volume_trilha=float(n.get("volume_trilha", 0.2)), cortes_sfx=cortes_sfx)

    # ---------------- Prévia: o storyboard com os tempos, antes de gastar ----------------
    def partes_previa(self, p: dict) -> list[dict]:
        """Uma parte por corte, na ordem: tomada baixada no trecho do corte; senão o quadro com o movimento
        local (tomada paga ganha o selo "vídeo será gerado aqui"); sem quadro, cartão cinza com o título."""
        cortes = p.get("cortes") or [{"tomada": s["id"], "inicio": 0, "duracao": s["duracao"]} for s in p["tomadas"]]
        shots = {s["id"]: s for s in p["tomadas"]}
        ordem = list(dict.fromkeys(c["tomada"] for c in cortes))  # a numeração do storyboard

        def arquivo(valor: dict | None) -> Path | None:
            try:
                return self.asset(valor) if valor else None
            except ValueError:  # arquivo apagado da biblioteca: a cena cai para o próximo recurso
                return None

        partes = []
        for c in cortes:
            s = shots.get(c["tomada"])
            if not s:
                raise ValueError("Um corte aponta para uma cena que não existe mais. Revise os tempos.")
            parte = {"duracao": float(c["duracao"]), "titulo": f"Cena {ordem.index(s['id']) + 1}: {s['titulo']}"}
            video, quadro = arquivo(s.get("arquivo")), arquivo((s.get("imagens") or [None])[0])
            if video:
                parte.update(video=video, inicio=float(c.get("inicio") or 0), velocidade=float(c.get("velocidade") or 1),
                             recorte=c.get("recorte") or s.get("recorte"))
            elif quadro:
                parte.update(imagem=quadro, movimento=s.get("movimento_local") if not paga(s) else "aproximar", selo=paga(s))
            partes.append(parte)
        return partes

    def previa(self, id: str) -> dict:
        """Vídeo-rascunho local do storyboard atual, 540x960: cada cena na ordem dos cortes, nos tempos da voz,
        com a narração e a legenda quando houver. Sem créditos e sem Dreamina; não mexe no resultado.
        A assinatura é a da revisão: quando o storyboard muda, a interface sabe que a prévia ficou velha."""
        p = self.store.get(id)
        if not p["tomadas"]:
            raise ValueError("Ainda não há cenas para a prévia. Desenvolva a sequência no chat.")
        if layout_de(p) == "lado_a_lado":
            raise ValueError("A prévia com os tempos ainda é só para vídeos em tela cheia.")
        assinatura = revisao(p)["assinatura"]
        segue = self.segue_voz(p)
        p, avisos = self.alinhar_voz(p)
        n = p.get("narracao") or {}
        narrado = bool(n.get("audio") and n.get("palavras"))
        if self._falta_voz(p):
            avisos.append("A voz ainda não foi gerada: a prévia saiu muda, com os tempos do plano.")
        sem_quadro = [s["titulo"] for s in p["tomadas"] if not s.get("arquivo") and not s.get("imagens")]
        if sem_quadro:
            avisos.append("Sem quadro (cartão cinza): " + ", ".join(sem_quadro) + ".")
        pasta = self.output(id)
        marca = uuid.uuid4().hex[:8]
        trabalho, final = pasta / f"previa-{marca}-partes", pasta / f"previa-{marca}.mp4"
        try:
            muda = montar_previa(self.partes_previa(p), trabalho, trabalho / "sequencia.mp4", p.get("faixa"))
            if narrado:
                narrada = self._narrar(p, trabalho / "sequencia.mp4", trabalho / "narrado.mp4", segue)
                info = reduzir_previa(Path(narrada["caminho"]), final)
            else:
                (trabalho / "sequencia.mp4").replace(final)
                info = muda
        finally:
            shutil.rmtree(trabalho, ignore_errors=True)
        for antiga in pasta.glob("previa-*.mp4"):  # só a última prévia importa
            if antiga != final:
                try:
                    antiga.unlink(missing_ok=True)
                except OSError:  # o navegador ainda está tocando a anterior: fica para a próxima
                    pass
        previa = {"nome": final.name, "duracao": round(info["duracao"], 2), "assinatura": assinatura,
                  "avisos": avisos, "criado": agora()}
        self.store.event(id, "previa_local", {"arquivo": final.name, "creditos": 0})
        return self.store.update(id, lambda atual: {**atual, "previa": previa})

    # ---------------- Faixas de trabalho ----------------
    def _abrir_trabalho(self, id: str, faixa: str, rotulo: str) -> str:
        """Reserva vaga na faixa. Só conflita com trabalhos do mesmo tipo; as outras faixas seguem livres."""
        with self.lock:
            jobs = self.trabalhos.get(id, {})
            if sum(1 for j in jobs.values() if j["faixa"] == faixa) >= FAIXAS[faixa]:
                raise ValueError(FAIXA_OCUPADA[faixa])
            job = uuid.uuid4().hex[:8]
            self.trabalhos.setdefault(id, {})[job] = {"id": job, "faixa": faixa, "rotulo": rotulo, "iniciado": agora()}
            return job

    def _fechar_trabalho(self, id: str, job: str) -> None:
        with self.lock:
            self.trabalhos.get(id, {}).pop(job, None)
            if not self.trabalhos.get(id):
                self.trabalhos.pop(id, None)

    def ocupado(self, id: str, faixa: str | None = None) -> bool:
        jobs = self.trabalhos.get(id, {})
        return any(j["faixa"] == faixa for j in jobs.values()) if faixa else bool(jobs)

    def em_andamento(self, id: str) -> list[dict]:
        return sorted(self.trabalhos.get(id, {}).values(), key=lambda j: j["iniciado"])

    def com_estado(self, p: dict) -> dict:
        """Produção com o que está correndo agora e a situação de cada cena (conferência e revisão), calculadas
        aqui: a interface só mostra, nunca decide sozinha o que está aprovado."""
        return {**p, "ocupado": self.ocupado(p["id"]), "trabalhos": self.em_andamento(p["id"]),
                "situacoes": self.situacoes(p), "revisao_atual": revisao(p), "referencias_criativas": referencias(p)}

    def _gravar(self, p: dict, mensagens: list | None = None) -> dict:
        """Grava uma operação longa sem apagar o que a conversa escreveu no meio dela.

        A operação é dona de todos os campos menos a lista de mensagens: essa vem do registro fresco,
        e só as mensagens novas desta operação são acrescentadas."""
        novas = mensagens or []
        return self.store.update(p["id"], lambda atual: {**p, "mensagens": atual["mensagens"] + novas})

    def _com_retentativa(self, id: str, operacao, tentativas: int = 3):
        """Repete quando outra faixa gravou no meio: com paralelismo, a versão do plano pode virar entre ler e salvar."""
        for restantes in range(tentativas - 1, -1, -1):
            try:
                return operacao(self.store.get(id))
            except ValueError as e:
                if not restantes or "mudou em outra janela" not in str(e):
                    raise

    def exigir_livre(self, id: str, faixa: str = "producao") -> None:
        """Guarda das alterações de plano: só a faixa de produção impede mexer (cotação e geração dependem do plano)."""
        if self.ocupado(id, faixa):
            raise ValueError(FAIXA_OCUPADA[faixa])

    def background(self, id: str, function, *args, faixa: str = "producao", rotulo: str = "", job: str | None = None):
        # job: vaga já reservada por quem chamou (para só avisar no chat depois de saber que cabe)
        job = job or self._abrir_trabalho(id, faixa, rotulo or faixa)
        def work():
            try:
                function(id, *args)
            except Exception as e:
                erro = str(e)[:800]
                self.store.update(id, lambda atual: {**atual, "erro": erro})
            finally:
                self._fechar_trabalho(id, job)
        threading.Thread(target=work, daemon=True).start()
        return {"iniciado": True, "id": id, "trabalho": job, "faixa": faixa}


def achar_openclaw() -> str | None:
    import os
    import shutil
    candidatos = [shutil.which("openclaw"), str(Path(os.environ.get("APPDATA", "")) / "npm" / "openclaw.cmd")]
    return next((c for c in candidatos if c and Path(c).exists()), None)


def url_painel_base() -> str:
    import os
    ws = os.environ.get("OPENCLAW_URL", "") or "ws://127.0.0.1:18789"
    return ws.replace("wss://", "https://").replace("ws://", "http://").rstrip("/") + "/"


def abrir_painel_openclaw() -> dict:
    """Pede ao OpenClaw um link de entrada de uso único. Se ele não conseguir emitir (CLI sem pareamento,
    Gateway ainda subindo), abre o painel pelo endereço normal: o navegador já pareado entra direto;
    senão o próprio painel pede o acesso."""
    import subprocess
    base = url_painel_base()
    exe = achar_openclaw()
    motivo = ""
    if not exe:
        motivo = "comando 'openclaw' não encontrado neste computador"
    else:
        try:
            r = subprocess.run([exe, "dashboard", "--json"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60, stdin=subprocess.DEVNULL,
                               creationflags=0x08000000 if os_windows() else 0)
            bruto = r.stdout.strip()
            try:
                dados = json.loads(bruto[bruto.index("{"):bruto.rindex("}") + 1])
            except ValueError:
                dados = {}
            url = dados.get("browserUrl")
            if r.returncode == 0 and url:
                return {"url": url}
            motivo = str(dados.get("reason") or (r.stderr.strip().splitlines() or ["sem detalhes"])[-1])[:300]
        except subprocess.TimeoutExpired:
            motivo = "o OpenClaw demorou demais para gerar o link"
    return {"url": base, "aviso": f"Abri o painel pelo endereço normal ({motivo}). Se ele pedir acesso, "
                                  "rode abrir-openclaw.bat uma vez para parear este navegador."}


def os_windows() -> bool:
    import os
    return os.name == "nt"


def create_router(root: Path, ask, imagem=None, conversar=None) -> APIRouter:
    service = Processo(root, ask, imagem=imagem, conversar=conversar)
    router = APIRouter(prefix="/api/processo")
    router.service = service

    def get(id):
        try:
            return service.store.get(id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None

    def safe(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from None

    def estado(p: dict) -> dict:
        """Toda rota que devolve a produção diz também o que está correndo, para a interface mostrar sem travar."""
        return service.com_estado(p)

    @router.get("/status")
    def status():
        return {"dreamina": service.cli.status(), "planejamento": "openclaw", "api_planejamento_direta": False}

    @router.post("/openclaw/painel")
    def openclaw_panel():
        """Link do painel (Control UI) do OpenClaw: conectores, agentes, sessões. O próprio OpenClaw gera um
        acesso de uso único (vale 10 min); o token do Gateway nunca passa pelo Estúdio."""
        return safe(abrir_painel_openclaw)

    @router.get("/biblioteca")
    def library():
        return service.library()

    @router.get("/modelos")
    def models():
        return safe(service.cli.models)

    @router.get("/arquivo/{pasta}/{nome}")
    def asset(pasta: str, nome: str):
        return FileResponse(safe(service.asset, {"pasta": pasta, "nome": nome}))

    @router.post("/upload/{pasta}")
    async def upload(pasta: str, arquivo: UploadFile = File(...)):
        if pasta not in PASTAS:
            raise HTTPException(400, "Pasta inválida.")
        name = Path(arquivo.filename or "arquivo")
        allowed = VIDEO if pasta in ("movimentos", "saida") else IMAGEM
        if name.suffix.lower() not in allowed:
            raise HTTPException(400, "Formato não aceito nesta pasta.")
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", name.stem)[:80]
        folder = root / pasta
        folder.mkdir(exist_ok=True)
        dest = folder / f"{clean}-{uuid.uuid4().hex[:6]}{name.suffix.lower()}"
        total = 0
        try:
            with dest.open("xb") as f:
                while block := await arquivo.read(1024 * 1024):
                    total += len(block)
                    if total > 300 * 1024 * 1024:
                        raise ValueError("Arquivo maior que 300 MB.")
                    f.write(block)
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, str(e)) from None
        return {"pasta": pasta, "nome": dest.name}

    @router.get("/ocupado")
    def busy():
        """Usado pelo supervisor: só reinicia o servidor quando nada está em andamento (qualquer faixa)."""
        return {"ocupado": bool(service.trabalhos), "operacoes": sorted(service.trabalhos),
                "faixas": {id: [j["faixa"] for j in jobs.values()] for id, jobs in service.trabalhos.items()}}

    @router.get("/{id}/rascunho")
    def draft(id: str):
        return {"texto": service.rascunho(id), "pensando": id in service.chatting,
                "trabalhos": service.em_andamento(id)}

    @router.post("/{id}/usar-imagem")
    def use_image(id: str, request: UsarImagem):
        get(id)
        return estado(safe(service.usar_imagem, id, request))

    @router.post("/{id}/descartar")
    def discard(id: str, request: Descartar):
        get(id)
        return estado(safe(service.descartar, id, request.asset.model_dump()))

    @router.get("")
    def list_productions():
        return service.store.list()

    @router.post("")
    def create(request: Novo):
        return service.create(request.nome, request.formato)

    @router.get("/narracao/status")
    def narration_status():
        from studio.narracao import disponivel
        return disponivel()

    @router.get("/trilhas")
    def tracks():
        return service.trilhas()

    @router.get("/trilhas/{nome}")
    def track(nome: str):
        return FileResponse(safe(service.trilha, nome))

    @router.post("/trilhas")
    async def upload_track(arquivo: UploadFile = File(...)):
        nome = Path(arquivo.filename or "trilha.mp3")
        if nome.suffix.lower() not in AUDIO:
            raise HTTPException(400, "Envie a música em MP3, WAV, M4A ou OGG.")
        pasta = root / PASTA_TRILHAS
        pasta.mkdir(exist_ok=True)
        limpo = re.sub(r"[^a-zA-Z0-9_-]", "_", nome.stem)[:80]
        dest = pasta / f"{limpo}-{uuid.uuid4().hex[:6]}{nome.suffix.lower()}"
        dados = await arquivo.read()
        if len(dados) > 50 * 1024 * 1024:
            raise HTTPException(400, "Música maior que 50 MB.")
        dest.write_bytes(dados)
        return {"nome": dest.name}

    @router.put("/{id}/narracao/ajustes")
    def narration_settings(id: str, request: AjustesNarracao):
        get(id)
        return estado(safe(service.ajustar_narracao, id, request))

    # Ficha central: público, restrições, critérios, áudio e o caderno de referências com papel de cada uma
    @router.put("/{id}/caderno")
    def notebook(id: str, request: SalvarCaderno):
        get(id)
        return estado(safe(service.salvar_caderno, id, request))

    @router.post("/{id}/referencias/ativar")
    def use_reference(id: str, request: AtivarReferencia):
        get(id)
        return estado(safe(service.ativar_referencia, id, request))

    @router.post("/{id}/storyboard/revisar")
    def review_storyboard(id: str, request: RevisarStoryboard):
        get(id)
        return estado(safe(service.revisar_storyboard, id, request.assinatura))

    @router.post("/{id}/cenas/{cena}/conferir")
    def check_scene(id: str, cena: str, request: AceitarConferencia = AceitarConferencia()):
        get(id)
        return safe(service.background, id, service._reconferir, cena, request.material, faixa="midia",
                    rotulo="Conferindo a cena")

    @router.post("/{id}/cenas/{cena}/aceitar")
    def accept_scene(id: str, cena: str, request: AceitarConferencia):
        get(id)
        return estado(safe(service.aceitar_conferencia, id, cena, request.material))

    @router.post("/{id}/cenas/{cena}/refazer")
    def redo_frame(id: str, cena: str):
        p = get(id)
        s = next((t for t in p["tomadas"] if t["id"] == cena), None)
        if not s:
            raise HTTPException(404, "Cena não encontrada.")
        return estado(safe(service.refazer_quadro, p, s))

    @router.post("/{id}/narracao")
    def narration(id: str, request: Narracao):
        get(id)
        return safe(service.background, id, service.gerar_narracao, request, faixa="voz", rotulo="Gerando a voz")

    @router.post("/{id}/narracao/arquivo")
    async def narration_file(id: str, arquivo: UploadFile = File(...), texto: str = Form(""), setas: bool = Form(True)):
        get(id)
        nome = Path(arquivo.filename or "audio.mp3")
        if nome.suffix.lower() not in (".mp3", ".wav", ".m4a", ".ogg"):
            raise HTTPException(400, "Envie o áudio em MP3, WAV, M4A ou OGG.")
        dest = service.output(id) / f"narracao-{uuid.uuid4().hex[:6]}{nome.suffix.lower()}"
        dest.write_bytes(await arquivo.read())
        return safe(service.background, id, service.salvar_audio_narracao, dest, texto[:800], setas,
                    faixa="voz", rotulo="Sincronizando o áudio")

    @router.get("/{id}/narracao/audio")
    def narration_audio(id: str):
        n = get(id).get("narracao") or {}
        if not n.get("audio"):
            raise HTTPException(404, "Sem narração.")
        return FileResponse(safe(lambda: service.output(id) / Path(n["audio"]).name))

    @router.get("/{id}")
    def production(id: str):
        return estado(get(id))

    @router.put("/{id}/plano")
    def plan(id: str, request: SalvarPlano):
        return estado(safe(service.save_plan, get(id), request.plano.model_dump(), request.versao))

    @router.post("/{id}/conversa")
    def chat(id: str, request: Mensagem):
        get(id)
        return estado(safe(service.chat, id, request))

    @router.post("/{id}/referencia")
    def reference(id: str, request: Selecao):
        get(id)
        return estado(safe(service.select_reference, id, request))

    @router.post("/{id}/cotar")
    def quote(id: str, request: Cotar = Cotar()):
        get(id)
        return safe(service.background, id, service.prepare_quote, request.tomadas,
                    faixa="producao", rotulo="Calculando o custo")

    @router.post("/{id}/gerar")
    def generate(id: str, request: Gerar, http: Request):
        get(id)
        if http.headers.get("X-Estudio-Humano") != "sim":
            raise HTTPException(403, "A geração paga precisa do botão de aprovação do Estúdio.")
        return safe(service.background, id, service.generate, request,
                    faixa="producao", rotulo="Enviando as tomadas")

    @router.post("/{id}/acompanhar")
    def sync(id: str):
        get(id)
        return safe(service.background, id, service.sync, faixa="producao", rotulo="Acompanhando as tomadas")

    @router.post("/{id}/reusar")
    def reuse(id: str, request: Reuso):
        safe(service.exigir_livre, id)
        return estado(safe(service.reuse, get(id), request.tomada, request.asset.model_dump()))

    @router.post("/{id}/montar")
    def render(id: str):
        get(id)
        return safe(service.background, id, service.render, faixa="producao", rotulo="Montando o vídeo")

    @router.post("/{id}/previa")
    def preview(id: str):
        """Prévia com os tempos: local e grátis, nunca chama o Dreamina."""
        get(id)
        return safe(service.background, id, service.previa, faixa="producao", rotulo="Montando a prévia")

    @router.get("/{id}/previa")
    def preview_file(id: str):
        name = (get(id).get("previa") or {}).get("nome", "")
        if not name or Path(name).name != name:
            raise HTTPException(404, "Ainda não há prévia.")
        path = service.output(id) / name
        if not path.is_file():
            raise HTTPException(404, "Arquivo da prévia não encontrado.")
        return FileResponse(path, media_type="video/mp4")

    @router.get("/{id}/resultado")
    def result(id: str):
        p = get(id)
        name = p.get("resultado", {}).get("nome", "")
        if not name or Path(name).name != name:
            raise HTTPException(404, "Ainda não há vídeo montado.")
        path = service.output(id) / name
        if not path.is_file():
            raise HTTPException(404, "Arquivo final não encontrado.")
        return FileResponse(path, media_type="video/mp4", filename=f"{id}-{name}")

    @router.get("/{id}/registro")
    def record(id: str):
        return {"producao": get(id), "eventos": service.store.events(id)}

    return router
