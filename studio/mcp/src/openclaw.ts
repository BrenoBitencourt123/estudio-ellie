// Ponte entre o Estúdio Ellie e o OpenClaw (Gateway local). O Estúdio usa o agente "ellie-studio" do OpenClaw
// como IA pela assinatura do Breno (Claude ou GPT), sem chave de API. Os pedidos reaproveitam a sessão
// do seu escopo enquanto ela serve, para aproveitar o cache de prompt do Gateway.
import { randomUUID } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, extname, join, resolve, sep } from "node:path";
import { GatewayClient } from "@openclaw/gateway-client";
import { PROTOCOL_VERSION } from "@openclaw/gateway-protocol/version";

// Lê as opções OPENCLAW_* do .env do projeto (sem depender de quem iniciou a ponte); o ambiente tem prioridade
try {
  for (const linha of readFileSync(resolve(import.meta.dirname, "..", "..", "..", ".env"), "utf8").split(/\r?\n/)) {
    const achado = /^(OPENCLAW_[A-Z_]+)=(.*)$/.exec(linha.trim());
    if (achado && !process.env[achado[1]]) process.env[achado[1]] = achado[2].trim().replace(/^"|"$/g, "");
  }
} catch { /* sem .env: usa os padrões */ }

const URL_GATEWAY = process.env.OPENCLAW_URL ?? "ws://127.0.0.1:18789";
const AGENTE = process.env.OPENCLAW_AGENTE ?? "ellie-studio";
// Só imagens de dentro do projeto da Ellie podem ser enviadas como anexo
const PASTA_PROJETO = resolve(import.meta.dirname, "..", "..", "..");
const TEMPO_CONEXAO_MS = 15_000;
const TIPOS: Record<string, string> = { ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp" };

// Agentes do chat, em ordem de preferência: um agente por modelo (ex.: ellie-claude com Claude pelo
// Claude CLI, ellie-studio com GPT pelo Codex). Cada agente usa o modelo E o runtime/login configurados nele.
// Não forçamos modelo por sessão (sessions.patch): isso desliga o runtime do agente (Codex / Claude CLI)
// e pode cair na API paga. O último recurso é sempre o agente principal (OPENCLAW_AGENTE).
const AGENTES_CHAT = [...new Set([process.env.OPENCLAW_AGENTE_CHAT, process.env.OPENCLAW_AGENTE_RESERVA, AGENTE]
  .map((a) => (a ?? "").trim()).filter(Boolean))];

type Frame = { event: string; payload?: unknown };
type EventoChat = {
  sessionKey?: string; state?: string; errorMessage?: string; deltaText?: string; replace?: boolean; usage?: unknown;
  message?: { content?: { text?: string }[] };
};
type Final = { texto: string; usage?: unknown };
type Espera = {
  resolver: (r: Final) => void; rejeitar: (erro: Error) => void; timer: ReturnType<typeof setTimeout>;
  aoDelta?: (texto: string, substituir: boolean) => void; recebeuTexto?: boolean;
};

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
  if (!espera || !p.state) return;
  if (p.state === "delta") {
    if (typeof p.deltaText === "string") {
      espera.recebeuTexto = true;
      espera.aoDelta?.(p.deltaText, !!p.replace);
    }
    return;
  }
  if (!["final", "error", "aborted"].includes(p.state)) return;
  esperas.delete(p.sessionKey!);
  clearTimeout(espera.timer);
  if (p.state === "final") espera.resolver({ texto: textosDaMensagem(p.message ?? {}).join(""), usage: p.usage });
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

// Sessões reaproveitadas por escopo. Uma sessionKey nova a cada pedido obriga o Gateway a montar o
// agente de novo (~25s) e manda o prompt de sistema inteiro sem cache (~29k tokens): medido 48,3s no
// frio contra 19,1s reaproveitando. Então cada escopo guarda a sua sessão e só troca quando o contexto
// já não serve: depois de JANELA_SESSAO_MS sem uso, depois de MAX_TURNOS_SESSAO pedidos, ou após falha.
const JANELA_SESSAO_MS = 10 * 60_000;
const MAX_TURNOS_SESSAO = 8;
const sessoesPerguntar = new Map<string, { chave: string; expiraEm: number; turnos: number }>();

function chaveDoEscopo(escopo: string): string {
  const agora = Date.now();
  const atual = sessoesPerguntar.get(escopo);
  if (atual && atual.expiraEm > agora && atual.turnos < MAX_TURNOS_SESSAO) {
    atual.expiraEm = agora + JANELA_SESSAO_MS;
    atual.turnos += 1;
    return atual.chave;
  }
  const chave = `agent:${AGENTE}:estudio-${escopo}-${agora}-${randomUUID().slice(0, 8)}`;
  sessoesPerguntar.set(escopo, { chave, expiraEm: agora + JANELA_SESSAO_MS, turnos: 1 });
  return chave;
}

// Manda um pedido (com imagens) ao agente e devolve o texto final da resposta.
// `escopo` separa as sessões por tipo de tarefa: pedidos do mesmo escopo reaproveitam contexto e cache;
// escopos diferentes nunca se misturam.
export async function perguntar(
  texto: string, imagens: string[] = [], tempoMaximoMs = 600_000, escopo = "geral",
): Promise<string> {
  const anexos = imagens.map(anexo);
  await conectar();
  const limpo = /^[a-zA-Z0-9_-]{1,40}$/.test(escopo) ? escopo : "geral";
  const sessionKey = chaveDoEscopo(limpo);
  // Sessão que falhou ou estourou o tempo sai do pool: o próximo pedido do escopo começa limpo
  const descartar = () => {
    if (sessoesPerguntar.get(limpo)?.chave === sessionKey) sessoesPerguntar.delete(limpo);
  };
  const resposta = new Promise<string>((resolver, rejeitar) => {
    const timer = setTimeout(() => {
      esperas.delete(sessionKey);
      descartar();
      rejeitar(new Error(`O OpenClaw demorou mais de ${tempoMaximoMs / 1000}s para responder.`));
    }, tempoMaximoMs);
    esperas.set(sessionKey, {
      resolver: (r) => resolver(r.texto),
      rejeitar: (erro) => { descartar(); rejeitar(erro); },
      timer,
    });
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
    descartar();
    throw new Error(`O OpenClaw recusou o pedido: ${erro instanceof Error ? erro.message : String(erro)}`);
  }
  return resposta;
}

// ---------------------------------------------------------------------------
// Conversa contínua por produção (Fase 2)
// - Uma sessão do OpenClaw por produção e por agente (cada agente = um modelo): o contrato e o contexto vão uma vez ("completo"),
//   depois só o que mudou ("delta"). O histórico fica no OpenClaw, que pode reaproveitar cache de prompt.
// - Modelos em ordem (Claude → GPT): se o primeiro falhar, tenta o próximo com o pedido completo.
// - Repassa o texto parcial (eventos delta) para quem chamou, para mostrar a resposta enquanto chega.
// ---------------------------------------------------------------------------
export type PedidoConversa = {
  sessao: string; completo: string; delta?: string | null; imagensCompleto?: string[]; imagensDelta?: string[];
  modeloAnterior?: string; tempoMaximoMs?: number;
};
export type Tentativa = { modelo: string; erro: string };

// Agente que falhou por motivo que não passa sozinho (versão, login, limite, modelo indisponível) fica de
// fora por um tempo, para não perder ~1 min por mensagem tentando antes da reserva.
const PAUSA_AGENTE_MS = 15 * 60_000;
const pausados = new Map<string, { ate: number; motivo: string }>();
const ERRO_PERSISTENTE = /not support|version|update|limit|limite|reached your|api key|unknown provider|runtime is not available|unauthori|forbidden|expired|login/i;
export type ResultadoConversa = {
  texto: string; modelo: string; modo: "delta" | "completo"; usage?: unknown; segundos: number; tentativas: Tentativa[];
};

const LIMITE_GATEWAY_MS = 180_000;
// Agente que não é o último da fila espera menos antes de dar lugar à reserva: com o prazo cheio
// (600s) um agente travado custava 10 min antes de tentar o próximo. Ao estourar, abortamos o turno
// pelo Gateway (chat.abort) e só então chamamos a reserva, para não deixar dois modelos trabalhando.
const LIMITE_PRIMEIRO_AGENTE_MS = 120_000;

function esperarResposta(sessionKey: string, tempoMaximoMs: number, aoDelta?: Espera["aoDelta"]) {
  let espera!: Espera;
  const promessa = new Promise<Final>((resolver, rejeitar) => {
    const timer = setTimeout(() => {
      esperas.delete(sessionKey);
      rejeitar(Object.assign(new Error(`O OpenClaw demorou mais de ${tempoMaximoMs / 1000}s para responder.`), { tempo: true }));
    }, tempoMaximoMs);
    espera = { resolver, rejeitar, timer, aoDelta };
    esperas.set(sessionKey, espera);
  });
  return { promessa, espera: () => espera };
}

export async function conversar(pedido: PedidoConversa, aoDelta?: (texto: string, substituir: boolean) => void): Promise<ResultadoConversa> {
  if (!/^[a-zA-Z0-9_-]{1,120}$/.test(pedido.sessao)) throw new Error("Sessão inválida.");
  const tentativas: Tentativa[] = [];
  await conectar();
  const ativos = AGENTES_CHAT.filter((a) => (pausados.get(a)?.ate ?? 0) < Date.now());
  const fila = ativos.length ? ativos : AGENTES_CHAT;
  for (const agente of fila) {
    const nome = agente;
    const sessionKey = `agent:${agente}:${pedido.sessao}`;
    const usarDelta = !!pedido.delta && pedido.modeloAnterior === nome;
    const texto = usarDelta ? pedido.delta! : pedido.completo;
    const inicio = Date.now();
    const ehUltimo = agente === fila[fila.length - 1];
    const prazoCheio = pedido.tempoMaximoMs ?? 600_000;
    const prazo = ehUltimo ? prazoCheio : Math.min(LIMITE_PRIMEIRO_AGENTE_MS, prazoCheio);
    try {
      const anexos = (usarDelta ? pedido.imagensDelta ?? [] : pedido.imagensCompleto ?? []).map(anexo);
      const { promessa } = esperarResposta(sessionKey, prazo, aoDelta);
      try {
        await cliente!.request("chat.send", {
          sessionKey, message: texto, idempotencyKey: randomUUID(), ...(anexos.length ? { attachments: anexos } : {}),
        }, { timeoutMs: LIMITE_GATEWAY_MS });
      } catch (erro) {
        const espera = esperas.get(sessionKey);
        if (espera) { clearTimeout(espera.timer); esperas.delete(sessionKey); }
        throw erro;
      }
      const final = await promessa;
      if (!final.texto.trim()) throw new Error("O modelo respondeu vazio.");
      pausados.delete(agente);
      return { texto: final.texto, usage: final.usage, modelo: nome, modo: usarDelta ? "delta" : "completo",
               segundos: (Date.now() - inicio) / 1000, tentativas };
    } catch (erro) {
      const mensagem = erro instanceof Error ? erro.message : String(erro);
      tentativas.push({ modelo: nome, erro: mensagem.slice(0, 400) });
      if (ERRO_PERSISTENTE.test(mensagem) && agente !== AGENTES_CHAT[AGENTES_CHAT.length - 1]) {
        pausados.set(agente, { ate: Date.now() + PAUSA_AGENTE_MS, motivo: mensagem.slice(0, 200) });
        process.stderr.write(`[conversa] ${agente} pausado por 15 min\n`);
      }
      process.stderr.write(`[conversa] ${nome} falhou: ${mensagem}\n`);
      // Estourou o tempo: o modelo pode ainda estar trabalhando. Se ainda há reserva, aborta o turno
      // pelo Gateway antes de chamar o próximo, para nunca ter dois modelos trabalhando em paralelo.
      if ((erro as { tempo?: boolean }).tempo) {
        if (ehUltimo) break;
        try {
          await cliente!.request("chat.abort", { sessionKey }, { timeoutMs: 15_000 });
          process.stderr.write(`[conversa] ${nome} abortado após ${prazo / 1000}s; passando para a reserva\n`);
        } catch (falha) {
          // Não deu para abortar: não arrisca dois turnos em paralelo e para aqui.
          process.stderr.write(`[conversa] não consegui abortar ${nome}: ${falha instanceof Error ? falha.message : String(falha)}\n`);
          break;
        }
      }
      aoDelta?.("", true); // limpa texto parcial antes de tentar o próximo modelo
    }
  }
  throw new Error(tentativas.map((t) => `${t.modelo}: ${t.erro}`).join(" | ") || "Nenhum modelo respondeu.");
}

export const agentesConfigurados = () => AGENTES_CHAT;

// Pasta onde o OpenClaw grava as imagens geradas (só arquivos daqui podem voltar para o Estúdio)
const PASTA_MIDIA_OPENCLAW = join(homedir(), ".openclaw", "media");

type Mensagem = { role?: string; content?: unknown };

const PASTAS_IMAGEM_OPENCLAW = ["tool-image-generation", join("outgoing", "originals")].map((p) => join(PASTA_MIDIA_OPENCLAW, p));
const REGEX_ARQUIVO = /[^\s"'<>|()\[\]]+\.(?:png|jpe?g|webp)/gi;

function textosProfundos(valor: unknown, saida: string[] = []): string[] {
  if (typeof valor === "string") saida.push(valor);
  else if (Array.isArray(valor)) valor.forEach((v) => textosProfundos(v, saida));
  else if (valor && typeof valor === "object") Object.values(valor).forEach((v) => textosProfundos(v, saida));
  return saida;
}

// Procura caminhos de imagem em qualquer parte do histórico (texto "MEDIA:", blocos de imagem, resultado da ferramenta)
export function imagensNoHistorico(mensagens: Mensagem[]): string[] {
  const caminhos = new Set<string>();
  for (const m of mensagens) {
    if (m.role === "user") continue;
    for (const texto of textosProfundos(m)) {
      for (const achado of texto.matchAll(REGEX_ARQUIVO)) {
        const bruto = achado[0].replace(/^MEDIA:/i, "").replace(/^file:\/\//i, "");
        const direto = resolve(bruto);
        if (direto.startsWith(PASTA_MIDIA_OPENCLAW + sep) && existsSync(direto)) { caminhos.add(direto); continue; }
        for (const pasta of PASTAS_IMAGEM_OPENCLAW) {
          const candidato = join(pasta, basename(bruto.replace(/\\/g, "/")));
          if (existsSync(candidato)) { caminhos.add(candidato); break; }
        }
      }
    }
  }
  return [...caminhos];
}

export function imagensNovas(desde: number): string[] {
  const pasta = PASTAS_IMAGEM_OPENCLAW[0];
  if (!existsSync(pasta)) return [];
  return readdirSync(pasta).filter((n) => /\.(png|jpe?g|webp)$/i.test(n)).map((n) => join(pasta, n))
    .map((c) => ({ c, t: statSync(c).mtimeMs })).filter((x) => x.t >= desde - 2000).sort((a, b) => a.t - b.t).map((x) => x.c);
}

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
    const mensagens = historico.messages ?? [];
    const achadas = imagensNoHistorico(mensagens);
    if (achadas.length) return achadas;
    // A resposta terminou (DONE) mas o caminho não veio no texto: pega o arquivo novo da ferramenta de imagem
    const terminou = mensagens.some((m) => m.role === "assistant" && textosDaMensagem(m).some((t) => /\bDONE\b/.test(t)));
    if (terminou) {
      const novas = imagensNovas(inicio);
      if (novas.length) return novas.slice(-1);
    }
  }
  throw new Error(`A imagem não ficou pronta em ${tempoMaximoMs / 1000}s.`);
}

export async function status(): Promise<{ conectado: boolean; agente: string; existe: boolean; modelos?: string[]; erro?: string }> {
  try {
    await conectar();
    const lista = (await cliente!.request("agents.list", {})) as { agents?: { id: string }[] };
    const ids = new Set((lista.agents ?? []).map((a) => a.id));
    const faltando = AGENTES_CHAT.filter((a) => !ids.has(a));
    const pausa = [...pausados].filter(([, v]) => v.ate > Date.now()).map(([k, v]) => ({ agente: k, motivo: v.motivo, ate: new Date(v.ate).toISOString() }));
    return { conectado: true, agente: AGENTE, existe: ids.has(AGENTE), modelos: AGENTES_CHAT.filter((a) => ids.has(a)), pausados: pausa,
             ...(faltando.length ? { erro: `Agente(s) não registrado(s) no OpenClaw: ${faltando.join(", ")}` } : {}) };
  } catch (erro) {
    return { conectado: false, agente: AGENTE, existe: false, erro: erro instanceof Error ? erro.message : String(erro) };
  }
}
