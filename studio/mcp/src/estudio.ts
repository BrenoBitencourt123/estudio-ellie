// Cliente da API do Estúdio Ellie (servidor Python em studio/server.py)
export const URL_ESTUDIO = process.env.ESTUDIO_URL ?? "http://127.0.0.1:8000";
export const URL_INTERFACE = process.env.ESTUDIO_INTERFACE ?? "http://127.0.0.1:5173";

async function chamar<T>(caminho: string, opcoes?: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(URL_ESTUDIO + caminho, opcoes);
  } catch {
    throw new Error(`O Estúdio não respondeu em ${URL_ESTUDIO}. Ele está aberto? (estudio.bat na pasta gemma-videos)`);
  }
  if (!resposta.ok) {
    let mensagem = `erro ${resposta.status}`;
    try {
      const corpo = (await resposta.json()) as { detail?: unknown };
      if (typeof corpo.detail === "string") mensagem = corpo.detail;
      else if (Array.isArray(corpo.detail)) {
        mensagem = corpo.detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
      }
    } catch {
      // resposta sem JSON: fica a mensagem genérica
    }
    throw new Error(mensagem);
  }
  return (await resposta.json()) as T;
}

const json = (metodo: string, corpo: unknown): RequestInit => ({
  method: metodo,
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify(corpo),
});

export const estudio = {
  get: <T>(caminho: string) => chamar<T>(caminho),
  post: <T>(caminho: string, corpo: unknown) => chamar<T>(caminho, json("POST", corpo)),
  apagar: <T>(caminho: string) => chamar<T>(caminho, { method: "DELETE" }),
  // Baixa uma imagem servida pelo Estúdio (folhas de quadros) e devolve em base64 para o MCP
  imagem: async (caminho: string): Promise<{ data: string; mimeType: string }> => {
    const resposta = await fetch(URL_ESTUDIO + caminho);
    if (!resposta.ok) throw new Error(`não consegui baixar a imagem ${caminho} (${resposta.status})`);
    const bytes = Buffer.from(await resposta.arrayBuffer());
    return { data: bytes.toString("base64"), mimeType: resposta.headers.get("content-type") ?? "image/jpeg" };
  },
};
