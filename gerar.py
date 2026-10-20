"""
Gera os vídeos da Gemma com Seedance 2.5 (Atlas Cloud).

Uso:
  python gerar.py --teste        # mostra o que seria enviado e o custo, sem gastar nada
  python gerar.py --so v01       # gera só o vídeo com id v01
  python gerar.py                # gera toda a fila (respeitando o teto semanal)

Cada linha da fila.csv vira um vídeo em saida/. Tudo que foi enviado fica em
saida/registro.csv, que também serve pra calcular o gasto da semana.
"""

import argparse
import base64
import csv
import mimetypes
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from studio.processos import rodar

PASTA = Path(__file__).resolve().parent
PASTA_PERSONA = PASTA / "persona"
PASTA_PECAS = PASTA / "pecas"
PASTA_MOVIMENTOS = PASTA / "movimentos"
PASTA_CENARIOS = PASTA / "cenarios"
PASTA_LIMPOS = PASTA_MOVIMENTOS / ".limpos"
PASTA_SAIDA = PASTA / "saida"
ARQUIVO_FILA = PASTA / "fila.csv"
ARQUIVO_REGISTRO = PASTA_SAIDA / "registro.csv"

API = "https://api.atlascloud.ai/api/v1/model"
# Apelido → id do modelo na Atlas Cloud (todos aceitam fotos de referência)
MODELOS = {
    "2.5": "bytedance/seedance-2.5/reference-to-video",
    "2.0": "bytedance/seedance-2.0/reference-to-video",
    "2.0-fast": "bytedance/seedance-2.0-fast/reference-to-video",
    "2.0-mini": "bytedance/seedance-2.0-mini/reference-to-video",
}
# Preço por segundo (US$, sem vídeo de movimento) publicado pela Atlas Cloud em 10/2026
PRECOS = {
    ("2.5", "480p"): 0.134, ("2.5", "720p"): 0.30,
    ("2.0", "480p"): 0.09, ("2.0", "720p"): 0.20,
    ("2.0-fast", "480p"): 0.027, ("2.0-fast", "720p"): 0.0581,
    ("2.0-mini", "480p"): 0.0113, ("2.0-mini", "720p"): 0.0242,
}
EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}

CAMPOS_REGISTRO = [
    "data", "id", "modelo", "prediction_id", "duracao", "custo_estimado_usd", "custo_real_usd", "status", "arquivo",
    "erro",
]
# Status que contam no gasto da semana (falha não é cobrada)
STATUS_COBRADOS = {"enviado", "ok"}

INTERVALO_CONSULTA_S = 5
TEMPO_MAXIMO_S = 15 * 60


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def sair(mensagem: str) -> None:
    print(f"\n❌ {mensagem}")
    sys.exit(1)


def carregar_env() -> dict[str, str]:
    """Lê o .env simples (CHAVE=valor) sem depender de biblioteca extra."""
    arquivo = PASTA / ".env"
    if not arquivo.exists():
        sair("Arquivo .env não encontrado. Copie o .env.example para .env e preencha a chave.")
    config: dict[str, str] = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        config[chave.strip()] = valor.strip()
    return config


def numero(config: dict[str, str], chave: str) -> float:
    try:
        return float(config[chave].replace(",", "."))
    except (KeyError, ValueError):
        sair(f"Valor inválido ou ausente no .env: {chave}")
        raise  # inalcançável, só pro type checker


# ---------------------------------------------------------------------------
# Fila e registro (CSV com ; para abrir direto no Excel)
# ---------------------------------------------------------------------------

def ler_fila() -> list[dict[str, str]]:
    with ARQUIVO_FILA.open(encoding="utf-8-sig", newline="") as f:
        linhas = [l for l in csv.DictReader(f, delimiter=";") if (l.get("id") or "").strip()]
    for linha in linhas:
        try:
            duracao = int(linha["duracao"])
        except (KeyError, ValueError):
            sair(f"Linha {linha['id']}: duracao precisa ser um número inteiro.")
            raise
        if not 4 <= duracao <= 30:
            sair(f"Linha {linha['id']}: duracao precisa estar entre 4 e 30 segundos.")
    return linhas


def ler_registro() -> list[dict[str, str]]:
    if not ARQUIVO_REGISTRO.exists():
        return []
    with ARQUIVO_REGISTRO.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def salvar_registro(registro: list[dict[str, str]]) -> None:
    PASTA_SAIDA.mkdir(exist_ok=True)
    with ARQUIVO_REGISTRO.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS_REGISTRO, delimiter=";")
        escritor.writeheader()
        escritor.writerows(registro)


def gasto_da_semana_usd(registro: list[dict[str, str]]) -> float:
    limite = datetime.now() - timedelta(days=7)
    total = 0.0
    for linha in registro:
        if linha["status"] in STATUS_COBRADOS and datetime.fromisoformat(linha["data"]) >= limite:
            # Usa o valor cobrado de verdade quando a Atlas Cloud já informou
            total += float(linha.get("custo_real_usd") or linha["custo_estimado_usd"])
    return total


# ---------------------------------------------------------------------------
# Referências
# ---------------------------------------------------------------------------

def imagens_persona() -> list[Path]:
    imagens = sorted(p for p in PASTA_PERSONA.iterdir() if p.suffix.lower() in EXTENSOES_IMAGEM)
    if not imagens:
        sair("Nenhuma imagem em persona/. Coloque as fotos de referência da Gemma lá.")
    return imagens


def arquivo_obrigatorio(pasta: Path, nome: str, id_video: str) -> Path:
    caminho = pasta / nome
    if not caminho.exists():
        sair(f"Linha {id_video}: arquivo não encontrado: {pasta.name}/{nome}")
    return caminho


def imagem_base64(caminho: Path) -> str:
    tipo = mimetypes.guess_type(caminho.name)[0] or "image/png"
    return f"data:{tipo};base64,{base64.b64encode(caminho.read_bytes()).decode()}"


def limpar_movimento(caminho: Path, duracao: int) -> Path:
    """
    Prepara o vídeo de movimento: tira o áudio, corta a faixa de baixo (onde fica o
    aviso de direitos do TikTok) e limita à duração do vídeo final.
    Texto e marca d'água em cima do corpo NÃO dá pra remover automaticamente.
    """
    PASTA_LIMPOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_LIMPOS / f"{caminho.stem}_{duracao}s.mp4"
    if destino.exists():
        return destino
    comando = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(caminho),
        "-t", str(duracao),
        "-an",
        "-vf", "crop=iw:trunc(ih*0.94/2)*2:0:0,fps=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(destino),
    ]
    resultado = rodar(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        sair(f"FFmpeg falhou ao limpar {caminho.name}: {resultado.stderr.strip()}")
    return destino


def duracao_video(caminho: Path) -> float:
    resultado = rodar(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(caminho)],
        capture_output=True, text=True,
    )
    try:
        return float(resultado.stdout.strip())
    except ValueError:
        sair(f"Não consegui ler a duração de {caminho.name}.")
        raise


def montar_prompt(
    qtd_persona: int, tem_peca: bool, tem_cenario: bool, tem_movimento: bool, cena: str, sem_rosto: bool = False
) -> str:
    """
    As imagens vão nesta ordem: persona, peça (se tiver), cenário (se tiver).
    Se a cena citar a palavra PECA (ex.: "holds the dress from PECA on a hanger"), ela vira a
    referência da peça e o script não diz que ela está vestindo (serve pra takes de cabide/POV).
    """
    refs = [f"@Image{i}" for i in range(1, qtd_persona + 1)]
    lista_refs = ", ".join(refs[:-1]) + f" and {refs[-1]}" if len(refs) > 1 else (refs[0] if refs else "")
    proxima_imagem = qtd_persona + 1
    peca_na_cena = tem_peca and "PECA" in cena
    if peca_na_cena:
        cena = cena.replace("PECA", f"@Image{proxima_imagem}")
    # Boas práticas do Seedance 2.0 (pesquisa 10/2026): cada referência ligada a UMA função explícita,
    # frases positivas (não há campo de prompt negativo e "não faça X" tende a puxar o X) e prompt curto.
    partes = []
    if sem_rosto:
        # Vídeo sem rosto: as fotos dão só cabelo, corpo e pele; o enquadramento deixa a cabeça fora do quadro
        if lista_refs:
            partes.append(f"Same young woman as {lista_refs}: same hair, skin tone and body, consistent throughout.")
        partes.append("Framed from the chin down the whole time: her face stays out of frame, the shot shows her from the neck to the feet.")
    elif lista_refs:
        partes.append(
            f"Same young woman as {lista_refs}: stable facial structure, same hair and body, consistent identity throughout."
        )
    partes.append(cena.strip().rstrip(".") + ".")
    if tem_peca:
        if peca_na_cena:
            partes.append(
                f"Use @Image{proxima_imagem} only for the garment: same colours, pattern and cut."
            )
        else:
            partes.append(
                f"Use @Image{proxima_imagem} only for her outfit: same colours, pattern and cut, same clothing throughout."
            )
        proxima_imagem += 1
    if tem_cenario:
        partes.append(
            f"Use @Image{proxima_imagem} only for the location: same place, colours, weather and light."
        )
    if tem_movimento:
        partes.append(
            "Use @Video1 only for body movement and camera motion; "
            + ("her outfit and the place come from the images." if sem_rosto
               else "her face, outfit and the place come from the images.")
        )
    # Regra física fixa: evita objeto flutuando quando a mão que segura algo faz outra ação
    partes.append(
        "Natural hands with five fingers; anything she holds stays firmly in the same hand."
    )
    partes.append("Realistic vertical smartphone footage, natural light, sharp focus, clean frame with only the scene.")
    return " ".join(partes)


# ---------------------------------------------------------------------------
# Atlas Cloud
# ---------------------------------------------------------------------------

def cabecalho(chave: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {chave}"}


def enviar_video_referencia(chave: str, caminho: Path) -> str:
    """Vídeo de referência não aceita base64, então sobe pelo uploadMedia."""
    with caminho.open("rb") as f:
        resposta = requests.post(
            f"{API}/uploadMedia",
            headers=cabecalho(chave),
            files={"file": (caminho.name, f, "video/mp4")},
            timeout=120,
        )
    if resposta.status_code != 200:
        sair(f"Upload de {caminho.name} falhou ({resposta.status_code}): {resposta.text[:300]}")
    dados = resposta.json()
    # A documentação da Atlas Cloud mostra os dois formatos de resposta
    url = dados.get("url") or (dados.get("data") or {}).get("download_url")
    if not url:
        sair(f"Upload de {caminho.name} não retornou URL. Resposta: {str(dados)[:300]}")
    return url


def iniciar_geracao(chave: str, payload: dict) -> str:
    resposta = requests.post(
        f"{API}/generateVideo",
        headers={**cabecalho(chave), "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    try:
        dados = resposta.json()
    except ValueError:
        dados = {}
    corpo = dados.get("data")
    prediction_id = corpo.get("id") if isinstance(corpo, dict) else None
    if resposta.status_code != 200 or not prediction_id:
        sair(f"A Atlas Cloud recusou o pedido ({resposta.status_code}): {resposta.text[:500]}")
    return prediction_id


def buscar_preco(chave: str, prediction_id: str) -> str:
    """A Atlas Cloud só informa o preço alguns segundos depois de concluir o vídeo."""
    for _ in range(6):
        time.sleep(5)
        try:
            resposta = requests.get(f"{API}/prediction/{prediction_id}", headers=cabecalho(chave), timeout=30)
            preco = (resposta.json().get("data") or {}).get("price")
        except (requests.RequestException, ValueError):
            preco = None
        if preco:
            return str(preco)
    return ""


def aguardar_resultado(chave: str, prediction_id: str) -> tuple[str, str, str]:
    """
    Retorna (status, url_ou_erro, preco_cobrado_usd).
    Status: 'ok', 'falhou' ou 'enviado' (tempo esgotado).
    """
    inicio = time.time()
    while time.time() - inicio < TEMPO_MAXIMO_S:
        try:
            resposta = requests.get(f"{API}/prediction/{prediction_id}", headers=cabecalho(chave), timeout=30)
            dados = resposta.json().get("data") or {}
        except (requests.RequestException, ValueError):
            dados = {}  # erro de rede momentâneo: tenta de novo na próxima volta
        status = dados.get("status")
        preco = str(dados.get("price") or "")
        if status in ("completed", "succeeded"):
            return "ok", dados["outputs"][0], preco or buscar_preco(chave, prediction_id)
        if status == "failed":
            return "falhou", str(dados.get("error") or "falha sem mensagem"), preco
        print(f"   ⏳ processando... {int(time.time() - inicio)}s", end="\r")
        time.sleep(INTERVALO_CONSULTA_S)
    return "enviado", "tempo esgotado; rode o script de novo pra continuar esperando", ""


def baixar(url: str, id_video: str) -> Path:
    destino = PASTA_SAIDA / f"{id_video}.mp4"
    versao = 2
    while destino.exists():
        destino = PASTA_SAIDA / f"{id_video}_{versao}.mp4"
        versao += 1
    with requests.get(url, stream=True, timeout=300) as resposta:
        resposta.raise_for_status()
        with destino.open("wb") as f:
            for bloco in resposta.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    return destino


def aumentar_para_1080(arquivo: Path) -> Path:
    """Aumenta o vídeo pra 1080x1920 no próprio computador (grátis), mantendo o original."""
    destino = arquivo.with_name(f"{arquivo.stem}_1080.mp4")
    comando = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(arquivo),
        "-vf", "scale=1080:1920:flags=lanczos",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "slow",
        str(destino),
    ]
    resultado = rodar(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"   ⚠️  não consegui aumentar pra 1080p: {resultado.stderr.strip()}")
        return arquivo
    return destino


def finalizar(
    chave: str, linha_registro: dict[str, str], registro: list[dict[str, str]], aumentar: bool, sufixo: str = ""
) -> None:
    """Espera o resultado de um pedido já enviado, baixa e atualiza o registro."""
    status, resultado, preco = aguardar_resultado(chave, linha_registro["prediction_id"])
    linha_registro["status"] = status
    linha_registro["custo_real_usd"] = preco
    if status == "ok":
        arquivo = baixar(resultado, linha_registro["id"] + sufixo)
        linha_registro["arquivo"] = arquivo.name
        cobrado = f" — cobrado US$ {float(preco):.2f}" if preco else ""
        print(f"   ✅ pronto: saida/{arquivo.name}{cobrado}          ")
        if aumentar:
            final = aumentar_para_1080(arquivo)
            if final != arquivo:
                print(f"   📱 versão pra postar: saida/{final.name}")
    else:
        linha_registro["erro"] = resultado
        print(f"   ⚠️  {status}: {resultado}          ")
    salvar_registro(registro)


# ---------------------------------------------------------------------------
# Edits: junta os takes de um mesmo grupo num vídeo só
# ---------------------------------------------------------------------------

def juntar_grupos(fila: list[dict[str, str]], registro: list[dict[str, str]]) -> None:
    """
    Linhas da fila com o mesmo 'grupo' viram um edit em saida/edits/<grupo>.mp4,
    na ordem em que aparecem na fila, com corte seco. Usa o take mais recente de cada id.
    """
    ultimo_take: dict[str, str] = {}
    for linha in registro:
        if linha["status"] == "ok" and linha.get("arquivo"):
            ultimo_take[linha["id"]] = linha["arquivo"]

    grupos: dict[str, list[str]] = {}
    for linha in fila:
        grupo = (linha.get("grupo") or "").strip()
        if grupo:
            grupos.setdefault(grupo, []).append(linha["id"].strip())

    for grupo, ids in grupos.items():
        faltando = [i for i in ids if i not in ultimo_take]
        if faltando:
            print(f"🎬 {grupo}: ainda falta gerar {', '.join(faltando)}")
            continue
        takes = []
        for id_video in ids:
            original = PASTA_SAIDA / ultimo_take[id_video]
            versao_1080 = original.with_name(f"{original.stem}_1080.mp4")
            takes.append(versao_1080 if versao_1080.exists() else original)

        destino = PASTA_SAIDA / "edits" / f"{grupo}.mp4"
        destino.parent.mkdir(exist_ok=True)
        entradas: list[str] = []
        filtros: list[str] = []
        for i, take in enumerate(takes):
            entradas += ["-i", str(take)]
            filtros.append(
                f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"fps=30,setsar=1,format=yuv420p[t{i}]"
            )
        filtros.append("".join(f"[t{i}]" for i in range(len(takes))) + f"concat=n={len(takes)}:v=1:a=0[final]")
        comando = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *entradas,
            "-filter_complex", ";".join(filtros), "-map", "[final]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow", str(destino),
        ]
        resultado = rodar(comando, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"🎬 {grupo}: FFmpeg falhou: {resultado.stderr.strip()}")
            continue
        print(f"🎬 edit pronto: saida/edits/{destino.name} ({' + '.join(ids)})")


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os vídeos da Gemma com Seedance 2.5")
    parser.add_argument("--teste", action="store_true", help="mostra o que seria enviado, sem gastar nada")
    parser.add_argument("--so", metavar="ID", help="gera só a linha da fila com esse id")
    parser.add_argument("--modelo", choices=list(MODELOS), help="troca o modelo só nessa execução (pra comparar)")
    parser.add_argument("--resolucao", choices=["480p", "720p"], help="troca a resolução só nessa execução")
    args = parser.parse_args()

    config = carregar_env()
    chave = config.get("ATLASCLOUD_API_KEY", "")
    if not args.teste and not chave:
        sair("Preencha ATLASCLOUD_API_KEY no .env.")
    cotacao = numero(config, "COTACAO_USD_BRL")
    teto_usd = numero(config, "TETO_SEMANAL_BRL") / cotacao
    modelo = args.modelo or config.get("MODELO", "2.5")
    if modelo not in MODELOS:
        sair(f"MODELO inválido no .env: {modelo}. Opções: {', '.join(MODELOS)}")
    resolucao = args.resolucao or config.get("RESOLUCAO", "480p")
    preco_por_segundo = PRECOS.get((modelo, resolucao)) or numero(config, "PRECO_USD_POR_SEGUNDO")
    # Quando é uma comparação (modelo/resolução trocados na hora), o arquivo ganha o nome do modelo
    sufixo = f"_{modelo}_{resolucao}" if (args.modelo or args.resolucao) else ""
    aumentar = config.get("AUMENTAR_PARA_1080", "nao").lower() in ("sim", "s", "true", "1")

    registro = ler_registro()

    # Pedidos que ficaram sem resposta numa execução anterior (já foram cobrados)
    pendentes = [l for l in registro if l["status"] == "enviado"]
    if pendentes and not args.teste:
        print(f"Retomando {len(pendentes)} pedido(s) pendente(s)...")
        for linha in pendentes:
            print(f"▶ {linha['id']} ({linha['prediction_id']})")
            finalizar(chave, linha, registro, aumentar)

    ja_gerados = {l["id"] for l in registro if l["status"] in STATUS_COBRADOS}
    fila_completa = ler_fila()
    if args.so:
        fila = [l for l in fila_completa if l["id"] == args.so]
        if not fila:
            sair(f"Nenhuma linha com id {args.so} na fila.csv.")
    else:
        fila = [l for l in fila_completa if l["id"] not in ja_gerados]

    if not fila:
        print("Nada pra gerar: todos os vídeos da fila já estão em saida/.")
        if not args.teste:
            juntar_grupos(fila_completa, registro)
        return

    persona = imagens_persona()
    gasto_inicial = gasto_da_semana_usd(registro)
    gasto = gasto_inicial
    print(f"Modelo: Seedance {modelo} | Resolução: {resolucao}{' → aumentada pra 1080p no PC' if aumentar else ''}")
    print(f"Gasto nos últimos 7 dias: US$ {gasto:.2f} de US$ {teto_usd:.2f} (R$ {teto_usd * cotacao:.0f})\n")

    for linha in fila:
        id_video = linha["id"].strip()
        duracao = int(linha["duracao"])
        nome_peca = (linha.get("peca") or "").strip()
        nome_movimento = (linha.get("movimento") or "").strip()
        nome_cenario = (linha.get("cenario") or "").strip()
        peca = arquivo_obrigatorio(PASTA_PECAS, nome_peca, id_video) if nome_peca else None
        cenario = arquivo_obrigatorio(PASTA_CENARIOS, nome_cenario, id_video) if nome_cenario else None
        movimento = arquivo_obrigatorio(PASTA_MOVIMENTOS, nome_movimento, id_video) if nome_movimento else None
        video_limpo = limpar_movimento(movimento, duracao) if movimento else None

        # A Atlas Cloud cobra também os segundos do vídeo de movimento, mas com 40% de desconto
        if video_limpo:
            custo = (duracao + duracao_video(video_limpo)) * preco_por_segundo * 0.6
        else:
            custo = duracao * preco_por_segundo

        print(f"▶ {id_video} — {duracao}s — ~US$ {custo:.2f} (~R$ {custo * cotacao:.2f})")

        if gasto + custo > teto_usd:
            print(f"   ⛔ teto semanal atingido. Parei antes de {id_video}.")
            break

        prompt = montar_prompt(
            len(persona), peca is not None, cenario is not None, movimento is not None, linha["cena"]
        )
        if modelo != "2.5":
            # O Seedance 2.0 cita as referências como "image 1" / "video 1", sem @
            prompt = re.sub(r"@Image(\d+)", r"image \1", prompt)
            prompt = re.sub(r"@Video(\d+)", r"video \1", prompt)
        # Imagem de referência não é cobrada; só o vídeo de movimento entra no preço
        imagens = persona + ([peca] if peca else []) + ([cenario] if cenario else [])

        if args.teste:
            print(f"   imagens: {', '.join(p.name for p in imagens)}")
            print(f"   movimento: {movimento.name if movimento else '(nenhum)'}")
            print(f"   prompt: {prompt}\n")
            gasto += custo
            continue

        payload = {
            "model": MODELOS[modelo],
            "prompt": prompt,
            "reference_images": [imagem_base64(p) for p in imagens],
            "duration": duracao,
            "resolution": resolucao,
            "ratio": "9:16",
            "generate_audio": False,
            "watermark": False,
        }
        if modelo == "2.5":
            payload["output_format"] = "mp4"
            # Valida o pedido na hora do envio em vez de falhar depois (só existe no 2.5)
            payload["omni_reference_task_type"] = "reference"
        if video_limpo:
            print("   ⬆️  enviando vídeo de movimento...")
            payload["reference_videos"] = [enviar_video_referencia(chave, video_limpo)]

        prediction_id = iniciar_geracao(chave, payload)
        gasto += custo
        linha_registro = {
            "data": datetime.now().isoformat(timespec="seconds"),
            "id": id_video,
            "modelo": f"{modelo} {resolucao}",
            "prediction_id": prediction_id,
            "duracao": str(duracao),
            "custo_estimado_usd": f"{custo:.3f}",
            "custo_real_usd": "",
            "status": "enviado",
            "arquivo": "",
            "erro": "",
        }
        # Registra antes de esperar: se o script cair, o pedido não se perde
        registro.append(linha_registro)
        salvar_registro(registro)
        finalizar(chave, linha_registro, registro, aumentar, sufixo)

    if args.teste:
        print(f"Custo estimado dessa fila: US$ {gasto - gasto_inicial:.2f}. Nada foi enviado.")
    else:
        juntar_grupos(fila_completa, registro)


if __name__ == "__main__":
    main()
