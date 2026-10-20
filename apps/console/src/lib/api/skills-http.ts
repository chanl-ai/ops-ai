import type { ListParams } from '@/lib/types/query';
import type { SkillGenerateEvent } from '@/lib/types/skills';

import { ApiError } from './contract';
import type { SkillsApi } from './skills-contract';
import { optionsQs } from './options';
import { fetchWithIdentity } from './request-identity';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** Reads a server-sent event stream where each `data:` line is one JSON SkillGenerateEvent. */
async function* events(res: Response): AsyncIterable<SkillGenerateEvent> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) if (line.startsWith('data:')) yield JSON.parse(line.slice(5).trim()) as SkillGenerateEvent;
  }
}

/** REST routes for skills; generation streams over SSE from POST /skills/generate. */
export function createSkillsHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string, baseUrl: string): SkillsApi {
  return {
    list: (p) => get(`/skills?${qs(p)}`),
    get: (id) => get(`/skills/${id}`),
    create: (i) => send('POST', '/skills', i),
    saveDraft: (id, patch) => send('PUT', `/skills/${id}/draft`, patch),
    restore: (id, version) => send('POST', `/skills/${id}/versions/${version}/restore`),
    duplicate: (id) => send('POST', `/skills/${id}/duplicate`),
    requestReview: (id, note) => send('POST', `/skills/${id}/publish-requests`, { note }),
    deprecate: (id, reason) => send('POST', `/skills/${id}/deprecate`, { reason }),
    remove: (id) => send('DELETE', `/skills/${id}`),
    bulkDeprecate: (ids, reason) => send('POST', '/skills/bulk-deprecate', { ids, reason }),
    bulkRemove: (ids) => send('POST', '/skills/bulk-delete', { ids }),
    exportSkills: (ids, version) => send('POST', '/skills/export', { ids, version }),
    tests: {
      add: (id, i) => send('POST', `/skills/${id}/tests`, i),
      update: (id, cid, i) => send('PUT', `/skills/${id}/tests/${cid}`, i),
      remove: (id, cid) => send('DELETE', `/skills/${id}/tests/${cid}`),
      run: (id) => send('POST', `/skills/${id}/test-runs`),
    },
    resources: {
      add: (id, i) => send('POST', `/skills/${id}/resources`, i),
      remove: (id, rid) => send('DELETE', `/skills/${id}/resources/${rid}`),
    },
    async *generate(input, signal) {
      const res = await fetchWithIdentity(`${baseUrl}/skills/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(input),
        signal,
      });
      if (!res.ok) throw new ApiError(res.statusText, res.status);
      yield* events(res);
    },
    rewriteSection: (i) => send('POST', '/skills/rewrite-section', i),
    suggestTests: (input, skill) => send('POST', '/skills/suggest-tests', { input, skill }),
    dryRun: (draft, tests) => send('POST', '/skills/dry-run', { draft, tests }),
    impact: (draft, agentIds) => send('POST', '/skills/impact', { draft, agentIds }),
    generateOptions: () => get('/skills/generate-options'),
    options: () => get('/skills/options'),
    candidates: (scope) => send('POST', '/skills/candidates', scope),
    previewImport: (fileId) => send('POST', '/skills/import/preview', { fileId }),
    importSkill: (fileId, ownerTeam) => send('POST', '/skills/import', { fileId, ownerTeam }),
    agents: {
      get: (aid) => get(`/agents/${aid}/skills`),
      attach: (aid, skillId, version) => send('PUT', `/agents/${aid}/skills/${skillId}`, version === undefined ? {} : { version }),
      options: (aid, p, loading) => get(`/agents/${aid}/skills/options?${[optionsQs(p), loading ? `loading=${loading}` : ''].filter(Boolean).join('&')}`),
      detach: (aid, skillId) => send('DELETE', `/agents/${aid}/skills/${skillId}`),
    },
  };
}
