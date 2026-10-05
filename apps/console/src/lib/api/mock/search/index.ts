import type { SearchGroup, SearchHit } from '@/lib/types/search';

import type { CasesApi } from '../../cases-contract';
import type { ChatApi } from '../../chat-contract';
import type { KnowledgeApi } from '../../knowledge-contract';
import type { SearchApi } from '../../search-contract';
import { currentTeamId } from '../../team-context';
import { mode, respond } from '../runtime';

/** Hits returned per group; the palette shows the count of the rest. */
const PER_GROUP = 5;
const MAX_RECENT = 6;

interface Deps {
  /** Team-scoped rows, so the palette never finds another team's records. */
  workflows: () => { id: string; name: string; owner: string; status: string }[];
  agents: () => { id: string; name: string; role: string; status: string }[];
  cases: CasesApi;
  knowledge: KnowledgeApi;
  chat: ChatApi;
}

const matches = (q: string, ...fields: string[]) => fields.some((f) => f.toLowerCase().includes(q));

/** Palette search across records. Lists that already search server-side (cases, knowledge, chats) are reused. */
export function createSearchMock(deps: Deps): SearchApi {
  const recents: Record<string, SearchHit[]> = {};

  return {
    async query(raw) {
      const q = raw.trim().toLowerCase();
      const page = { page: 1, pageSize: PER_GROUP, search: q };
      // The three list calls carry their own latency and ?mock= behaviour, so this resolves with them.
      const [cases, kbs, chats] = await Promise.all([
        deps.cases.list({ ...page, view: 'team' }),
        deps.knowledge.kbs.list(page),
        deps.chat.threads.list(page),
      ]);
      const empty = mode() === 'empty';
      const wf = empty ? [] : deps.workflows().filter((w) => matches(q, w.name, w.id, w.owner));
      const ag = empty ? [] : deps.agents().filter((a) => matches(q, a.name, a.role));
      const groups: { group: SearchGroup; hits: SearchHit[]; total: number }[] = [
        { group: 'workflows', total: wf.length, hits: wf.slice(0, PER_GROUP).map((w) => ({ id: w.id, group: 'workflows', title: w.name, detail: `${w.owner} · ${w.status}`, href: `/workflows/${w.id}` })) },
        { group: 'agents', total: ag.length, hits: ag.slice(0, PER_GROUP).map((a) => ({ id: a.id, group: 'agents', title: a.name, detail: a.role, href: `/agents/${a.id}` })) },
        {
          group: 'cases',
          total: cases.pagination.total,
          hits: cases.data.map((c) => ({ id: c.id, group: 'cases', title: c.subject, detail: `${c.id} · ${c.requester} · ${c.intentName}`, href: `/cases/${c.id}` })),
        },
        {
          group: 'knowledge',
          total: kbs.pagination.total,
          hits: kbs.data.map((k) => ({ id: k.id, group: 'knowledge', title: k.name, detail: k.description, href: `/knowledge/${k.id}` })),
        },
        {
          group: 'chats',
          total: chats.pagination.total,
          hits: chats.data.map((t) => ({ id: t.id, group: 'chats', title: t.title, detail: t.agentName, href: `/chat/${t.id}` })),
        },
      ];
      return { query: raw, groups: groups.filter((g) => g.hits.length) };
    },
    recent: () => respond((m) => (m === 'empty' ? [] : (recents[currentTeamId()] ?? []))),
    visit: (hit) =>
      respond(() => {
        const team = currentTeamId();
        recents[team] = [hit, ...(recents[team] ?? []).filter((h) => !(h.id === hit.id && h.group === hit.group))].slice(0, MAX_RECENT);
      }),
  };
}
