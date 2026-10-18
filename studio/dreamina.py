"""Adaptador da CLI oficial. Não usa endpoints privados nem armazena credenciais."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


class CliError(RuntimeError):
    pass


class Dreamina:
    def __init__(self, binary: str = ""):
        self.binary = binary or os.environ.get("DREAMINA_CLI", "") or shutil.which("dreamina-canvas") or str(
            Path.home() / "bin" / ("dreamina-canvas.exe" if os.name == "nt" else "dreamina-canvas"))

    def call(self, *args: str, timeout: int = 120) -> dict:
        try:
            process = subprocess.run([self.binary, "--format", "json", "--non-interactive", *map(str, args)],
                                     capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except FileNotFoundError:
            raise CliError("CLI Dreamina não encontrada. Instale a CLI ou configure DREAMINA_CLI.") from None
        except subprocess.TimeoutExpired:
            raise CliError("A CLI não respondeu a tempo. Preserve os identificadores e consulte o andamento; não reenvie a geração.") from None
        try:
            data = json.loads(process.stdout)
        except ValueError:
            raise CliError("A CLI não devolveu JSON válido. Confira a versão instalada.") from None
        if process.returncode or not data.get("ok"):
            error = data.get("error", {})
            # Não propagar envelopes de confirmação: podem conter tokens.
            raise CliError(f"Dreamina: {error.get('code', 'erro')} — {error.get('message', 'operação não concluída')}")
        return data.get("data", {})

    def status(self) -> dict:
        try:
            auth = self.call("auth", "status")
            return {"instalada": True, "conectado": bool(auth.get("loggedIn")), "versao": auth.get("version", "")}
        except CliError as e:
            return {"instalada": False, "conectado": False, "erro": str(e)}

    def models(self) -> list[dict]:
        return self.call("model", "list", "--type", "video").get("items", [])

    def validate(self, shot: dict) -> None:
        models = self.models()
        model = next((m for m in models if m["model"] == shot["modelo"]), None)
        if not model:
            raise CliError("Modelo indisponível na CLI desta conta.")
        modes = [m for m in model.get("modes", []) if m["name"] == shot["modo"]]
        for mode in modes:
            flags = {f["flag"]: f for f in mode.get("flags", [])}
            duration = flags.get("--duration", {})
            if not duration.get("min", 0) <= shot["duracao"] <= duration.get("max", 0):
                continue
            if shot["resolucao"] not in flags.get("--resolution", {}).get("values", []):
                continue
            if "9:16" not in flags.get("--ratio", {}).get("values", []):
                continue
            references = mode.get("references", {})
            types = {r["mediaType"]: r for r in references.get("types", [])}
            images = len(shot["imagens"])
            videos = int(bool(shot.get("movimento")))
            if not references.get("min", 0) <= images + videos <= references.get("max", 0):
                continue
            if images and not types.get("image", {}).get("min", 0) <= images <= types.get("image", {}).get("max", 0):
                continue
            if videos and not types.get("video", {}).get("min", 0) <= videos <= types.get("video", {}).get("max", 0):
                continue
            if len(shot["prompt"]) > flags.get("--prompt", {}).get("maxLength", 0):
                continue
            return
        raise CliError("Duração, resolução, modo ou referências não atendem ao catálogo atual do modelo.")

    def canvas(self, id: str, title: str) -> dict:
        return self.call("canvas", "create", title, "--project-id", id)

    def upload(self, path: Path, project: str, resource: str, kind: str = "local_upload") -> dict:
        return self.call("resource", "upload", "--file", str(path), "--project-id", project,
                         "--resource-id", resource, "--import-kind", kind, timeout=240)

    def import_node(self, type: str, resource: str, node: str, project: str, submit: str, title: str, kind: str = "local_upload") -> dict:
        return self.call("node", "create", type, "--project-id", project, "--node-id", node,
                         "--title", title, "--resource-id", resource, "--import-kind", kind, "--submit-id", submit)

    def draft(self, shot: dict, project: str, refs: list[str]) -> dict:
        # Os vínculos do prompt apontam para os mesmos nós passados em --ref.
        prompt = "\n".join(f"Reference {i+1}: {{{{node:{ref}}}}}" for i, ref in enumerate(refs)) + "\n" + shot["prompt"]
        args = ["node", "create", "video", "--project-id", project, "--node-id", shot["node_id"],
                "--title", shot["titulo"], "--model", shot["modelo"], "--mode", shot["modo"],
                "--resolution", shot["resolucao"], "--ratio", "9:16", "--duration", str(shot["duracao"]),
                "--count", "1", "--prompt", prompt]
        for ref in refs:
            args += ["--ref", f"node:{ref}"]
        return self.call(*args)

    def quote(self, project: str, nodes: list[str]) -> dict:
        args = ["node", "quote", "--project-id", project]
        for node in nodes:
            args += ["--node-id", node]
        data = self.call(*args)
        if data.get("confirmable") is not True or not isinstance(data.get("totalMaxCredits"), (int, float)):
            raise CliError("Cotação incompleta. Nenhuma geração foi autorizada.")
        quoted = {i.get("nodeId") for i in data.get("items", []) if isinstance(i.get("maxCredits"), (int, float))}
        if quoted != set(nodes):
            raise CliError("A cotação não cobre todas as tomadas.")
        return data

    def run(self, project: str, shots: list[dict], ceiling: int) -> dict:
        ids = ["--project-id", project]
        for shot in shots:
            ids += ["--node-id", shot["node_id"]]
        # O token fica somente em memória, restrito a este lote aprovado pelo clique humano.
        confirmed = self.call("node", "confirm", *ids, "--credit-ceiling", str(ceiling))
        token = confirmed.get("creditConfirmationToken")
        if not token:
            raise CliError("A confirmação não retornou autorização para executar o lote.")
        args = ["node", "run", *ids, "--credit-token", token]
        for shot in shots:
            args += ["--submit-id", shot["submit_id"]]
        return self.call(*args)

    def operation(self, project: str, submit: str) -> dict:
        return self.call("operation", "status", submit, "--project-id", project)

    def resource(self, project: str, resource: str) -> dict:
        return self.call("resource", "get", resource, "--project-id", project)

    def download(self, project: str, resource: str, path: Path) -> dict:
        return self.call("resource", "download", resource, "--project-id", project, "--output", str(path), timeout=240)
