"""Produção conversacional, sem pilares, avaliações ou métricas de rede social."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from studio.dreamina import Dreamina
from studio.montagem import montar, preparar_referencia, probe, sha256
from studio.producao_store import Store, agora

PASTAS = ("persona", "base", "pecas", "cenarios", "movimentos", "saida")
VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}


class Asset(BaseModel):
    pasta: Literal["persona", "base", "pecas", "cenarios", "movimentos", "saida"]
    nome: str = Field(min_length=1, max_length=180, pattern=r"^[^/\\]+$")


class Tomada(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    titulo: str = Field(min_length=1, max_length=100)
    lado: Literal["esquerda", "direita"]
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
    altura: int = Field(default=350, ge=0, le=400)
    sobretitulo: str = Field(default="ONE OUTFIT / TWO SEASONS", max_length=45)
    titulo: str = Field(default="Summer to", max_length=45)
    destaque: str = Field(default="autumn.", max_length=30)
    pergunta: str = Field(default="Which would you wear — summer or autumn?", max_length=85)
    esquerda: str = Field(default="AUTUMN", max_length=25)
    direita: str = Field(default="SUMMER", max_length=25)


class Plano(BaseModel):
    duracao_final: int = Field(default=9, ge=4, le=30)
    tomadas: list[Tomada] = Field(min_length=2, max_length=12)
    cortes: list[Corte] = Field(min_length=1, max_length=60)
    faixa: Faixa = Field(default_factory=Faixa)
    legenda: str = Field(default="One outfit, two seasons ☀️🍂 Summer or autumn — which would you wear?\n\n#OutfitInspo #AutumnOutfit #SummerStyle #SeasonalStyle", max_length=1000)


class Novo(BaseModel):
    nome: str = Field(default="Novo vídeo", min_length=1, max_length=100)


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


class Gerar(BaseModel):
    cotacao_id: str
    teto: int = Field(gt=0)


class Cotar(BaseModel):
    tomadas: list[str] | None = None


class Reuso(BaseModel):
    tomada: str
    asset: Asset


def nova_tomada(id: str, lado: str, title: str, prompt: str) -> dict:
    return Tomada(id=id, lado=lado, titulo=title, prompt=prompt).model_dump()


def plano_inicial() -> dict:
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
    return Plano(tomadas=[Tomada(**summer), Tomada(**autumn)],
                 cortes=[Corte(tomada="outono", duracao=9)]).model_dump()


class Processo:
    def __init__(self, root: Path, ask, cli=None, store=None):
        self.root = root.resolve()
        self.store = store or Store(root / "studio" / "dados" / "producoes.sqlite3")
        self.ask = ask
        self.cli = cli or Dreamina()
        self.lock = threading.RLock()
        self.busy: set[str] = set()
        self.chatting: dict[str, int] = {}
        example_file = root / "exemplos" / "producao-v7.json"
        if example_file.exists():
            example = json.loads(example_file.read_text(encoding="utf-8"))
            try:
                self.store.get(example["id"])
            except ValueError:
                self.store.create(example)

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

    def create(self, name: str) -> dict:
        plan = plano_inicial()
        master = {"pasta": "persona", "nome": "ellie-aprovada.png"} if (self.root / "persona" / "ellie-aprovada.png").exists() else None
        for s in plan["tomadas"]:
            name_asset = "01-verao.png" if s["lado"] == "direita" else "04-outono.png"
            if (self.root / "base" / name_asset).exists():
                s["imagens"] = [{"pasta": "base", "nome": name_asset}]
        return self.store.create({"id": uuid.uuid4().hex, "nome": name, "criado": agora(), "status": "conversa",
            **plan, "master": master, "referencia": None, "mensagens": [], "cotacao": None,
            "autorizacao": None, "imports": {}, "canvas_id": "", "canvas_url": "", "erro": "", "historico_creditos": 0})

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

    def save_plan(self, p: dict, plan: dict, expected: int) -> dict:
        if p["id"] in self.busy or (p["id"] in self.chatting and self.chatting[p["id"]] != threading.get_ident()):
            raise ValueError("Aguarde a operação atual terminar antes de alterar o plano.")
        validated = Plano(**plan).model_dump()
        ids = [s["id"] for s in validated["tomadas"]]
        if len(ids) != len(set(ids)) or sum(s["lado"] == "direita" for s in validated["tomadas"]) != 1:
            raise ValueError("Use identificadores únicos e uma única tomada contínua à direita.")
        if any(c["tomada"] not in ids for c in validated["cortes"]):
            raise ValueError("Um corte aponta para uma tomada inexistente.")
        if sum(round(c["duracao"] * 30) for c in validated["cortes"]) != validated["duracao_final"] * 30:
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
        if not text:
            raise ValueError("Escreva sua ideia ou escolha uma referência.")
        p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "user", "texto": text, "criado": agora()})
        p = self.store.save(p)
        context = {k: p.get(k) for k in ["nome", "master", "referencia", "duracao_final", "tomadas", "cortes", "faixa", "legenda", "cotacao", "status"]}
        library = self.library()
        instruction = (self.root / "studio" / "processo-prompt.md").read_text(encoding="utf-8")
        photos: list[Path] = []
        if p.get("master"):
            photos.append(self.asset(p["master"]))
        if p.get("referencia"):
            # Reaproveita o extrator de quadros do sistema original; não envia o vídeo inteiro ao chat.
            from studio.assistente import frames_do_video, montar_folha
            source = self.asset(p["referencia"])
            meta = probe(source)
            frames = frames_do_video(source, 0, min(30, meta["duracao"]), quantidade=12)
            sheet = self.output(id) / "referencia-quadros.jpg"
            montar_folha(frames, sheet, colunas=4, celula=240, numerar=True)
            photos.append(sheet)
            context["referencia_duracao"] = meta["duracao"]
        prompt = instruction + "\n\nESTADO REAL:\n" + json.dumps(context, ensure_ascii=False) + "\nBIBLIOTECA REAL:\n" + json.dumps(library, ensure_ascii=False)
        prompt += "\nCONVERSA RECENTE:\n" + json.dumps(p["mensagens"][-14:], ensure_ascii=False)
        try:
            from studio.assistente import extrair_json
            response = extrair_json(self.ask(prompt, photos))
            message = str(response.get("mensagem_pt", "")).strip()
            if not message:
                raise ValueError("O OpenClaw não retornou uma mensagem.")
            if response.get("plano"):
                p = self.save_plan(p, response["plano"], p["versao"])
            cards = self.cards(response.get("blocos", []), library)
            p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "assistant", "texto": message,
                                     "blocos": cards, "criado": agora()})
            p["erro"] = ""
            p = self.store.save(p)
            if response.get("acao") == "montar" and all(s.get("arquivo") for s in p["tomadas"]):
                p = self.render(id)
        except Exception as e:
            p["erro"] = "Não consegui continuar pelo OpenClaw. Confira a conexão e a assinatura. " + str(e)[:300]
            p["mensagens"].append({"id": uuid.uuid4().hex, "papel": "assistant", "texto": p["erro"], "blocos": [{"tipo": "conexao"}], "criado": agora()})
        return self.store.save(p)

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
            if kind not in ("galeria", "quiz", "plano", "custo", "resultado", "upload", "edicao"):
                continue
            card = {"tipo": kind, "titulo": str(item.get("titulo", ""))[:150]}
            if kind in ("galeria", "upload"):
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
        if not p.get("master"):
            raise ValueError("Escolha a imagem aprovada da modelo primeiro.")
        for shot in pending:
            if not shot["imagens"]:
                raise ValueError("Escolha as imagens de estado de " + shot["titulo"])
            for a in shot["imagens"]:
                self.asset(a)
            effective = dict(shot)
            effective["imagens"] = list(shot["imagens"])
            if p["master"] not in effective["imagens"]:
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
            item = p["imports"].setdefault(key, {"resource": str(uuid.uuid4()), "submit": str(uuid.uuid4()),
                                                  "node": "node_" + uuid.uuid4().hex[:12]})
            self.store.save(p)
            if not item.get("uploaded"):
                result = self.cli.upload(path, p["canvas_id"], item["resource"], kind)
                if result.get("resourceId") != item["resource"]:
                    raise ValueError("O upload não corresponde à referência planejada.")
                item["uploaded"] = True
                self.store.save(p)
            if not item.get("imported"):
                self.cli.import_node(media, item["resource"], item["node"], p["canvas_id"], item["submit"], path.stem, kind)
                item["imported"] = True
                self.store.save(p)
            return item["node"]

        for shot in pending:
            refs = [imported(self.asset(a), "image") for a in shot["imagens"]]
            if p["master"] not in shot["imagens"]:
                refs.append(imported(self.asset(p["master"]), "image"))
            if shot.get("movimento"):
                source = self.asset(shot["movimento"])
                target = self.output(id) / f"movimento-{shot['id']}.mp4"
                preparar_referencia(source, target, shot["movimento_inicio"], shot["movimento_duracao"])
                refs.append(imported(target, "video"))
            shot.setdefault("node_id", "node_" + uuid.uuid4().hex[:12])
            self.store.save(p)
            self.cli.draft(shot, p["canvas_id"], refs)
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
        if all(s.get("arquivo") for s in p["tomadas"]):
            p["status"] = "pronto_para_montar"
            self.store.save(p)
            return self.render(id)
        elif any(s.get("estado") in ("failed", "canceled", "cancelled") for s in p["tomadas"]):
            p["status"] = "parcial"
            p["erro"] = "Uma tomada não concluiu. Os resultados e custos conhecidos foram preservados. Nenhuma repetição foi feita; estorno ainda não foi confirmado."
        elif not any(s.get("submit_id") and not s.get("arquivo") for s in p["tomadas"]):
            p["status"] = "proxima_tomada"
        return self.store.save(p)

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
            for shot in p["tomadas"]:
                if shot["lado"] == "esquerda" and not shot.get("submit_id") and value not in shot["imagens"]:
                    shot["imagens"].append(value)
        p["cotacao"] = p["autorizacao"] = None
        return self.store.save(p)

    def render(self, id: str) -> dict:
        p = self.store.get(id)
        result = montar(p, self.asset, self.output(id))
        p["resultado"] = {**result, "nome": Path(result["caminho"]).name}
        p["status"] = "concluido"
        p["erro"] = ""
        self.store.event(id, "montagem_local", {"arquivo": result["nome"] if "nome" in result else Path(result["caminho"]).name, "creditos": 0})
        return self.store.save(p)

    def background(self, id: str, function, *args):
        with self.lock:
            if id in self.busy or id in self.chatting:
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


def create_router(root: Path, ask) -> APIRouter:
    service = Processo(root, ask)
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

    @router.get("")
    def list_productions():
        return service.store.list()

    @router.post("")
    def create(request: Novo):
        return service.create(request.nome)

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
