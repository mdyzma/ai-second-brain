/** Minimal text/event-stream parser (the chat turn is a POST, so EventSource can't be used). */
export type SseMessage = { event: string; data: string };

export function createSseParser(onMessage: (message: SseMessage) => void) {
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data: string[] = [];

  function line(text: string): void {
    if (text === "") {
      if (data.length > 0) onMessage({ event, data: data.join("\n") });
      event = "message";
      data = [];
      return;
    }
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  function drain(): void {
    let index = buffer.indexOf("\n");
    while (index !== -1) {
      line(buffer.slice(0, index).replace(/\r$/, ""));
      buffer = buffer.slice(index + 1);
      index = buffer.indexOf("\n");
    }
  }

  return {
    push(chunk: Uint8Array | string): void {
      buffer += typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
      drain();
    },
    /** Flush the decoder. An event without its terminating blank line is dropped (per spec). */
    end(): void {
      buffer += decoder.decode();
      drain();
      buffer = "";
    },
  };
}

export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const queue: SseMessage[] = [];
  const parser = createSseParser((message) => queue.push(message));
  const reader = body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        parser.end();
        yield* queue.splice(0);
        return;
      }
      parser.push(value);
      yield* queue.splice(0);
    }
  } finally {
    reader.releaseLock();
  }
}
