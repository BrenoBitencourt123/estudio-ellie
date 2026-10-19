"""Supervisor do Estúdio Ellie: roda em segundo plano, sem janelas.

- Sobe o servidor (FastAPI, porta 8000) e a ponte OpenClaw (Node, porta 8790), escondidos.
- Liga o gateway do OpenClaw se ele estiver desligado (e religa se cair). Não o derruba ao sair.
- Se um deles cair, sobe de novo (com espera crescente para não ficar em loop).
- Observa os arquivos do sistema. Quando algo muda (uma correção, uma atualização), espera o
  Estúdio ficar livre (nenhuma resposta da IA, imagem ou vídeo em andamento) e só então reinicia
  a parte que mudou. A página no navegador percebe e se recarrega sozinha.

Uso:
  pythonw studio/supervisor.py            inicia em segundo plano (ou não faz nada se já estiver rodando)
  pythonw studio/supervisor.py --abrir    idem, e abre o Estúdio no navegador
  python  studio/supervisor.py --parar    encerra tudo
Log: studio/dados/logs/supervisor.log
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOGS = RAIZ / "studio" / "dados" / "logs"
ARQ_PID = LOGS / "supervisor.pid"
ARQ_PARAR = LOGS / "supervisor.parar"
URL = "http://127.0.0.1:8000"
PORTA_API, PORTA_PONTE = 8000, int(os.environ.get("PORTA_MCP", "8790"))
SEM_JANELA = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
INTERVALO = 2.0
ESPERA_ESTAVEL = 3.0  # espera os arquivos pararem de mudar (gravação em lote) antes de reiniciar
VARIAVEIS_ENV = ("OPENCLAW_AGENTE", "OPENCLAW_URL", "OPENCLAW_AGENTE_CHAT", "OPENCLAW_AGENTE_RESERVA", "DREAMINA_CLI")

# O que reiniciar quando cada grupo de arquivos muda. O prompt (processo-prompt.md) e a interface
# compilada são lidos a cada uso, então não precisam de reinício.
OBSERVADOS = {
    "api": [("studio", "*.py"), (".", "gerar.py"), (".", ".env"), (".", "requirements.txt")],
    "ponte": [("studio/mcp/src", "*.ts"), ("studio/mcp", "package.json"), (".", ".env")],
}


def log(*partes):
    LOGS.mkdir(parents=True, exist_ok=True)
    linha = f"[{time.strftime('%d/%m %H:%M:%S')}] " + " ".join(str(p) for p in partes)
    with (LOGS / "supervisor.log").open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    if sys.stdout and not sys.executable.lower().endswith("pythonw.exe"):
        print(linha, flush=True)


def porta_ocupada(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def get_json(url: str, tempo: float = 3) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=tempo) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def ler_env() -> dict:
    env = dict(os.environ)
    arquivo = RAIZ / ".env"
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            chave, _, valor = linha.partition("=")
            if chave.strip() in VARIAVEIS_ENV:
                env[chave.strip()] = valor.strip().strip('"')
    return env


def achar_node() -> str:
    """Node 24+: o do PATH ou o que vem com o Codex (o mesmo que o openclaw-local.ps1 usa)."""
    if os.environ.get("ESTUDIO_NODE"):
        return os.environ["ESTUDIO_NODE"]
    candidatos = [shutil.which("node"),
                  str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")]
    for c in candidatos:
        if c and Path(c).exists():
            try:
                versao = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=10,
                                        creationflags=SEM_JANELA).stdout.strip().lstrip("v")
                if int(versao.split(".")[0]) >= 24:
                    return c
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
    raise RuntimeError("Node.js 24+ não encontrado (nem no PATH nem no runtime do Codex).")


def python_console() -> str:
    """Os filhos rodam com python.exe (sem janela por CREATE_NO_WINDOW); pythonw não grava stdout."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return sys.executable


def assinatura(grupo: str) -> dict:
    marcas = {}
    for pasta, padrao in OBSERVADOS[grupo]:
        base = RAIZ / pasta
        arquivos = [base / padrao] if "*" not in padrao else list(base.glob(padrao))
        for f in arquivos:
            if f.is_file() and "__pycache__" not in f.parts:
                st = f.stat()
                marcas[str(f)] = (st.st_mtime_ns, st.st_size)
    return marcas


class Processo:
    def __init__(self, nome: str, comando, cwd: Path, porta: int, url_ocupado: str):
        self.nome, self.comando, self.cwd, self.porta, self.url_ocupado = nome, comando, cwd, porta, url_ocupado
        self.proc: subprocess.Popen | None = None
        self.falhas = 0
        self.proxima_tentativa = 0.0

    def iniciar(self):
        if porta_ocupada(self.porta):
            log(f"{self.nome}: porta {self.porta} já está em uso por outro programa; não vou abrir outro.")
            self.proxima_tentativa = time.time() + 30
            return
        saida = (LOGS / f"{self.nome}.log").open("ab")
        erro = (LOGS / f"{self.nome}-error.log").open("ab")
        self.proc = subprocess.Popen(self.comando(), cwd=self.cwd, env=ler_env(), stdout=saida, stderr=erro,
                                     stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
        log(f"{self.nome}: iniciado (pid {self.proc.pid})")

    def parar(self):
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":  # encerra a árvore inteira (uvicorn/node e filhos)
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True,
                               creationflags=SEM_JANELA)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log(f"{self.nome}: parado")
        self.proc = None
        for _ in range(30):  # espera a porta liberar
            if not porta_ocupada(self.porta):
                break
            time.sleep(0.5)

    def vivo(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def ocupado(self) -> bool:
        estado = get_json(self.url_ocupado)
        return bool(estado and estado.get("ocupado"))

    def cuidar(self):
        """Sobe de novo se caiu, com espera crescente (5 s, 10 s, 20 s… até 2 min)."""
        if self.vivo() or time.time() < self.proxima_tentativa:
            return
        if self.proc is not None:
            self.falhas += 1
            log(f"{self.nome}: caiu (código {self.proc.returncode}); tentativa {self.falhas}")
            self.proc = None
            self.proxima_tentativa = time.time() + min(120, 5 * 2 ** (self.falhas - 1))
            return
        self.iniciar()
        if self.vivo():
            self.inicio = time.time()

    def estabilizou(self):
        if self.vivo() and self.falhas and time.time() - getattr(self, "inicio", time.time()) > 60:
            self.falhas = 0


def porta_gateway() -> int:
    url = ler_env().get("OPENCLAW_URL", "") or "ws://127.0.0.1:18789"
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return 18789


def achar_openclaw() -> str | None:
    candidatos = [shutil.which("openclaw"), str(Path(os.environ.get("APPDATA", "")) / "npm" / "openclaw.cmd")]
    return next((c for c in candidatos if c and Path(c).exists()), None)


class Gateway:
    """Garante o gateway do OpenClaw ligado. Ele é compartilhado (outros programas usam), então o supervisor
    só liga quando está desligado e nunca o derruba ao encerrar.
    Tentativas: 'openclaw gateway start' (serviço instalado); se a porta não abrir, roda o gateway escondido."""
    MODOS = (["gateway", "start"], ["gateway", "run"], ["gateway"])

    ARQUIVO_MODO = LOGS / "gateway-modo.txt"  # o modo que funcionou da última vez é tentado primeiro

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        try:
            self.modo = self.MODOS.index(self.ARQUIVO_MODO.read_text(encoding="utf-8").strip().split())
        except (OSError, ValueError):
            self.modo = 0
        self.proxima = 0.0
        self.espera = 15
        self.tentando: list[str] | None = None  # modo em andamento, para registrar quando a porta abrir tarde

    def _ligou(self, args: list[str]):
        log(f"gateway: ligado com 'openclaw {' '.join(args)}'")
        self.espera = 15
        self.tentando = None
        try:
            self.ARQUIVO_MODO.write_text(" ".join(args), encoding="utf-8")
        except OSError:
            pass

    def _esperar_porta(self, segundos: float) -> bool:
        fim = time.time() + segundos
        while time.time() < fim:
            if porta_ocupada(porta_gateway()):
                return True
            time.sleep(1)
        return False

    def cuidar(self):
        if porta_ocupada(porta_gateway()):
            if self.tentando:  # subiu depois do tempo de espera
                self._ligou(self.tentando)
            return
        if time.time() < self.proxima:
            return
        if self.proc and self.proc.poll() is None:  # ainda subindo
            self.proxima = time.time() + 5
            return
        exe = achar_openclaw()
        if not exe:
            log("gateway: comando 'openclaw' não encontrado; ligue o OpenClaw manualmente")
            self.proxima = time.time() + 300
            return
        args = self.MODOS[self.modo % len(self.MODOS)]
        self.tentando = list(args)
        log(f"gateway: porta {porta_gateway()} fechada; tentando 'openclaw {' '.join(args)}'")
        saida = (LOGS / "gateway.log").open("ab")
        try:
            if args == ["gateway", "start"]:
                subprocess.run([exe, *args], stdout=saida, stderr=saida, stdin=subprocess.DEVNULL,
                               timeout=90, creationflags=SEM_JANELA)
                ok = self._esperar_porta(30)
            else:
                self.proc = subprocess.Popen([exe, *args], stdout=saida, stderr=saida, stdin=subprocess.DEVNULL,
                                             cwd=Path.home(), creationflags=SEM_JANELA)
                ok = self._esperar_porta(45)
        except (OSError, subprocess.SubprocessError) as e:
            log("gateway: falhou ao executar:", repr(e))
            ok = False
        if ok:
            self._ligou(list(args))
            return
        self.modo += 1
        if self.modo % len(self.MODOS) == 0:  # deu a volta em todos: espera crescente
            self.espera = min(600, self.espera * 2)
        self.proxima = time.time() + (5 if self.modo % len(self.MODOS) else self.espera)


def pid_vivo(pid: int) -> bool:
    if os.name == "nt":
        saida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                               creationflags=SEM_JANELA).stdout
        return str(pid) in saida
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ja_rodando() -> int | None:
    try:
        pid = int(ARQ_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and pid_vivo(pid) else None


def abrir_quando_pronto():
    for _ in range(120):
        if get_json(URL + "/api/versao", 1) is not None:
            break
        time.sleep(0.5)
    webbrowser.open(URL)


def parar_tudo():
    pid = ja_rodando()
    if not pid:
        print("O Estúdio não está rodando.")
        return
    ARQ_PARAR.write_text("1")
    for _ in range(60):
        if not pid_vivo(pid):
            print("Estúdio encerrado.")
            return
        time.sleep(0.5)
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=SEM_JANELA)
    print("Estúdio encerrado à força.")


def encerrar_instancia_antiga():
    """Se o Estúdio foi aberto pelo estudio.bat/iniciar.ps1, fecha essa instância para o supervisor assumir."""
    arquivo = LOGS / "processos.json"
    try:
        antigos = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    for chave in ("api", "ponte", "interface"):
        pid = antigos.get(chave)
        if isinstance(pid, int) and pid_vivo(pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=SEM_JANELA)
            log(f"instância antiga ({chave}, pid {pid}) encerrada para o supervisor assumir")
    arquivo.unlink(missing_ok=True)


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    if "--parar" in sys.argv:
        return parar_tudo()
    if ja_rodando():
        if "--abrir" in sys.argv:
            webbrowser.open(URL)
        return
    ARQ_PID.write_text(str(os.getpid()))
    ARQ_PARAR.unlink(missing_ok=True)
    log("supervisor: iniciado em", RAIZ)
    encerrar_instancia_antiga()
    node = achar_node()
    api = Processo("api", lambda: [python_console(), "-m", "uvicorn", "studio.server:app", "--host", "127.0.0.1",
                                   "--port", str(PORTA_API)], RAIZ, PORTA_API, URL + "/api/processo/ocupado")
    ponte = Processo("ponte", lambda: [node, "src/index.ts"], RAIZ / "studio" / "mcp", PORTA_PONTE,
                     f"http://127.0.0.1:{PORTA_PONTE}/ia/ocupado")
    servicos = {"api": api, "ponte": ponte}
    marcas = {g: assinatura(g) for g in servicos}
    proprio = Path(__file__).resolve()
    marca_propria = proprio.stat().st_mtime_ns
    pendente: dict[str, float] = {}  # grupo -> momento da última mudança vista
    reiniciar_supervisor = False
    avisado: set[str] = set()
    if "--abrir" in sys.argv:
        import threading
        threading.Thread(target=abrir_quando_pronto, daemon=True).start()
    gateway = Gateway()

    def vigiar_gateway():  # em paralelo: ligar o gateway pode levar 1-2 min e não deve atrasar o Estúdio
        while not ARQ_PARAR.exists():
            try:
                gateway.cuidar()
            except Exception as e:
                log("gateway: erro:", repr(e))
            time.sleep(INTERVALO)
    import threading
    threading.Thread(target=vigiar_gateway, daemon=True).start()
    try:
        while not ARQ_PARAR.exists():
            for grupo, servico in servicos.items():
                servico.cuidar()
                servico.estabilizou()
                atual = assinatura(grupo)
                if atual != marcas[grupo]:
                    marcas[grupo] = atual
                    pendente[grupo] = time.time()
                if grupo in pendente and time.time() - pendente[grupo] >= ESPERA_ESTAVEL:
                    if servico.vivo() and (servico.ocupado() or (grupo == "ponte" and api.ocupado())):
                        if grupo not in avisado:
                            log(f"{grupo}: atualização pronta; esperando terminar o que está em andamento")
                            avisado.add(grupo)
                        continue
                    log(f"{grupo}: arquivos mudaram; reiniciando para aplicar a atualização")
                    servico.parar()
                    servico.falhas = 0
                    servico.proxima_tentativa = 0
                    servico.cuidar()
                    pendente.pop(grupo)
                    avisado.discard(grupo)
            # O próprio supervisor foi atualizado: reinicia-se quando tudo estiver livre
            if proprio.stat().st_mtime_ns != marca_propria and not api.ocupado() and not ponte.ocupado():
                time.sleep(ESPERA_ESTAVEL)
                log("supervisor: atualizado; reiniciando o supervisor")
                reiniciar_supervisor = True
                break
            time.sleep(INTERVALO)
    finally:
        for servico in servicos.values():
            servico.parar()
        ARQ_PARAR.unlink(missing_ok=True)
        ARQ_PID.unlink(missing_ok=True)
        log("supervisor: encerrado")
    if reiniciar_supervisor:
        argumentos = [a for a in sys.argv[1:] if a != "--abrir"]
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *argumentos], cwd=RAIZ,
                         creationflags=SEM_JANELA | (0x00000008 if os.name == "nt" else 0))  # DETACHED_PROCESS


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pythonw não mostra erros: deixa registrado
        log("supervisor: erro fatal:", repr(e))
        raise
