"""Produção conversacional, sem pilares, avaliações ou métricas de rede social."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from studio.dreamina import Dreamina
from studio.montagem import montar, montar_sequencia, preparar_referencia, probe, sha256
from studio.producao_store import Store, agora

PASTAS = ("persona", "base", "pecas", "cenarios", "movimentos", "saida", "anexos", "quadros", "referencias")
# Destinos de imagem gerada a partir do que o Breno cola no chat
DESTINOS_IMAGEM = ("cenarios", "pecas", "base", "persona", "quadros")
VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}


class Asset(BaseModel):
    pasta: Literal["persona", "base", "pecas", "cenarios", "movimentos", "saida", "anexos", "quadros", "referencias"]
    nome: str = Field(min_length=1, max_length=180, pattern=r"^[^/\\]+$")


class Tomada(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    titulo: str = Field(min_length=1, max_length=100)
    # cheia: tela inteira. esquerda/direita: só no layout lado_a_lado.
    lado: Literal["esquerda", "direita", "cheia"] = "cheia"
    # None: a modelo aprovada entra se a produção usa a Ellie. False: tomada sem a Ellie (paisagem, objeto, outro assunto).
    ellie: bool | None = None
    modelo: str = "seedance_2.0_fast"
    modo: Literal["m2v", "first_last_frame"] = "m2v"
    resolucao: Literal["480p", "720p", "1080p"] = "720p"
    duracao: int = Field(default=9, ge=4, le=30)
    prompt: str = Field(min_length=10, max_length=14500)
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
    duracao_final: int = Field(default=9, ge=1, le=90)
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


NARRACAO_VAZIA = {"texto": "", "voz": "", "setas": True, "cta": "", "audio": None, "palavras": []}
# Movimento neutro para quando uma imagem vira quadro inicial antes de a conversa descrever a cena
PROMPT_QUADRO = ("Animate the attached first frame as one continuous vertical 9:16 shot with subtle, natural motion. "
                 "No text, no captions, no cuts.")


def layout_de(p: dict) -> str:
    """Produções antigas não têm layout: o formato da Ellie era lado a lado; o narrado, tela cheia."""
    if p.get("layout"):
        return p["layout"]
    return "lado_a_lado" if p.get("formato", "duas_tomadas") == "duas_tomadas" and p.get("tomadas") else "tela_cheia"


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


class Gerar(BaseModel):
    cotacao_id: str
    teto: int = Field(gt=0)


class Cotar(BaseModel):
    tomadas: list[str] | None = None


class UsarImagem(BaseModel):
    asset: Asset
    como: Literal["quadro", "recriar"]


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
        self.busy: set[str] = set()
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
            if p.get("layout"):
                continue
            p["layout"] = layout_de(p)
            if p.get("formato") == "narrado":
                p["faixa"] = Faixa().model_dump()
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
            "narracao": dict(NARRACAO_VAZIA)})

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
        for shot in p["tomadas"]:
            data = Tomada(**shot).model_dump(exclude={"recorte"})
            data["conteudo_referencias"] = [sha256(self.asset(a)) for a in shot["imagens"]]
            if shot.get("movimento"):
                data["conteudo_movimento"] = sha256(self.asset(shot["movimento"]))
            payload.append(data)
        if p.get("master"):
            payload.append({"master_sha256": sha256(self.asset(p["master"]))})
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def save_plan(self, p: dict, plan: dict, expected: int, interno: bool = False) -> dict:
        # interno: chamado pela própria operação em segundo plano (ex.: imagem gerada virando quadro), que é quem está ocupando
        if not interno and (p["id"] in self.busy or (p["id"] in self.chatting and self.chatting[p["id"]] != threading.get_ident())):
            raise ValueError("Aguarde a operação atual terminar antes de alterar o plano.")
        plan = dict(plan)
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
        if ids and sum(round(c["duracao"] * 30) for c in validated["cortes"]) != validated["duracao_final"] * 30:
            raise ValueError("Os cortes precisam preencher a duração final.")
        old = {s["id"]: s for s in p["tomadas"]}
        fields = set(Tomada.model_fields) - {"recorte", "titulo"}
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
        p.update(validated)
        return self.store.save(p, expected)

    def message(self, id: str, request: Mensagem) -> dict:
        p = self.store.get(id)
        if id in self.busy:
            raise ValueError("Uma operação está em andamento. Aguarde para continuar esta conversa.")
        if request.selecao:
            p = self.select_reference(id, request.selecao)
        text = request.texto.strip() or ("Escolhi " + request.selecao.asset.nome if request.selecao else "")
        anexos = [a.model_dump() for a in request.anexos]
        for a in anexos:
            self.asset(a)  # valida que o arquivo existe na biblioteca
        if not text and not anexos:
            raise ValueError("Escreva sua ideia ou escolha uma referência.")
        user = {"id": uuid.uuid4().hex, "papel": "user", "texto": text, "criado": agora()}
        if anexos:
            user["anexos"] = anexos
            p["anexos_pendentes"] = anexos
            p["anexos_idade"] = 0
        elif p.get("anexos_pendentes"):
            # Imagens coladas valem para a mensagem em que foram coladas e a seguinte (resposta a um quiz/pergunta)
            p["anexos_idade"] = p.get("anexos_idade", 0) + 1
            if p["anexos_idade"] >= 2:
                p["anexos_pendentes"] = []
        p["mensagens"].append(user)
        p = self.store.save(p)
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
        context["usa_ellie"] = bool(p.get("master"))
        context["ellie_disponivel"] = (self.root / "persona" / "ellie-aprovada.png").exists()
        n = p.get("narracao") or {}
        context["narracao"] = {"texto": n.get("texto", ""), "cta": n.get("cta", ""), "audio_pronto": bool(n.get("audio")),
                               "setas": n.get("setas", True)}
        photos: list[Path] = []
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

    def turno_ia(self, p: dict) -> dict:
        id = p["id"]
        context, fotos = self._contexto(p)
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
            response = extrair_json(bruto)
            message = str(response.get("mensagem_pt", "")).strip()
            if not message:
                raise ValueError("O OpenClaw não retornou uma mensagem.")
            if isinstance(response.get("ellie"), bool):
                p = self.store.save(self.usar_ellie(p, response["ellie"]))
            if response.get("plano"):
                p = self.save_plan(p, response["plano"], p["versao"])
            texto_mudou = False
            if isinstance(response.get("narracao"), dict):
                pedido_n = response["narracao"]
                atual_n = {**NARRACAO_VAZIA, **(p.get("narracao") or {})}
                if "cta" in pedido_n:
                    atual_n["cta"] = str(pedido_n.get("cta") or "")[:200]
                if "texto" in pedido_n:
                    novo = str(pedido_n.get("texto") or "")[:800]
                    if novo != atual_n.get("texto"):
                        texto_mudou = True
                        # Texto novo invalida o áudio antigo (a voz é gerada só pelo botão, que usa créditos do ElevenLabs)
                        atual_n.update(texto=novo, audio=None, palavras=[])
                p["narracao"] = atual_n
            cards = self.cards(response.get("blocos", []), library)
            # Narrado: o cartão da narração só aparece quando o texto muda (ou quando ainda não há áudio e ela fala do texto)
            sem_audio = not (p.get("narracao") or {}).get("audio")
            if texto_mudou and (p.get("narracao") or {}).get("texto"):
                if not any(c.get("tipo") == "narracao" for c in cards):
                    cards.insert(0, {"tipo": "narracao", "titulo": "Texto da narração"})
            elif not (sem_audio and re.search(r"narra[çc][ãa]o|roteiro", message, re.I)):
                cards = [c for c in cards if c.get("tipo") != "narracao"]
            resposta = {"id": uuid.uuid4().hex, "papel": "assistant", "texto": message, "blocos": cards,
                        "criado": agora(), "ia": meta}
            p["mensagens"].append(resposta)
            p["erro"] = ""
            # O que a IA já viu: o estado DEPOIS da resposta dela (o plano que ela mesma propôs não precisa voltar)
            depois, _ = self._contexto(p)
            p["ia_sessao"] = {"geracao": geracao, "modelo": meta.get("modelo") or "padrao", "h_instr": h["instr"],
                              "h_estado": self._hash(depois), "h_lib": h["lib"], "h_fotos": h["fotos"],
                              "ultima_msg": resposta["id"],
                              "anexos": [a["nome"] for a in p.get("anexos_pendentes") or []]}
            self.store.event(id, "turno_ia", meta)
            p = self.store.save(p)
            if response.get("acao") == "montar" and p["tomadas"] and all(s.get("arquivo") for s in p["tomadas"]):
                p = self.render(id)
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
                return self.pedir_imagem(p, destino, str(pedido.get("prompt", ""))[:1200], refs,
                                         bool(pedido.get("usar_ellie")), aviso=False)
        except Exception as e:
            p["erro"] = "Não consegui continuar pelo OpenClaw. Confira a conexão e a assinatura.\n" + str(e).replace(" | ", "\n")[:1500]
            p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "assistant", "texto": p["erro"], "blocos": [{"tipo": "conexao"}], "criado": agora()})
        finally:
            self.rascunhos.pop(id, None)
        return self.store.save(p)

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

    def responder(self, p: dict, texto: str, blocos: list | None = None) -> dict:
        p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "assistant", "texto": texto,
                               "blocos": blocos or [], "criado": agora(), "local": True})
        p["erro"] = ""
        return self.store.save(p)

    def rota_rapida(self, p: dict, text: str, colou_agora: bool) -> dict | None:
        """Resolve sem IA o que for óbvio: destino de imagem colada, variação da última imagem, ou quiz de 1 clique."""
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
                p["anexos_pendentes"] = []
                nomes = ", ".join(a["nome"] for a in pendentes)
                return self.responder(p, f"Guardei na biblioteca, em anexos: {nomes}.")
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
        if ultimo and text and pede_variacao(text) and len(text) < 80:
            refs = [a for a in ultimo.get("referencias", []) if self._existe(a)]
            return self.pedir_imagem(p, ultimo["pasta"], ultimo.get("descricao", ""), refs, ultimo.get("usar_ellie", False))
        return None

    def _existe(self, a: dict) -> bool:
        try:
            self.asset(a)
            return True
        except (ValueError, Exception):
            return False

    def pedir_imagem(self, p: dict, pasta: str, descricao: str, refs: list[dict], usar_ellie: bool, aviso: bool = True) -> dict:
        """Dispara a geração de imagem em segundo plano; o chat continua livre e mostra o resultado ao terminar."""
        if not self.imagem:
            return self.responder(p, "A geração de imagem não está ligada neste servidor.")
        rotulo = {"cenarios": "o cenário", "pecas": "a roupa", "base": "a Ellie com essa roupa", "persona": "a imagem",
                  "quadros": "o quadro inicial"}[pasta]
        p["ultimo_pedido_imagem"] = {"pasta": pasta, "descricao": descricao, "referencias": refs, "usar_ellie": usar_ellie}
        p["anexos_pendentes"] = []
        if aviso:
            p = self.responder(p, f"Gerando {rotulo} com o GPT Image. Leva de 30 s a 1,5 min; o resultado aparece aqui.")
        else:
            p = self.store.save(p)
        self.background(p["id"], self._gerar_imagem, pasta, descricao, refs, usar_ellie, do_chat=True)
        return {**self.store.get(p["id"]), "ocupado": True}

    def _gerar_imagem(self, id: str, pasta: str, descricao: str, refs: list[dict], usar_ellie: bool):
        caminhos = [self.asset(a) for a in refs]
        try:
            nome = self.imagem(pasta, descricao, "", caminhos, usar_ellie)
        except Exception as e:
            detalhe = getattr(e, "detail", None) or str(e)
            p = self.store.get(id)
            self.responder(p, f"A imagem não saiu: {str(detalhe)[:300]}. Peça de novo quando quiser.", [{"tipo": "conexao"}])
            return
        p = self.store.get(id)
        self.store.event(id, "imagem_gerada", {"pasta": pasta, "nome": nome, "referencias": [a["nome"] for a in refs]})
        # Só o que o próprio sistema gerou pode ser descartado (nunca a modelo aprovada ou arquivos do Breno)
        p.setdefault("geradas", []).append({"pasta": pasta, "nome": nome})
        if pasta == "quadros":
            try:
                p = self._definir_quadro(p, {"pasta": pasta, "nome": nome}, interno=True)
            except ValueError as e:  # a imagem existe: avisa em vez de sumir com o resultado
                p = self.store.get(id)
                self.responder(p, f"A imagem ficou pronta, mas não entrou como quadro: {e}",
                               [{"tipo": "imagem", "titulo": "", "pasta": pasta, "nomes": [nome], "gerada": True}])
                return
        self.responder(p, "Pronto. Se não ficou bom, peça outra versão ou descarte.",
                       [{"tipo": "imagem", "titulo": "", "pasta": pasta, "nomes": [nome], "gerada": True}])

    # ---------------- Referências do Pinterest ----------------
    def buscar_referencias(self, p: dict, termo: str, quantidade: int = 10, aviso: bool = True) -> dict:
        quantidade = max(1, min(16, quantidade))
        if aviso:
            p = self.responder(p, f"Buscando “{termo}” no Pinterest. Leva uns 20 a 60 s; as imagens aparecem aqui.")
        self.background(p["id"], self._buscar_referencias, termo, quantidade, do_chat=True)
        return {**self.store.get(p["id"]), "ocupado": True}

    def _buscar_referencias(self, id: str, termo: str, quantidade: int):
        try:
            nomes = self.pinterest(termo, self.root / "referencias", quantidade)
        except Exception as e:
            self.responder(self.store.get(id), f"A busca no Pinterest não deu certo: {str(e)[:300]}")
            return
        p = self.store.get(id)
        self.store.event(id, "pinterest", {"termo": termo, "imagens": len(nomes)})
        if not nomes:
            self.responder(p, f"O Pinterest não devolveu imagens para “{termo}”. Tente outro termo (em inglês costuma render mais).")
            return
        self.responder(p, f"{len(nomes)} referências do Pinterest para “{termo}”. Escolha uma para virar quadro inicial "
                          "ou para o GPT recriar.", [{"tipo": "imagem", "titulo": "", "pasta": "referencias", "nomes": nomes,
                                                     "referencias": True, "termo": termo}])

    def usar_imagem(self, id: str, pedido: UsarImagem) -> dict:
        p = self.store.get(id)
        asset = pedido.asset.model_dump()
        self.asset(asset)
        if pedido.como == "quadro":
            return self.usar_como_quadro(p, asset)
        return self.pedir_imagem(p, "quadros", "Recreate this reference as an original cinematic vertical 9:16 first frame. "
                                 "Keep the mood, composition and light; do not copy watermarks or text.", [asset], False)

    def _definir_quadro(self, p: dict, asset: dict, interno: bool = False) -> dict:
        """Coloca a imagem como quadro inicial: na primeira tomada ainda sem imagem, senão substitui a da última
        tomada não enviada; sem tomada disponível, abre uma cena nova (invalida cotação antiga, se houver)."""
        plano = {k: p.get(k) for k in CAMPOS_PLANO}
        plano["layout"] = layout_de(p)
        tomadas = [dict(s) for s in p["tomadas"]]
        livres = [s for s in tomadas if not s.get("submit_id") and not s.get("arquivo")]
        alvo = next((s for s in livres if not s["imagens"]), livres[-1] if livres else None)
        if alvo:
            alvo["imagens"] = [asset]
            if not alvo.get("movimento"):
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
                    plano["duracao_final"] = int(plano["duracao_final"]) + 10
        plano["tomadas"] = tomadas
        return self.save_plan(p, plano, p["versao"], interno=interno)

    def usar_como_quadro(self, p: dict, asset: dict) -> dict:
        p["anexos_pendentes"] = []
        p = self._definir_quadro(p, asset)
        return self.responder(p, "Pronto, essa imagem é o quadro inicial da cena. Quando quiser, consulte o custo da animação.",
                              [{"tipo": "custo", "titulo": "Produção da cena"}])

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
        p = self.store.get(id)
        p["anexos_pendentes"] = [a for a in p.get("anexos_pendentes") or [] if a != asset]
        for m in p["mensagens"]:
            for b in m.get("blocos") or []:
                if b.get("tipo") == "imagem" and b.get("pasta") == asset["pasta"] and asset["nome"] in (b.get("nomes") or []):
                    b["descartado"] = True
            if asset in (m.get("anexos") or []):
                m["anexos"] = [a for a in m["anexos"] if a != asset]
        self.store.event(id, "descartado", asset)
        return self.store.save(p)

    # ---------------- Narração (formato narrado) ----------------
    def gerar_narracao(self, id: str, pedido: Narracao) -> None:
        from studio.narracao import gerar_elevenlabs
        p = self.store.get(id)
        texto = pedido.texto.strip() or (p.get("narracao") or {}).get("texto", "")
        if not texto:
            raise ValueError("Escreva o texto da narração.")
        nome = f"narracao-{uuid.uuid4().hex[:6]}.mp3"
        palavras = gerar_elevenlabs(texto, self.output(id) / nome, pedido.voz)
        p = self.store.get(id)
        p["narracao"] = {**NARRACAO_VAZIA, **(p.get("narracao") or {}), "texto": texto, "voz": pedido.voz, "setas": pedido.setas,
                         "audio": nome, "palavras": palavras, "origem": "elevenlabs"}
        if pedido.cta.strip():
            p["narracao"]["cta"] = pedido.cta.strip()
        self.store.event(id, "narracao", {"origem": "elevenlabs", "palavras": len(palavras)})
        self.responder(p, f"Voz pronta ({len(palavras)} palavras). Ouça no cartão da narração.", [{"tipo": "narracao"}])

    def salvar_audio_narracao(self, id: str, origem: Path, texto: str, setas: bool) -> None:
        from studio.narracao import alinhar_arquivo
        palavras = alinhar_arquivo(origem, texto)
        p = self.store.get(id)
        p["narracao"] = {**NARRACAO_VAZIA, **(p.get("narracao") or {}), "texto": texto or " ".join(w["p"] for w in palavras),
                         "setas": setas, "audio": origem.name, "palavras": palavras, "origem": "arquivo"}
        self.store.event(id, "narracao", {"origem": "arquivo", "palavras": len(palavras)})
        self.responder(p, f"Áudio recebido e sincronizado ({len(palavras)} palavras).", [{"tipo": "narracao"}])

    def chat(self, id: str, request: Mensagem) -> dict:
        with self.lock:
            if id in self.busy or id in self.chatting:
                raise ValueError("Esta conversa já está processando um pedido.")
            self.chatting[id] = threading.get_ident()
        try:
            return self.message(id, request)
        finally:
            with self.lock:
                self.chatting.pop(id, None)

    @staticmethod
    def cards(values: list, library: dict) -> list[dict]:
        cards = []
        for item in values[:4]:
            kind = item.get("tipo")
            if kind not in ("galeria", "quiz", "plano", "custo", "resultado", "upload", "edicao", "imagem", "narracao"):
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
        pending = [s for s in p["tomadas"] if not s.get("arquivo") and not s.get("submit_id")]
        if selected is not None:
            if not selected or not set(selected).issubset({s['id'] for s in pending}):
                raise ValueError("Escolha somente tomadas novas deste plano para cotar.")
            pending = [s for s in pending if s['id'] in selected]
        if not pending:
            raise ValueError("Não há novas tomadas para cotar. Use os arquivos existentes para montar.")
        if len(pending) > 3 and not p.get("permitir_plano_extenso"):
            raise ValueError("O primeiro lote aceita até três tomadas. Simplifique antes de cotar para evitar o custo do V7.")
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
            p = self.store.save(p)
        if not p.get("canvas_url"):
            created = self.cli.canvas(p["canvas_id"], p["nome"])
            p["canvas_url"] = created.get("webUrl", "")
            p = self.store.save(p)

        def imported(path: Path, media: str) -> str:
            kind = "external_generated" if media == "image" else "local_upload"
            key = sha256(path)
            item = p["imports"].setdefault(key, {"resource": str(uuid.uuid4()), "submit": str(uuid.uuid4())})
            if not item.get("imported"):
                item.pop("node", None)  # IDs inventados por versões antigas eram recusados pela CLI
            self.store.save(p)
            if not item.get("uploaded"):
                result = self.cli.upload(path, p["canvas_id"], item["resource"], kind)
                if result.get("resourceId") != item["resource"]:
                    raise ValueError("O upload não corresponde à referência planejada.")
                item["uploaded"] = True
                self.store.save(p)
            if not item.get("imported"):
                criado = self.cli.import_node(media, item["resource"], None, p["canvas_id"], item["submit"], path.stem, kind)
                item["node"] = Dreamina.node_id(criado)
                if not item["node"]:
                    raise ValueError("A CLI criou a referência mas não devolveu o node_id. Resposta: " + json.dumps(criado)[:300])
                item["imported"] = True
                self.store.save(p)
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
            self.store.save(p)
        quote = self.cli.quote(p["canvas_id"], [s["node_id"] for s in pending])
        p["cotacao"] = {"id": uuid.uuid4().hex, "hash": fingerprint, "criado": agora(), "draft_version": quote.get("draftVersion"),
                         "total": quote["totalMaxCredits"], "itens": quote["items"], "tomadas": [s['id'] for s in pending], "unidade": "creditos_dreamina"}
        p["autorizacao"] = None
        p["status"] = "orcamento"
        p["erro"] = ""
        self.store.event(id, "cotacao", {"total": quote["totalMaxCredits"], "hash": fingerprint})
        return self.store.save(p)

    def generate(self, id: str, request: Gerar) -> dict:
        p = self.store.get(id)
        q = p.get("cotacao")
        if q and q.get("executada"):
            raise ValueError("As tomadas deste lote já foram enviadas. Use Acompanhar.")
        if p.get("exemplo"):
            raise ValueError("O exemplo é histórico. Crie um novo vídeo para gerar outra versão.")
        if not q or request.cotacao_id != q["id"] or q["hash"] != self.generation_hash(p):
            raise ValueError("O plano mudou ou a cotação venceu. Consulte o custo novamente.")
        if request.teto < q["total"]:
            raise ValueError("O custo ultrapassa o teto que você autorizou.")
        pending = [s for s in p["tomadas"] if not s.get("arquivo") and not s.get("submit_id")]
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
        self.store.save(p)  # Identidade e reserva existem ANTES da chamada que pode gastar.
        self.store.event(id, "autorizacao", {"teto": request.teto, "cotacao_id": q["id"]})
        try:
            self.cli.run(p["canvas_id"], pending, request.teto)
            for shot in pending:
                shot["estado"] = "enviado"
            p["erro"] = ""
        except Exception:
            p["status"] = "envio_incerto"
            p["erro"] = "O envio não foi confirmado. Os identificadores estão preservados. Use Acompanhar; não gerar novamente."
        return self.store.save(p)

    def sync(self, id: str) -> dict:
        p = self.store.get(id)
        if p.get("status") == "concluido" and p.get("resultado") and all(s.get("arquivo") for s in p["tomadas"]):
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
                self.store.save(p)
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
            self.store.save(p)
        self._avisar_tomadas(p, prontas_antes, falhas_antes)
        if all(s.get("arquivo") for s in p["tomadas"]):
            p["status"] = "pronto_para_montar"
            self.store.save(p)
            if self._falta_voz(p):
                return p  # monta quando a voz estiver pronta
            return self.render(id)
        elif any(s.get("estado") in ("failed", "canceled", "cancelled") for s in p["tomadas"]):
            p["status"] = "parcial"
            p["erro"] = "Uma tomada não concluiu. Os resultados e custos conhecidos foram preservados. Nenhuma repetição foi feita; estorno ainda não foi confirmado."
        elif not any(s.get("submit_id") and not s.get("arquivo") for s in p["tomadas"]):
            p["status"] = "proxima_tomada"
        return self.store.save(p)

    def _avisar_tomadas(self, p: dict, prontas_antes: set, falhas_antes: set):
        """Avisa no chat, sem IA, quando uma tomada fica pronta ou falha, com o cartão de produção atualizado."""
        novas = [s for s in p["tomadas"] if s.get("arquivo") and s["id"] not in prontas_antes]
        falhas = [s for s in p["tomadas"] if s.get("estado") in ("failed", "canceled", "cancelled") and s["id"] not in falhas_antes]
        if not novas and not falhas:
            return
        faltam = [s["titulo"] for s in p["tomadas"] if not s.get("arquivo")]
        partes = []
        for s in novas:
            gasto = f", {s['creditos_registrados']} créditos" if isinstance(s.get("creditos_registrados"), (int, float)) else ""
            partes.append(f"A tomada \"{s['titulo']}\" ficou pronta ({s.get('info', {}).get('duracao', s['duracao']):.0f}s{gasto}). Assista abaixo antes de seguir.")
        for s in falhas:
            partes.append(f"A tomada \"{s['titulo']}\" não concluiu no Dreamina. Nada foi repetido; os custos conhecidos ficaram registrados.")
        sem_voz = self._falta_voz(p)
        partes.append(("Falta: " + ", ".join(faltam) + ".") if faltam else
                      "Tomadas prontas. Falta a voz: gere ou envie no cartão da narração, depois monte." if sem_voz else
                      "Todas as tomadas estão prontas; vou montar o vídeo.")
        p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "assistant", "texto": " ".join(partes),
                               "blocos": [{"tipo": "custo", "titulo": "Produção das tomadas"}], "criado": agora(), "local": True})
        self.store.save(p)

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
        return self.store.save(p)

    def select_reference(self, id: str, selection: Selecao) -> dict:
        p = self.store.get(id)
        if id in self.busy or (id in self.chatting and self.chatting[id] != threading.get_ident()):
            raise ValueError("Aguarde a operação atual.")
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
        return self.store.save(p)

    @staticmethod
    def _falta_voz(p: dict) -> bool:
        n = p.get("narracao") or {}
        return bool(n.get("texto", "").strip()) and not n.get("audio")

    def render(self, id: str) -> dict:
        p = self.store.get(id)
        if not p["tomadas"] or not all(s.get("arquivo") for s in p["tomadas"]):
            raise ValueError("Ainda faltam tomadas prontas para montar.")
        n = p.get("narracao") or {}
        if self._falta_voz(p):
            raise ValueError("Falta a narração: gere a voz ou envie o áudio (ou apague o texto da narração) antes de montar.")
        if layout_de(p) == "lado_a_lado":
            result = montar(p, self.asset, self.output(id))
        else:
            if not p.get("cortes"):
                raise ValueError("O plano não tem cortes.")
            result = montar_sequencia(p, self.asset, self.output(id))
        if n.get("audio") and n.get("palavras"):
            from studio.montagem_narrada import montar_narrado
            numero = sum(1 for f in self.output(id).glob("narrado-*.mp4")) + 1
            # Uma cena só: o vídeo acompanha a voz. Várias cenas: mantém a sequência inteira.
            minimo = float(p["duracao_final"]) if len(p.get("cortes") or []) > 1 else 0.0
            result = montar_narrado(Path(result["caminho"]), self.output(id) / n["audio"], n["palavras"],
                                    self.output(id) / f"narrado-{numero}.mp4", setas_ativas=n.get("setas", True),
                                    cta=n.get("cta", ""), minimo=minimo)
        p["resultado"] = {**result, "nome": Path(result["caminho"]).name}
        p["status"] = "concluido"
        p["erro"] = ""
        self.store.event(id, "montagem_local", {"arquivo": result["nome"] if "nome" in result else Path(result["caminho"]).name, "creditos": 0})
        return self.store.save(p)

    def background(self, id: str, function, *args, do_chat: bool = False):
        with self.lock:
            # do_chat: disparado de dentro do próprio turno de conversa (que ainda segura self.chatting)
            if id in self.busy or (id in self.chatting and not do_chat):
                raise ValueError("Esta produção já está processando uma operação.")
            self.busy.add(id)
        def work():
            try:
                function(id, *args)
            except Exception as e:
                p = self.store.get(id)
                p["erro"] = str(e)[:800]
                self.store.save(p)
            finally:
                with self.lock:
                    self.busy.discard(id)
        threading.Thread(target=work, daemon=True).start()
        return {"iniciado": True, "id": id}


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

    def safe(function, *args):
        try:
            return function(*args)
        except (ValueError, RuntimeError, OSError) as e:
            raise HTTPException(400, str(e)) from None

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
        """Usado pelo supervisor: só reinicia o servidor quando nada está em andamento."""
        return {"ocupado": bool(service.busy or service.chatting),
                "operacoes": sorted(service.busy | set(service.chatting))}

    @router.get("/{id}/rascunho")
    def draft(id: str):
        return {"texto": service.rascunho(id), "pensando": id in service.chatting}

    @router.post("/{id}/usar-imagem")
    def use_image(id: str, request: UsarImagem):
        get(id)
        return safe(service.usar_imagem, id, request)

    @router.post("/{id}/descartar")
    def discard(id: str, request: Descartar):
        get(id)
        return safe(service.descartar, id, request.asset.model_dump())

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

    @router.post("/{id}/narracao")
    def narration(id: str, request: Narracao):
        get(id)
        return safe(service.background, id, service.gerar_narracao, request)

    @router.post("/{id}/narracao/arquivo")
    async def narration_file(id: str, arquivo: UploadFile = File(...), texto: str = Form(""), setas: bool = Form(True)):
        get(id)
        nome = Path(arquivo.filename or "audio.mp3")
        if nome.suffix.lower() not in (".mp3", ".wav", ".m4a", ".ogg"):
            raise HTTPException(400, "Envie o áudio em MP3, WAV, M4A ou OGG.")
        dest = service.output(id) / f"narracao-{uuid.uuid4().hex[:6]}{nome.suffix.lower()}"
        dest.write_bytes(await arquivo.read())
        return safe(service.background, id, service.salvar_audio_narracao, dest, texto[:800], setas)

    @router.get("/{id}/narracao/audio")
    def narration_audio(id: str):
        n = get(id).get("narracao") or {}
        if not n.get("audio"):
            raise HTTPException(404, "Sem narração.")
        return FileResponse(safe(lambda: service.output(id) / Path(n["audio"]).name))

    @router.get("/{id}")
    def production(id: str):
        return {**get(id), "ocupado": id in service.busy or id in service.chatting}

    @router.put("/{id}/plano")
    def plan(id: str, request: SalvarPlano):
        return safe(service.save_plan, get(id), request.plano.model_dump(), request.versao)

    @router.post("/{id}/conversa")
    def chat(id: str, request: Mensagem):
        get(id)
        return safe(service.chat, id, request)

    @router.post("/{id}/referencia")
    def reference(id: str, request: Selecao):
        get(id)
        return safe(service.select_reference, id, request)

    @router.post("/{id}/cotar")
    def quote(id: str, request: Cotar = Cotar()):
        get(id)
        return safe(service.background, id, service.prepare_quote, request.tomadas)

    @router.post("/{id}/gerar")
    def generate(id: str, request: Gerar, http: Request):
        get(id)
        if http.headers.get("X-Estudio-Humano") != "sim":
            raise HTTPException(403, "A geração paga precisa do botão de aprovação do Estúdio.")
        return safe(service.background, id, service.generate, request)

    @router.post("/{id}/acompanhar")
    def sync(id: str):
        get(id)
        return safe(service.background, id, service.sync)

    @router.post("/{id}/reusar")
    def reuse(id: str, request: Reuso):
        if id in service.busy or id in service.chatting:
            raise HTTPException(409, "Aguarde a operação atual.")
        return safe(service.reuse, get(id), request.tomada, request.asset.model_dump())

    @router.post("/{id}/montar")
    def render(id: str):
        get(id)
        return safe(service.background, id, service.render)

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
