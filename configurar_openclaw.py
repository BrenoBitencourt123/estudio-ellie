"""Registra um agente dedicado pela CLI oficial; não edita credenciais/config global à mão."""
import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executar", action="store_true", help="Registrar o agente no OpenClaw instalado")
    parser.add_argument("--cli", default="", help="Caminho opcional para a CLI OpenClaw")
    parser.add_argument("--gateway", action="store_true", help="Registrar pelo RPC oficial do Gateway que já está aberto")
    parser.add_argument("--node", default="", help="Node.js para o modo --gateway")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    workspace = root / "studio" / "agente-ellie"
    local_wrapper = root / "openclaw-local.cmd"
    cli = args.cli or (str(local_wrapper) if os.name == 'nt' and local_wrapper.exists() else shutil.which("openclaw")) or "openclaw"
    command = [cli, "agents", "add", "ellie-studio", "--workspace", str(workspace), "--non-interactive"]
    if args.gateway:
        bundled_node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        node = args.node or (str(bundled_node) if os.name == 'nt' and bundled_node.exists() else shutil.which('node'))
        if not node:
            raise SystemExit('Node.js não encontrado. Instale Node 24+ ou indique --node.')
        command = [node, str(root / 'studio/mcp/configurar-gateway.mjs')]
    print("Este Estúdio usa o agente separado ellie-studio e o modelo que você configurou no OpenClaw.")
    print("Conecte primeiro a assinatura no OpenClaw (OAuth ChatGPT/Codex ou login Claude CLI).")
    print("Não configure uma API key/fallback pago se quiser usar somente a assinatura.")
    print("Comando de registro:", subprocess.list2cmdline(command))
    if not args.executar:
        print("Prévia: nada foi alterado. Para registrar, rode novamente com --executar.")
        return
    # Usa CLI/RPC oficiais sem sobrescrever openclaw.json ou credenciais.
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit("O OpenClaw não registrou o agente. Confira `openclaw agents list`; não sobrescreva outro agente.")
    source = root / "studio" / "mcp" / "skill" / "producao-ellie"
    dest = workspace / "skills" / "producao-ellie"
    if dest.exists():
        expected = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        current = {p.relative_to(dest): p.read_bytes() for p in dest.rglob('*') if p.is_file()}
        if expected != current:
            raise SystemExit("A skill existente tem alterações. Foi preservada; confira antes de substituí-la.")
    else:
        shutil.copytree(source, dest)
    print("Agente e skill preparados. Confira a conexão no Estúdio.")
    print("O Estúdio não fez login nem alterou o plano da sua conta.")


if __name__ == "__main__":
    main()
