// Ponte entre o Estúdio Ellie e o OpenClaw (Gateway local). O Estúdio usa o agente "ellie-studio" do OpenClaw
// como IA pela assinatura do Breno (Claude ou GPT), sem chave de API. Cada pedido abre uma sessão nova,
// com o contexto selecionado pelo aplicativo, sem duplicar o histórico no Gateway.
import { randomUUID } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { GatewayClient } from "@openclaw/gateway-client";
import { PROTOCOL_VERSION } from "@openclaw/gateway-protocol/version";

const URL_GATEWAY = process.env.OPENCLAW_URL ?? "ws://127.0.0.1:18789";
const AGENTE = process.env.OPENCLAW_AGENTE ?? "ellie-studio";
// Só imagens de dentro do projeto da Ellie podem ser enviadas como anexo
const PASTA_PROJETO = resolve(import.meta.dirname, "..", "..", "..");
const TEMPO_CONEXAO_MS = 15_000;
const TIPOS: Record<string, string> = { ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp" };

type Frame = { event: string; payload?: unknown };
type EventoChat = { sessionKey?: string; state?: string; errorMessage?: string; message?: { content?: { text?: string }[] } };
type Espera = { resolver: (texto: string) => void; rejeitar: (erro: Error) => void; timer: ReturnType<typeof setTimeout> };

let cliente: GatewayClient | null = null;
let conectado: Promise<void> | null = null;
const esperas = new Map<string, Espera>();

function lerToken(): string {
  if (process.env.OPENCLAW_GATEWAY_TOKEN) return process.env.OPENCLAW_GATEWAY_TOKEN;
  const caminho = process.env.OPENCLAW_CONFIG_PATH ?? join(homedir(), ".openclaw", "openclaw.json");
  let cfg: { gateway?: { auth?: { token?: string } } };
  try { cfg = JSON.parse(readFileSync(caminho, "utf8")) as typeof cfg; }
  catch { throw new Error("Abra o OpenClaw, conecte a assinatura e configure o Gateway local antes de conversar."); }
  const token = cfg.gateway?.auth?.token;
  if (!token) throw new Error("Token do Gateway não encontrado no openclaw.json.");
  return token;
}

function aoEvento(frame: Frame): void {
  if (frame.event !== "chat") return;
  const p = (frame.payload ?? {}) as EventoChat;
  const espera = p.sessionKey ? esperas.get(p.sessionKey) : undefined;
  if (!espera || !p.state || !["final", "error", "aborted"].includes(p.state)) return;
  esperas.delete(p.sessionKey!);
  clearTimeout(espera.timer);
  if (p.state === "final") espera.resolver(textosDaMensagem(p.message ?? {}).join(""));
  else espera.rejeitar(new Error(p.errorMessage ?? "O OpenClaw não concluiu a resposta."));
}

function desconectar(): void {
  cliente?.stop();
  cliente = null;
  conectado = null;
}

function conectar(): Promise<void> {
  if (conectado) return conectado;
  // Uma configuração ausente não pode deixar uma Promise rejeitada presa para sempre.
  const token = lerToken();
  conectado = new Promise<void>((ok, falha) => {
    const timer = setTimeout(() => {
      desconectar();
      falha(new Error("O Gateway do OpenClaw não respondeu. Abra-o no ambiente configurado e verifique novamente."));
    }, TEMPO_CONEXAO_MS);
    const novo = new GatewayClient({
      url: URL_GATEWAY,
      token,
      clientName: "gateway-client",
      clientDisplayName: "Estúdio Ellie",
      mode: "backend",
      platform: "windows",
      role: "operator",
      scopes: ["operator.read", "operator.write"],
      minProtocol: PROTOCOL_VERSION,
      maxProtocol: PROTOCOL_VERSION,
      onHelloOk: () => {
        clearTimeout(timer);
        ok();
      },
      onConnectError: (erro) => {
        clearTimeout(timer);
        desconectar();
        falha(new Error(`Não consegui conectar no OpenClaw: ${erro instanceof Error ? erro.message : String(erro)}`));
      },
      onClose: () => {
        // Conexão caiu: os pedidos em andamento falham e o próximo pedido reconecta
        for (const [chave, espera] of esperas) {
          clearTimeout(espera.timer);
          espera.rejeitar(new Error("A conexão com o OpenClaw caiu."));
          esperas.delete(chave);
        }
        desconectar();
      },
      onEvent: (frame) => aoEvento(frame as Frame),
    });
    cliente = novo;
    novo.start();
  });
  return conectado;
}

function anexo(caminho: string) {
  const absoluto = resolve(caminho);
  if (!absoluto.startsWith(PASTA_PROJETO + sep)) throw new Error(`Imagem fora do projeto: ${caminho}`);
  const mimeType = TIPOS[extname(absoluto).toLowerCase()];
  if (!mimeType) throw new Error(`Formato de imagem não aceito: ${caminho}`);
  const bytes = readFileSync(absoluto);
  return { type: "image", fileName: absoluto.split(sep).pop()!, mimeType, content: bytes.toString("base64"), sizeBytes: statSync(absoluto).size };
}

// Manda um pedido (com imagens) ao agente e devolve o texto final da resposta
export async function perguntar(texto: string, imagens: string[] = [], tempoMaximoMs = 600_000): Promise<string> {
  const anexos = imagens.map(anexo);
  await conectar();
  const sessionKey = `agent:${AGENTE}:estudio-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const resposta = new Promise<string>((resolver, rejeitar) => {
    const timer = setTimeout(() => {
      esperas.delete(sessionKey);
      rejeitar(new Error(`O OpenClaw demorou mais de ${tempoMaximoMs / 1000}s para responder.`));
    }, tempoMaximoMs);
    esperas.set(sessionKey, { resolver, rejeitar, timer });
  });
  try {
    await cliente!.request("chat.send", {
      sessionKey,
      message: texto,
      idempotencyKey: randomUUID(),
      ...(anexos.length ? { attachments: anexos } : {}),
    });
  } catch (erro) {
    const espera = esperas.get(sessionKey);
    if (espera) {
      clearTimeout(espera.timer);
      esperas.delete(sessionKey);
    }
    throw new Error(`O OpenClaw recusou o pedido: ${erro instanceof Error ? erro.message : String(erro)}`);
  }
  return resposta;
}

// Pasta onde o OpenClaw grava as imagens geradas (só arquivos daqui podem voltar para o Estúdio)
const PASTA_MIDIA_OPENCLAW = join(homedir(), ".openclaw", "media");
const REGEX_MIDIA = /MEDIA:\s*(.+?\.(?:png|jpe?g|webp))/gi;

type Mensagem = { role?: string; content?: unknown };

function textosDaMensagem(m: Mensagem): string[] {
  if (typeof m.content === "string") return [m.content];
  if (!Array.isArray(m.content)) return [];
  return m.content.map((c) => (c as { text?: string }).text ?? "").filter(Boolean);
}

// Gera imagem(ns) com a ferramenta image_generate do OpenClaw. A geração roda em segundo plano:
// o agente responde logo e, quando a imagem fica pronta, escreve "MEDIA:<caminho>" na mesma sessão.
export async function gerarImagem(
  prompt: string, proporcao = "9:16", referencias: string[] = [], tempoMaximoMs = 300_000, instrucaoReferencias = "",
): Promise<string[]> {
  const anexos = referencias.map(anexo);
  await conectar();
  const sessionKey = `agent:${AGENTE}:imagem-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const instrucao = [
    `Use your image generation tool now to create ONE image with aspect ratio ${proporcao}.`,
    anexos.length
      ? instrucaoReferencias ||
        "The attached images are references: pass them to the image tool as reference images and keep the same person (face, hair, body) and style."
      : "",
    `Image request (if it is not in English, translate it into a clear English image prompt before calling the tool): ${prompt}`,
    "When the image is ready, reply with only the word DONE.",
  ].filter(Boolean).join("\n");
  await cliente!.request("chat.send", {
    sessionKey, message: instrucao, idempotencyKey: randomUUID(), ...(anexos.length ? { attachments: anexos } : {}),
  });
  const inicio = Date.now();
  while (Date.now() - inicio < tempoMaximoMs) {
    await new Promise((r) => setTimeout(r, 4000));
    const historico = (await cliente!.request("chat.history", { sessionKey, limit: 30 })) as { messages?: Mensagem[] };
    const caminhos = new Set<string>();
    for (const m of historico.messages ?? []) {
      if (m.role !== "assistant") continue;
      for (const texto of textosDaMensagem(m)) {
        for (const achado of texto.matchAll(REGEX_MIDIA)) {
          const caminho = resolve(achado[1].trim());
          if (caminho.startsWith(PASTA_MIDIA_OPENCLAW + sep)) caminhos.add(caminho);
        }
      }
    }
    if (caminhos.size) return [...caminhos];
  }
  throw new Error(`A imagem não ficou pronta em ${tempoMaximoMs / 1000}s.`);
}

export async function status(): Promise<{ conectado: boolean; agente: string; existe: boolean; erro?: string }> {
  try {
    await conectar();
    const lista = (await cliente!.request("agents.list", {})) as { agents?: { id: string }[] };
    return { conectado: true, agente: AGENTE, existe: (lista.agents ?? []).some((a) => a.id === AGENTE) };
  } catch (erro) {
    return { conectado: false, agente: AGENTE, existe: false, erro: erro instanceof Error ? erro.message : String(erro) };
  }
}
