import type { ChatStreamEvent } from '@/lib/types/chat';

/** Reads a server-sent event stream where each `data:` line is one JSON ChatStreamEvent. */
export async function* readSse(res: Response): AsyncIterable<ChatStreamEvent> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  const parse = (f: string) => {
    // SSE allows CRLF line endings and comment lines (": keep-alive"); only `data:` lines carry the event.
    const data = f
      .split(/\r?\n/)
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trim())
      .join('');
    return data ? (JSON.parse(data) as ChatStreamEvent) : null;
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    const frames = buf.split(/\r?\n\r?\n/);
    buf = frames.pop() ?? '';
    for (const f of frames) {
      const ev = parse(f);
      if (ev) yield ev;
    }
  }
  // A server may close right after the last frame without the blank line that ends it.
  const last = parse(buf);
  if (last) yield last;
}
