// Servidor MCP do Estúdio Ellie.
//   npm start         → HTTP em http://127.0.0.1:8790/mcp (streamable-http, sem sessão)
//   npm run stdio     → stdio, para clientes que abrem o processo (ex.: Claude Code, Claude Desktop)
// Só fala com o Estúdio local (studio/server.py). Não gera vídeo nem gasta: deixa rascunhos para o Breno.
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { URL_ESTUDIO } from "./estudio.ts";
import { criarServidorMcp } from "./processo-ferramentas.ts";
import { conversar, gerarImagem, perguntar, status, type PedidoConversa } from "./openclaw.ts";

const PORTA = Number(process.env.PORTA_MCP ?? 8790);
// Pedidos em andamento ao OpenClaw: o supervisor só reinicia a ponte quando isto chega a zero
let emAndamento = 0;
async function contando<T>(trabalho: () => Promise<T>): Promise<T> {
  emAndamento++;
  try { return await trabalho(); } finally { emAndamento--; }
}
const LIMITE_CORPO = 1_000_000;
// No modo stdio o stdout é do protocolo, então todo log vai para o stderr
const log = (...partes: unknown[]) => process.stderr.write(`[estudio-mcp ${new Date().toLocaleTimeString("pt-BR")}] ${partes.join(" ")}\n`);

if (process.argv.includes("--stdio")) {
  await criarServidorMcp().connect(new StdioServerTransport());
  log(`stdio pronto (Estúdio em ${URL_ESTUDIO})`);
} else {
  const HOSTS = [`127.0.0.1:${PORTA}`, `localhost:${PORTA}`];

  // Só aceita chamadas deste PC: bloqueia sites abertos no navegador (e DNS rebinding)
  const origemConfiavel = (req: IncomingMessage) => {
    if (!HOSTS.includes(req.headers.host ?? "")) return false;
    const origem = req.headers.origin;
    return !origem || HOSTS.some((h) => origem === `http://${h}`);
  };

  async function lerJson(req: IncomingMessage): Promise<unknown> {
    let tamanho = 0;
    const partes: Buffer[] = [];
    for await (const parte of req) {
      tamanho += (parte as Buffer).length;
      if (tamanho > LIMITE_CORPO) throw new Error("corpo grande demais");
      partes.push(parte as Buffer);
    }
    const corpo = Buffer.concat(partes).toString("utf8");
    return corpo ? JSON.parse(corpo) : {};
  }

  const responderJson = (res: ServerResponse, codigo: number, corpo: unknown) =>
    void res.writeHead(codigo, { "Content-Type": "application/json; charset=utf-8" }).end(JSON.stringify(corpo));

  async function tratar(req: IncomingMessage, res: ServerResponse) {
    const caminho = new URL(req.url ?? "/", `http://${HOSTS[0]}`).pathname;
    if (!origemConfiavel(req)) return void res.writeHead(403).end("origem não permitida");

    // Ponte com o OpenClaw, usada pelo servidor do Estúdio (studio/server.py)
    if (caminho === "/ia/status" && req.method === "GET") return responderJson(res, 200, await status());
    if (caminho === "/ia/ocupado" && req.method === "GET") return responderJson(res, 200, { ocupado: emAndamento > 0, emAndamento });
    if (caminho === "/ia/perguntar" && req.method === "POST") {
      const corpo = (await lerJson(req)) as { texto?: unknown; imagens?: unknown; tempo_maximo_s?: unknown };
      if (typeof corpo.texto !== "string" || !corpo.texto.trim()) return responderJson(res, 400, { erro: "texto vazio" });
      const imagens = Array.isArray(corpo.imagens) ? corpo.imagens.filter((i): i is string => typeof i === "string") : [];
      const tempo = typeof corpo.tempo_maximo_s === "number" ? Math.min(600, corpo.tempo_maximo_s) * 1000 : undefined;
      try {
        const inicio = Date.now();
        const texto = await contando(() => perguntar(corpo.texto as string, imagens, tempo));
        log(`OpenClaw respondeu em ${((Date.now() - inicio) / 1000).toFixed(1)}s`);
        return responderJson(res, 200, { texto });
      } catch (erro) {
        return responderJson(res, 502, { erro: erro instanceof Error ? erro.message : String(erro) });
      }
    }

    // Conversa contínua com streaming: responde NDJSON, uma linha por pedaço de texto e uma linha final
    if (caminho === "/ia/conversar" && req.method === "POST") {
      const corpo = (await lerJson(req)) as Partial<PedidoConversa>;
      if (typeof corpo.sessao !== "string" || typeof corpo.completo !== "string" || !corpo.completo.trim()) {
        return responderJson(res, 400, { erro: "pedido inválido" });
      }
      res.writeHead(200, { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-cache" });
      const linha = (obj: unknown) => res.write(JSON.stringify(obj) + "\n");
      try {
        const resultado = await contando(() => conversar({
          sessao: corpo.sessao, completo: corpo.completo, delta: typeof corpo.delta === "string" ? corpo.delta : null,
          imagensCompleto: Array.isArray(corpo.imagensCompleto) ? corpo.imagensCompleto.filter((i) => typeof i === "string") : [],
          imagensDelta: Array.isArray(corpo.imagensDelta) ? corpo.imagensDelta.filter((i) => typeof i === "string") : [],
          modeloAnterior: typeof corpo.modeloAnterior === "string" ? corpo.modeloAnterior : undefined,
          tempoMaximoMs: typeof corpo.tempoMaximoMs === "number" ? Math.min(600_000, corpo.tempoMaximoMs) : undefined,
        }, (texto, substituir) => linha({ delta: texto, substituir })));
        log(`OpenClaw (${resultado.modelo}, ${resultado.modo}) respondeu em ${resultado.segundos.toFixed(1)}s`);
        linha({ fim: resultado });
      } catch (erro) {
        linha({ erro: erro instanceof Error ? erro.message : String(erro) });
      }
      return void res.end();
    }

    if (caminho === "/ia/imagem" && req.method === "POST") {
      const corpo = (await lerJson(req)) as { prompt?: unknown; proporcao?: unknown; referencias?: unknown; instrucao_referencias?: unknown };
      if (typeof corpo.prompt !== "string" || corpo.prompt.trim().length < 5) return responderJson(res, 400, { erro: "prompt vazio" });
      const referencias = Array.isArray(corpo.referencias) ? corpo.referencias.filter((i): i is string => typeof i === "string") : [];
      try {
        const inicio = Date.now();
        const arquivos = await contando(() => gerarImagem(
          corpo.prompt as string, typeof corpo.proporcao === "string" ? corpo.proporcao : "9:16", referencias, undefined,
          typeof corpo.instrucao_referencias === "string" ? corpo.instrucao_referencias : "",
        ));
        log(`Imagem gerada pelo OpenClaw em ${((Date.now() - inicio) / 1000).toFixed(1)}s`);
        return responderJson(res, 200, { arquivos });
      } catch (erro) {
        return responderJson(res, 502, { erro: erro instanceof Error ? erro.message : String(erro) });
      }
    }

    if (caminho !== "/mcp") return void res.writeHead(404).end("use /mcp");
    if (req.method !== "POST") return void res.writeHead(405, { Allow: "POST" }).end();
    const corpo = await lerJson(req);
    const servidor = criarServidorMcp();
    const transporte = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on("close", () => {
      void transporte.close();
      void servidor.close();
    });
    await servidor.connect(transporte);
    await transporte.handleRequest(req, res, corpo);
  }

  createServer((req, res) => {
    tratar(req, res).catch((erro) => {
      log("erro:", erro instanceof Error ? erro.message : String(erro));
      if (!res.headersSent) res.writeHead(400).end("requisição inválida");
    });
  }).listen(PORTA, "127.0.0.1", () => {
    log(`MCP em http://127.0.0.1:${PORTA}/mcp (Estúdio em ${URL_ESTUDIO})`);
  });
}
