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
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    workspace = root / "studio" / "agente-ellie"
    local_wrapper = root / "openclaw-local.cmd"
    cli = args.cli or (str(local_wrapper) if os.name == 'nt' and local_wrapper.exists() else shutil.which("openclaw")) or "openclaw"
    command = [cli, "agents", "add", "ellie-studio", "--workspace", str(workspace), "--non-interactive"]
    print("Este Estúdio usa o agente separado ellie-studio e o modelo que você configurou no OpenClaw.")
    print("Conecte primeiro a assinatura no OpenClaw (OAuth ChatGPT/Codex ou login Claude CLI).")
    print("Não configure uma API key/fallback pago se quiser usar somente a assinatura.")
    print("Comando de registro:", subprocess.list2cmdline(command))
    if not args.executar:
        print("Prévia: nada foi alterado. Para registrar, rode novamente com --executar.")
        return
    # Usa a CLI em vez de sobrescrever openclaw.json, contas ou modelos existentes.
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit("O OpenClaw não registrou o agente. Confira `openclaw agents list`; não sobrescreva outro agente.")
    source = root / "studio" / "mcp" / "skill" / "producao-ellie"
    dest = workspace / "skills" / "producao-ellie"
    if dest.exists():
        raise SystemExit("A skill já existe no workspace; preserve as alterações antes de copiar outra vez.")
    shutil.copytree(source, dest)
    print("Agente e skill preparados. Reinicie o Gateway e confira `openclaw agents list`.")
    print("O Estúdio não fez login nem alterou o plano da sua conta.")


if __name__ == "__main__":
    main()
