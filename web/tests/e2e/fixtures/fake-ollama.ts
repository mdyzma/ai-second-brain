/** Scripted Ollama for e2e: fast answers, a slow answer for questions containing "slow",
 * and scripted knowledge-graph extractions for non-streaming structured chat calls. */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { setTimeout as delay } from "node:timers/promises";

const port = Number(process.env.FAKE_OLLAMA_PORT ?? "11501");
let down = false;

const EMPTY_EXTRACTION = { summary: "", entities: [], relations: [] };

/** Extraction prompts carry the note path inside <note>; the reply is chosen from it. */
function scriptedExtraction(prompt: string): unknown {
  if (prompt.includes("Note path: Projects/NAS.md"))
    return {
      summary: "NAS disks and nightly backups.",
      entities: [
        { name: "NAS", type: "device", aliases: [], confidence: 0.9 },
        { name: "Proxmox", type: "tool", aliases: [], confidence: 0.8 },
      ],
      relations: [
        { subject: "NOTE", relation: "about", object: "NAS", chunk: "c1", confidence: 0.9 },
        { subject: "Proxmox", relation: "runs_on", object: "NAS", chunk: null, confidence: 0.7 },
      ],
    };
  if (prompt.includes("Note path: Projects/Proxmox.md"))
    return {
      summary: "Single-node Proxmox cluster.",
      entities: [{ name: "Proxmox", type: "tool", aliases: [], confidence: 0.9 }],
      relations: [
        { subject: "NOTE", relation: "about", object: "Proxmox", chunk: "c1", confidence: 0.9 },
      ],
    };
  return EMPTY_EXTRACTION;
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

function json(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" }).end(JSON.stringify(body));
}

const server = createServer(async (req, res) => {
  const path = new URL(req.url ?? "/", `http://127.0.0.1:${port}`).pathname;
  if (path === "/__control" && req.method === "POST") {
    const body = JSON.parse((await readBody(req)) || "{}") as { down?: boolean };
    down = body.down === true;
    res.writeHead(204).end();
    return;
  }
  if (down) {
    res.writeHead(503).end();
    return;
  }
  if (path === "/api/version") {
    json(res, 200, { version: "0.0.0-e2e" });
    return;
  }
  if (path === "/api/chat" && req.method === "POST") {
    const body = JSON.parse(await readBody(req)) as {
      model: string;
      messages: { content: string }[];
      stream?: boolean;
      format?: unknown;
    };
    if (body.stream === false && body.format) {
      const prompt = body.messages.map((m) => m.content).join(" ");
      json(res, 200, {
        model: body.model,
        message: { role: "assistant", content: JSON.stringify(scriptedExtraction(prompt)) },
        done: true,
      });
      return;
    }
    const question = body.messages.at(-1)?.content ?? "";
    const slow = question.includes("slow");
    const words = slow
      ? Array.from({ length: 80 }, (_, i) => `word${i} `)
      : ["This ", "is ", "the ", "fake ", "e2e ", "answer."];
    let closed = false;
    res.on("close", () => {
      closed = true;
    });
    res.writeHead(200, { "Content-Type": "application/x-ndjson" });
    await delay(200);
    for (const word of words) {
      if (closed) return;
      res.write(
        `${JSON.stringify({ model: body.model, message: { role: "assistant", content: word }, done: false })}\n`,
      );
      await delay(slow ? 250 : 30);
    }
    res.end(
      `${JSON.stringify({ model: body.model, message: { role: "assistant", content: "" }, done: true })}\n`,
    );
    return;
  }
  if (path === "/api/embed" && req.method === "POST") {
    const body = JSON.parse(await readBody(req)) as { input: string[] | string };
    const inputs = Array.isArray(body.input) ? body.input : [body.input];
    const embeddings = inputs.map((text) => {
      let seed = 0;
      for (const ch of text) seed = (seed * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
      const v = Array.from({ length: 1024 }, (_, i) => Math.sin(seed + i));
      const norm = Math.hypot(...v) || 1;
      return v.map((x) => x / norm);
    });
    json(res, 200, { embeddings });
    return;
  }
  res.writeHead(404).end();
});

server.listen(port, "127.0.0.1", () => console.log(`fake ollama listening on ${port}`));
