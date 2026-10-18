import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { estudio, URL_INTERFACE } from "./estudio.ts";

type Conteudo = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };
type Resultado = { content: Conteudo[]; isError?: boolean };

const texto = (t: string): Resultado => ({ content: [{ type: "text", text: t }] });

// Erro vira texto legível para o modelo repassar, em vez de derrubar a conversa
const seguro = <A>(fn: (args: A) => Promise<Resultado>) => async (args: A): Promise<Resultado> => {
  try {
    return await fn(args);
  } catch (erro) {
    return { ...texto("Erro: " + (erro instanceof Error ? erro.message : String(erro))), isError: true };
  }
};

// Respostas da API do Estúdio (só os campos usados aqui)
interface Config {
  modelos: string[];
  modelos_kling: string[];
  precos: Record<string, number>;
  gasto_semana_usd: number;
  teto_usd: number;
  cotacao: number;
  chave_configurada: boolean;
}
type Assets = Record<string, string[]>;
interface ItemHistorico {
  data: string;
  id: string;
  modelo: string;
  duracao: string;
  custo_estimado_usd: string;
  custo_real_usd: string;
  status: string;
  arquivo: string;
  arquivo_1080: string;
  erro: string;
  prompt: string;
  pilar: string;
}
interface Aprendizado {
  configs: { modo: string; modelo: string; gerados: number; falhas: number; bons: number; ruins: number; aprovacao: number | null; custo_por_aprovado: number | null; custo_medio: number | null }[];
  problemas: { nome: string; vezes: number; como_corrigir: string }[];
  pilares: { pilar: string; videos: number; meta: number; fatia: number; views_media: number | null; conclusao_media: number | null; seguidores_por_100_views: number | null }[];
  vencedores: { arquivo: string; modo: string; modelo: string; custo_usd: number; pilar: string; prompt: string; views: number | null; conclusao_pct: number | null; seguidores: number | null; pedido: Record<string, unknown> }[];
  rejeicoes_kling: { movimento: string; vezes: number }[];
  recomendacoes: string[];
  modos: Record<string, string>;
}
interface Rascunho {
  id: string;
  repetidos: { arquivo: string; nota: string }[];
  dica: string;
  criado: string;
  nota: string;
  prompt: string;
  custo_usd: number;
  custo_brl: number;
  passa_do_teto: boolean;
  pedido: { nome: string; tipo: string; modelo: string; resolucao: string; duracao: number; pilar: string };
}

const PILARES = ["outfit_clima", "pov_london", "lugar"] as const;
const PROBLEMAS = ["maos", "rosto", "roupa", "movimento", "cenario", "texto", "enquadramento", "objeto", "artefatos", "loop", "sem_graca"] as const;
const META_PILAR: Record<string, number> = { outfit_clima: 0.7, pov_london: 0.2, lugar: 0.1 };
const PASTAS = ["persona", "pecas", "cenarios", "base", "movimentos"] as const;
const MODELOS = ["2.0-mini", "2.0-fast", "2.0", "2.5", "kling-2.6-std", "kling-2.6-pro", "kling-3.0-std", "kling-3.0-pro"] as const;

const usd = (v: number) => `US$ ${v.toFixed(2)}`;
// Falha não é cobrada pela Atlas: mostra o custo só do que foi enviado ou concluído
const custoItem = (i: ItemHistorico) =>
  ["ok", "enviado"].includes(i.status) ? usd(Number(i.custo_real_usd || i.custo_estimado_usd || 0)) : "não cobrado";

// Diz qual pilar está mais atrás da meta (70/20/10) nos últimos vídeos prontos
function balancoPilares(itens: ItemHistorico[]): string {
  const prontos = itens.filter((i) => i.status === "ok").slice(0, 20);
  const comPilar = prontos.filter((i) => i.pilar);
  if (comPilar.length === 0) {
    return "Pilares: os vídeos recentes ainda não têm pilar registrado. Comece a marcar o pilar em cada rascunho.";
  }
  const linhas = PILARES.map((p) => {
    const qtd = comPilar.filter((i) => i.pilar === p).length;
    const fatia = qtd / comPilar.length;
    return { p, qtd, fatia, falta: META_PILAR[p] - fatia };
  });
  const atras = [...linhas].sort((a, b) => b.falta - a.falta)[0];
  return [
    `Pilares nos últimos ${comPilar.length} vídeos com pilar (meta 70/20/10):`,
    ...linhas.map((l) => `- ${l.p}: ${l.qtd} (${Math.round(l.fatia * 100)}%, meta ${META_PILAR[l.p] * 100}%)`),
    atras.falta > 0.05 ? `Mais atrás da meta: ${atras.p}.` : "A grade está equilibrada.",
  ].join("\n");
}

export function criarServidorMcp(): McpServer {
  const servidor = new McpServer({ name: "estudio-ellie", version: "0.1.0" });

  servidor.registerTool("panorama", {
    title: "Panorama do Estúdio Ellie",
    description:
      "Comece por aqui. Mostra o gasto da semana e o teto, os modelos e preços, o que há na biblioteca de referências " +
      "(fotos da Ellie, peças, cenários, imagens base, vídeos de movimento), os rascunhos esperando o Breno, " +
      "os últimos vídeos gerados e qual pilar de conteúdo está atrás da meta 70/20/10.",
    inputSchema: {},
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async () => {
    const [config, assets, historico, rascunhos, aprendizado] = await Promise.all([
      estudio.get<Config>("/api/config"),
      estudio.get<Assets>("/api/assets"),
      estudio.get<ItemHistorico[]>("/api/historico"),
      estudio.get<Rascunho[]>("/api/rascunhos"),
      estudio.get<Aprendizado>("/api/aprendizado"),
    ]);
    const restante = Math.max(0, config.teto_usd - config.gasto_semana_usd);
    const biblioteca = PASTAS.map((p) => {
      const itens = assets[p] ?? [];
      const lista = itens.slice(0, 25).join(", ") + (itens.length > 25 ? `, ... (+${itens.length - 25})` : "");
      return `- ${p} (${itens.length}): ${lista || "vazia"}`;
    });
    const precos = Object.entries(config.precos).map(([k, v]) => `${k.replace("|-", "")} ${v}`).join(" · ");
    const ultimos = historico.slice(0, 10).map((i) =>
      `- ${i.data.replace("T", " ")} · ${i.arquivo_1080 || i.arquivo || i.id} · ${i.modelo || "?"} · ${i.duracao}s · ` +
      `${custoItem(i)} · ${i.status}${i.pilar ? ` · ${i.pilar}` : ""}${i.erro ? ` · erro: ${i.erro.slice(0, 90)}` : ""}`);
    const pendentes = rascunhos.map((r) =>
      `- ${r.id} · ${r.pedido.nome || "(sem nome)"} · ${r.pedido.tipo} · ${r.pedido.modelo} · ${r.pedido.duracao}s · ` +
      `${usd(r.custo_usd)} · ${r.pedido.pilar || "sem pilar"}${r.passa_do_teto ? " · PASSA DO TETO" : ""}`);
    return texto([
      `Gasto nos últimos 7 dias: ${usd(config.gasto_semana_usd)} de ${usd(config.teto_usd)} (resta ${usd(restante)}).`,
      config.chave_configurada ? "" : "ATENÇÃO: falta a chave da Atlas Cloud no .env, o Breno não vai conseguir gerar.",
      `Preços (US$ por segundo; modelo|resolução): ${precos}`,
      "",
      "Biblioteca:",
      ...biblioteca,
      "",
      `Rascunhos esperando o Breno (${rascunhos.length}):`,
      ...(pendentes.length ? pendentes : ["- nenhum"]),
      "",
      "Últimos vídeos:",
      ...(ultimos.length ? ultimos : ["- nenhum ainda"]),
      "",
      balancoPilares(historico),
      "",
      "O que o autoestudo recomenda agora:",
      ...(aprendizado.recomendacoes.length ? aprendizado.recomendacoes.map((r) => `- ${r}`) : ["- ainda sem dados suficientes"]),
    ].filter((l) => l !== "").join("\n"));
  }));

  servidor.registerTool("regras_do_perfil", {
    title: "Regras do perfil e da cena",
    description:
      "O guia de produção da Ellie Hartley: objetivo (500 seguidores), persona, pilares, formato que funciona " +
      "(7 a 9s, loop, enquadramento sem cabeça), custos, diferenças entre Seedance e Kling, e as regras para " +
      "escrever a cena em cada modo. Leia uma vez por conversa, antes de preparar vídeos.",
    inputSchema: {},
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async () => {
    const r = await estudio.get<{ perfil: string; cena: string }>("/api/regras");
    return texto(`${r.perfil}\n\n## Como escrever a cena (campo "cena", em inglês)\n${r.cena}`);
  }));

  servidor.registerTool("ver_biblioteca", {
    title: "Ver uma pasta da biblioteca",
    description:
      "Devolve uma folha numerada com as imagens de uma pasta (de vídeos de movimento, um quadro de cada) e a lista " +
      "número → nome do arquivo. Pastas: persona (fotos de rosto da Ellie, para o Seedance), pecas (roupas), " +
      "cenarios (lugares), base (imagem única da Ellie vestida, para o Kling), movimentos (vídeos de referência). " +
      "Use o NOME do arquivo ao preparar o vídeo.",
    inputSchema: {
      pasta: z.enum(PASTAS).describe("Qual pasta ver"),
      pagina: z.number().int().min(1).default(1).describe("Página (12 itens por folha)"),
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async ({ pasta, pagina }) => {
    const r = await estudio.post<{ url: string; itens: { n: number; nome: string; duracao_s?: number }[]; pagina: number; paginas: number; total: number }>(
      "/api/folha", { pasta, pagina });
    if (!r.url) return texto(`A pasta ${pasta} está vazia (ou não tem a página ${pagina}). O Breno sobe arquivos pelo Estúdio.`);
    const lista = r.itens.map((i) => `${i.n}. ${i.nome}${i.duracao_s !== undefined ? ` (${i.duracao_s}s)` : ""}`).join("\n");
    return {
      content: [
        { type: "image", ...(await estudio.imagem(r.url)) },
        { type: "text", text: `${pasta}: página ${r.pagina} de ${r.paginas} (${r.total} itens)\n${lista}` },
      ],
    };
  }));

  servidor.registerTool("ver_video", {
    title: "Ver quadros de um vídeo",
    description:
      "Mostra quadros em ordem de um vídeo, numa folha numerada. Duas utilidades: " +
      "(1) fonte=movimentos: antes de usar um vídeo de movimento, confira enquadramento, se a cabeça e o tronco aparecem " +
      "(o Kling exige), em qual mão está o celular, se há texto ou marca d'água em cima do corpo e qual trecho é melhor; " +
      "(2) fonte=saida: depois que o Breno gerar, revise o resultado (mãos, rosto, roupa fiel à peça, objeto flutuando, " +
      "texto indesejado, loop) e proponha o ajuste. O nome do arquivo gerado aparece no panorama e no histórico.",
    inputSchema: {
      fonte: z.enum(["movimentos", "saida"]).describe("movimentos = vídeo de referência; saida = vídeo já gerado"),
      arquivo: z.string().min(1).describe("Nome do arquivo, ex.: giro.mp4 ou v07_1080.mp4"),
      inicio: z.number().min(0).default(0).describe("Começar em quantos segundos"),
      duracao: z.number().positive().optional().describe("Quantos segundos olhar (padrão: até o fim)"),
      quantidade: z.number().int().min(2).max(12).default(8).describe("Quantos quadros"),
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async ({ fonte, arquivo, inicio, duracao, quantidade }) => {
    const r = await estudio.post<{ url: string; duracao_total_s: number; inicio_s: number; trecho_s: number; quadros: number }>(
      "/api/quadros", { fonte, arquivo, inicio, duracao, quantidade });
    return {
      content: [
        { type: "image", ...(await estudio.imagem(r.url)) },
        {
          type: "text",
          text: `${arquivo}: ${r.duracao_total_s}s no total. Folha com ${r.quadros} quadros de ${r.inicio_s}s a ` +
            `${(r.inicio_s + r.trecho_s).toFixed(1)}s, em ordem (1 = primeiro).`,
        },
      ],
    };
  }));

  servidor.registerTool("preparar_video", {
    title: "Preparar um vídeo (rascunho para o Breno gerar)",
    description:
      "Valida o vídeo, monta o prompt final com as regras fixas de consistência, calcula o custo e deixa um RASCUNHO " +
      "no Estúdio. NÃO gera nem gasta nada: o Breno abre o rascunho no Estúdio e clica em Gerar. " +
      "Escreva só a cena (inglês britânico, regras em regras_do_perfil); identidade, roupa, lugar e 'sem texto' o servidor já põe. " +
      "Seedance Ellie: persona (1 a 4 fotos) + peca/cenario opcionais + movimento opcional. " +
      "Kling Ellie: imagem_base + movimento (obrigatórios). Lugar: tipo=lugar + cenario (só Seedance). " +
      "Comece pelo modelo barato (2.0-fast 720p ou kling-2.6-std) e 7 a 9s.",
    inputSchema: {
      nome: z.string().min(2).max(40).describe("Nome curto do arquivo em snake_case, ex.: v12_casaco_chuva"),
      pilar: z.enum(PILARES).describe("Pilar de conteúdo deste vídeo"),
      nota: z.string().min(10).max(600).describe("Para o Breno, em português: a ideia, por que ela ajuda o perfil agora e o que conferir no resultado"),
      tipo: z.enum(["ellie", "lugar"]).default("ellie"),
      modelo: z.enum(MODELOS).default("2.0-fast").describe("Seedance: 2.0-mini, 2.0-fast, 2.0, 2.5. Kling: kling-*"),
      resolucao: z.enum(["480p", "720p"]).default("720p").describe("Só Seedance"),
      duracao: z.number().int().min(4).max(15).default(8).describe("Segundos do vídeo (no Kling, o trecho do movimento)"),
      cena: z.string().max(600).default("").describe("A cena em inglês (obrigatória no Seedance; opcional e curta no Kling)"),
      camera: z.string().max(120).default("").describe(
        "Uma direção de câmera em inglês, só SEM vídeo de movimento (ex.: static tripod mirror shot, slow dolly in, handheld selfie, slow pan right). É o que mais muda o resultado no Seedance."),
      persona: z.array(z.string()).max(4).default([]).describe("Fotos de rosto da pasta persona (Seedance Ellie)"),
      peca: z.string().optional().describe("Arquivo da pasta pecas"),
      cenario: z.string().optional().describe("Arquivo da pasta cenarios (no tipo lugar, a foto do lugar)"),
      movimento: z.string().optional().describe("Arquivo da pasta movimentos"),
      movimento_inicio: z.number().min(0).default(0).describe("Em que segundo do vídeo de movimento começar"),
      imagem_base: z.string().optional().describe("Arquivo da pasta base (Kling)"),
      orientacao: z.enum(["video", "image"]).default("video").describe("Kling: corpo segue o vídeo ou a imagem"),
      objeto: z.string().max(80).default("").describe("Objeto que ela segura, em inglês (ex.: a beige phone)"),
      mao: z.enum(["", "right", "left"]).default("").describe("Mão que segura o objeto (obrigatória se houver objeto)"),
      substitui: z.string().optional().describe("Id de um rascunho anterior que este substitui"),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, seguro(async (a) => {
    const pedido = {
      nome: a.nome, tipo: a.tipo, pilar: a.pilar, modelo: a.modelo, resolucao: a.resolucao, duracao: a.duracao,
      cena: a.cena, camera: a.camera, persona: a.persona, peca: a.peca ?? null, cenario: a.cenario ?? null, movimento: a.movimento ?? null,
      movimento_inicio: a.movimento_inicio, imagem_base: a.imagem_base ?? null, orientacao: a.orientacao,
      objeto: a.objeto, mao: a.mao, aumentar_1080: true,
    };
    const r = await estudio.post<Rascunho & { segundos_movimento: number }>(
      "/api/rascunhos", { pedido, nota: a.nota, substitui: a.substitui ?? "", origem: "assistente" });
    return texto([
      `Rascunho ${r.id} pronto (${r.pedido.nome}). Nada foi gerado nem cobrado.`,
      `Custo quando o Breno gerar: ${usd(r.custo_usd)} (R$ ${r.custo_brl.toFixed(2).replace(".", ",")})` +
        (r.segundos_movimento ? `, com ${r.segundos_movimento}s de vídeo de movimento` : "") + ".",
      r.passa_do_teto ? "ATENÇÃO: passa do teto semanal. O Estúdio vai recusar até o Breno aumentar o teto." : "",
      r.repetidos.length
        ? `ATENÇÃO: já existe vídeo idêntico (${r.repetidos.map((x) => `${x.arquivo}${x.nota ? ` ${x.nota}` : ""}`).join(", ")}). ` +
          "Só gere de novo se for de propósito (outra tentativa); senão mude a cena, o trecho ou as referências."
        : "",
      r.dica ? `Autoestudo: ${r.dica}` : "",
      `Prompt final que vai para o modelo:\n${r.prompt}`,
      `Para gerar: o Breno abre ${URL_INTERFACE}, em "Rascunhos do assistente" clica em Abrir e depois em Gerar.`,
    ].filter(Boolean).join("\n\n"));
  }));

  servidor.registerTool("descartar_rascunho", {
    title: "Descartar um rascunho",
    description: "Remove um rascunho que ainda não foi gerado (por exemplo, quando você prepara uma versão melhor). Não apaga vídeos.",
    inputSchema: { id: z.string().min(2).describe("Id do rascunho, ex.: r1791900000000") },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  }, seguro(async ({ id }) => {
    await estudio.apagar(`/api/rascunhos/${encodeURIComponent(id)}`);
    return texto(`Rascunho ${id} descartado.`);
  }));

  servidor.registerTool("historico", {
    title: "Histórico de vídeos gerados",
    description:
      "Os últimos vídeos gerados com modelo, custo cobrado, status, erro, pilar e o prompt usado. " +
      "Use para aprender o que deu certo, repetir um setup que funcionou ou entender uma falha.",
    inputSchema: { limite: z.number().int().min(1).max(30).default(8) },
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async ({ limite }) => {
    const itens = (await estudio.get<ItemHistorico[]>("/api/historico")).slice(0, limite);
    if (!itens.length) return texto("Nenhum vídeo gerado ainda.");
    return texto(itens.map((i) => [
      `■ ${i.data.replace("T", " ")} · ${i.arquivo_1080 || i.arquivo || i.id} · ${i.modelo || "?"} · ${i.duracao}s · ${custoItem(i)} · ${i.status}${i.pilar ? ` · ${i.pilar}` : ""}`,
      i.erro ? `  erro: ${i.erro}` : "",
      i.prompt ? `  prompt: ${i.prompt}` : "  (sem prompt salvo: gerado pelo gerar.py)",
    ].filter(Boolean).join("\n")).join("\n\n"));
  }));

  servidor.registerTool("aprendizados", {
    title: "O que o estúdio aprendeu",
    description:
      "O autoestudo do estúdio, calculado das avaliações (👍/👎), dos problemas marcados e dos números do TikTok: " +
      "custo por vídeo APROVADO de cada modelo em cada modo, problemas que mais se repetem e como corrigir, " +
      "configurações vencedoras (para reusar), vídeos de movimento que o Kling rejeita e qual pilar converte mais em seguidores. " +
      "Consulte antes de escolher modelo e referências: a meta é o melhor vídeo pelo menor custo.",
    inputSchema: {},
    annotations: { readOnlyHint: true, openWorldHint: false },
  }, seguro(async () => {
    const a = await estudio.get<Aprendizado>("/api/aprendizado");
    const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
    const din = (v: number | null) => (v === null ? "—" : usd(v));
    const configs = a.configs.map((c) =>
      `- ${a.modos[c.modo] ?? c.modo} · ${c.modelo}: ${c.gerados} gerados, ${c.falhas} falhas, ${c.bons}👍 ${c.ruins}👎, ` +
      `aprovação ${pct(c.aprovacao)}, custo médio ${din(c.custo_medio)}, por aprovado ${din(c.custo_por_aprovado)}`);
    const vencedores = a.vencedores.map((v) =>
      `- ${v.arquivo} · ${v.modelo} · ${usd(v.custo_usd)} · ${v.pilar || "sem pilar"}` +
      (v.views ? ` · ${v.views} views, ${v.conclusao_pct ?? "?"}% conclusão, ${v.seguidores ?? "?"} seguidores` : "") +
      `\n  referências: ${JSON.stringify({ persona: v.pedido.persona, peca: v.pedido.peca, cenario: v.pedido.cenario, movimento: v.pedido.movimento, imagem_base: v.pedido.imagem_base, duracao: v.pedido.duracao })}` +
      `\n  cena: ${String(v.pedido.cena ?? "")}`);
    const pilares = a.pilares.map((p) =>
      `- ${p.pilar}: ${p.videos} vídeos (${Math.round(p.fatia * 100)}%, meta ${Math.round(p.meta * 100)}%)` +
      (p.views_media ? ` · média ${p.views_media} views, ${p.conclusao_media ?? "?"}% conclusão, ${p.seguidores_por_100_views ?? "?"} seguidores/100 views` : ""));
    return texto([
      "Recomendações:", ...(a.recomendacoes.length ? a.recomendacoes.map((r) => `- ${r}`) : ["- sem dados ainda"]),
      "", "Modelos por modo:", ...(configs.length ? configs : ["- nada gerado pelo Estúdio ainda"]),
      "", "Problemas mais comuns:", ...(a.problemas.length ? a.problemas.map((p) => `- ${p.nome} (${p.vezes}x): ${p.como_corrigir}`) : ["- nenhum marcado"]),
      "", "Configurações vencedoras (👍, melhores no TikTok primeiro):", ...(vencedores.length ? vencedores : ["- nenhuma ainda"]),
      "", "Pilares:", ...pilares,
      "", "Rejeitados pelo Kling:", ...(a.rejeicoes_kling.length ? a.rejeicoes_kling.map((r) => `- ${r.movimento} (${r.vezes}x)`) : ["- nenhum"]),
    ].join("\n"));
  }));

  servidor.registerTool("avaliar_video", {
    title: "Registrar análise ou resultado de um vídeo",
    description:
      "Grava no autoestudo o que aconteceu com um vídeo gerado. Use depois de ver_video (fonte=saida) para registrar " +
      "os problemas que você viu (analise_ia), ou quando o Breno contar os números do TikTok (views, % de conclusão, " +
      "seguidores ganhos em 48h). Só preencha 'nota' (bom/ruim) quando o Breno disser explicitamente o que achou.",
    inputSchema: {
      arquivo: z.string().min(3).describe("Arquivo do vídeo gerado, ex.: v12_casaco.mp4 (aceita a versão _1080)"),
      problemas_vistos: z.array(z.enum(PROBLEMAS)).optional().describe("Problemas que VOCÊ viu nos quadros"),
      comentario_ia: z.string().max(400).optional().describe("Sua análise curta, em português"),
      nota_do_breno: z.enum(["bom", "ruim"]).optional().describe("Só se o Breno disser"),
      views: z.number().min(0).optional(),
      conclusao_pct: z.number().min(0).max(100).optional().describe("% que assistiu até o fim"),
      seguidores: z.number().min(0).optional().describe("Seguidores ganhos com o vídeo (48h)"),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, seguro(async (a) => {
    const corpo: Record<string, unknown> = { arquivo: a.arquivo };
    if (a.problemas_vistos || a.comentario_ia) corpo.analise_ia = { problemas: a.problemas_vistos ?? [], comentario: a.comentario_ia ?? "" };
    if (a.nota_do_breno) corpo.nota = a.nota_do_breno;
    if (a.views !== undefined || a.conclusao_pct !== undefined || a.seguidores !== undefined) {
      corpo.tiktok = { views: a.views, conclusao_pct: a.conclusao_pct, seguidores: a.seguidores };
    }
    await estudio.post("/api/avaliar", corpo);
    return texto(`Registrado em ${a.arquivo}. Isso entra no autoestudo (ferramenta aprendizados).`);
  }));

  return servidor;
}
