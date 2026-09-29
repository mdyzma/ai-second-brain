// @vitest-environment node
import { describe, expect, it } from "vitest";
import { createSseParser, readSse, type SseMessage } from "./sse";

function collect(chunks: (string | Uint8Array)[]): SseMessage[] {
  const messages: SseMessage[] = [];
  const parser = createSseParser((message) => messages.push(message));
  for (const chunk of chunks) parser.push(chunk);
  parser.end();
  return messages;
}

describe("createSseParser", () => {
  it("parses several events in one chunk and skips comments", () => {
    expect(collect([': ping\n\nevent: token\ndata: {"a":1}\n\nevent: done\ndata: {}\n\n'])).toEqual(
      [
        { event: "token", data: '{"a":1}' },
        { event: "done", data: "{}" },
      ],
    );
  });

  it("joins an event split across chunks", () => {
    expect(collect(["event: tok", 'en\ndata: {"te', 'xt":"hi"}\n', "\n"])).toEqual([
      { event: "token", data: '{"text":"hi"}' },
    ]);
  });

  it("decodes a multi-byte character split across chunks", () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"zażółć"}\n\n');
    const cut = bytes.indexOf(0xc5) + 1; // split inside the two-byte "ż"
    expect(collect([bytes.slice(0, cut), bytes.slice(cut)])).toEqual([
      { event: "token", data: '{"text":"zażółć"}' },
    ]);
  });

  it("handles CRLF line endings and drops an unterminated event at the end", () => {
    expect(collect(["event: done\r\ndata: {}\r\n\r\nevent: token\ndata: {}"])).toEqual([
      { event: "done", data: "{}" },
    ]);
  });
});

describe("readSse", () => {
  it("yields messages from a byte stream", async () => {
    const body = new Response("event: done\ndata: {}\n\n").body;
    if (body === null) throw new Error("no body");
    const messages: SseMessage[] = [];
    for await (const message of readSse(body)) messages.push(message);
    expect(messages).toEqual([{ event: "done", data: "{}" }]);
  });
});
