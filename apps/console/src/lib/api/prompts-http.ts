import type { PromptStreamEvent } from '@/lib/types/prompts';
import type { ListParams } from '@/lib/types/query';

import { ApiError } from './contract';
import type { PromptsApi } from './prompts-contract';
import { fetchWithIdentity } from './request-identity';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** Reads a server-sent event stream where each `data:` line is one JSON PromptStreamEvent. */
async function* readSse(res: Response): AsyncIterable<PromptStreamEvent> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    const frames = buf.split('\n\n');
    buf = frames.pop() ?? '';
    for (const f of frames) {
      const data = f
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trim())
        .join('');
      if (data) yield JSON.parse(data) as PromptStreamEvent;
    }
  }
}

/** REST routes for prompt tooling; generation streams over SSE from POST /prompts/generate. */
export function createPromptsHttp(get: Get, send: Send, qs: (p: ListParams) => string, baseUrl: string): PromptsApi {
  return {
    variables: () => get('/prompts/variables'),
    async *generate(spec, context, signal) {
      const res = await fetchWithIdentity(`${baseUrl}/prompts/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ spec, context }),
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(body?.error?.message ?? res.statusText, res.status);
      }
      yield* readSse(res);
    },
    rewriteSection: (i) => send('POST', '/prompts/rewrite-section', i),
    analyze: (sections, context) => send('POST', '/prompts/analyze', { sections, context }),
  };
}
