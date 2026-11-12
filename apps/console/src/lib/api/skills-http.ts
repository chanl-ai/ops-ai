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
    list: (p) => get(`/build/skills?${qs(p)}`),
    get: (id) => get(`/build/skills/${id}`),
    create: (i) => send('POST', '/build/skills', i),
    saveDraft: (id, patch) => send('PUT', `/build/skills/${id}/draft`, patch),
    restore: (id, version) => send('POST', `/build/skills/${id}/versions/${version}/restore`),
    duplicate: (id) => send('POST', `/build/skills/${id}/duplicate`),
    requestReview: (id, note) => send('POST', `/build/skills/${id}/publish-requests`, { note }),
    deprecate: (id, reason) => send('POST', `/build/skills/${id}/deprecate`, { reason }),
    remove: (id) => send('DELETE', `/build/skills/${id}`),
    bulkDeprecate: (ids, reason) => send('POST', '/build/skills/bulk-deprecate', { ids, reason }),
    bulkRemove: (ids) => send('POST', '/build/skills/bulk-delete', { ids }),
    exportSkills: (ids, version) => send('POST', '/build/skills/export', { ids, version }),
    tests: {
      add: (id, i) => send('POST', `/build/skills/${id}/tests`, i),
      update: (id, cid, i) => send('PUT', `/build/skills/${id}/tests/${cid}`, i),
      remove: (id, cid) => send('DELETE', `/build/skills/${id}/tests/${cid}`),
      run: (id) => send('POST', `/build/skills/${id}/test-runs`),
    },
    resources: {
      add: (id, i) => send('POST', `/build/skills/${id}/resources`, i),
      remove: (id, rid) => send('DELETE', `/build/skills/${id}/resources/${rid}`),
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
    rewriteSection: (i) => send('POST', '/build/skills/rewrite-section', i),
    suggestTests: (input, skill) => send('POST', '/build/skills/suggest-tests', { input, skill }),
    dryRun: (draft, tests) => send('POST', '/build/skills/dry-run', { draft, tests }),
    impact: (draft, agentIds) => send('POST', '/build/skills/impact', { draft, agentIds }),
    generateOptions: () => get('/build/skills/generate-options'),
    options: () => get('/build/skills/options'),
    candidates: (scope) => send('POST', '/build/skills/candidates', scope),
    previewImport: (fileId) => send('POST', '/build/skills/import/preview', { fileId }),
    importSkill: (fileId, ownerTeam) => send('POST', '/build/skills/import', { fileId, ownerTeam }),
    agents: {
      get: (aid) => get(`/build/agents/${aid}/skills`),
      attach: (aid, skillId, version) => send('PUT', `/build/agents/${aid}/skills/${skillId}`, version === undefined ? {} : { version }),
      options: (aid, p, loading) => get(`/build/agents/${aid}/skills/options?${[optionsQs(p), loading ? `loading=${loading}` : ''].filter(Boolean).join('&')}`),
      detach: (aid, skillId) => send('DELETE', `/build/agents/${aid}/skills/${skillId}`),
    },
  };
}
