import type { ChangeView, KnowledgeChange } from '@/lib/types/knowledge-changes';

import { ApiError } from '../../contract';
import type { KnowledgeChangesApi } from '../../knowledge-changes-contract';
import { kbs as SEED_KBS } from '../knowledge/seed-kbs';
import { list, notFound, respond } from '../runtime';
import { inTeam, teamOwner } from '../teams';
import { CHANGE_SEEDS, type ChangeSeed } from './seed';

interface Deps {
  me: string;
  workflowName: (id: string) => string;
  workflowOwner: (id: string) => string | undefined;
}

const isOpen = (c: Pick<KnowledgeChange, 'status'>) => c.status === 'pending';
const unresolved = (c: KnowledgeChange) => !!c.conflict && !c.conflict.resolution;

/**
 * Knowledge change review. A change is decided by the document's owner: the owning person, or anyone working
 * in the team that holds the owner group (Platform, which sees everything, is not an owner).
 */
export function createKnowledgeChangesMock(deps: Deps): KnowledgeChangesApi {
  const seeds: ChangeSeed[] = structuredClone(CHANGE_SEEDS);

  const canDecide = (owner: string) => owner === deps.me || (teamOwner() !== undefined && inTeam(owner));
  const row = (s: ChangeSeed): KnowledgeChange => ({
    ...s,
    kbs: SEED_KBS.filter((k) => k.sources.some((l) => l.sourceId === s.sourceId)).map((k) => ({ id: k.id, name: k.name })),
    citedBy: s.citedBy.map((c) => ({ ...c, workflowName: deps.workflowName(c.workflowId) })),
    freshness: new Date(s.reviewBy).getTime() < Date.now() ? 'stale' : 'fresh',
    canDecide: canDecide(s.owner),
  });
  // A team sees changes it owns or that touch passages its workflows cite.
  const visible = () => seeds.filter((s) => s.owner === deps.me || inTeam(s.owner) || inTeam(s.citedBy.map((c) => deps.workflowOwner(c.workflowId)))).map(row);
  const find = (id: string) => seeds.find((s) => s.id === id) ?? notFound('Change');
  const inView = (c: KnowledgeChange, v: ChangeView) => (v === 'all' ? true : v === 'resolved' ? !isOpen(c) : v === 'mine' ? isOpen(c) && c.canDecide : isOpen(c));

  return {
    list: (p) =>
      respond((m) => {
        const scoped = visible().filter((c) => !p.kbId || c.kbs.some((k) => k.id === p.kbId));
        const rows = scoped.filter((c) => inView(c, p.view)).sort((a, b) => (p.view === 'resolved' ? (b.decidedAt ?? '').localeCompare(a.decidedAt ?? '') : a.createdAt.localeCompare(b.createdAt)));
        const src = m === 'empty' ? [] : scoped;
        return {
          ...list(
            rows,
            p,
            {
              text: (c) => `${c.id} ${c.summary} ${c.documentTitle} ${c.proposedBy}`,
              value: (c, k) => (k === 'kbId' ? c.kbs.map((x) => x.id) : String((c as unknown as Record<string, unknown>)[k])),
              facetKeys: ['origin', 'kbId', 'owner'],
            },
            m,
          ),
          viewCounts: {
            mine: src.filter((c) => inView(c, 'mine')).length,
            open: src.filter((c) => inView(c, 'open')).length,
            conflicts: src.filter((c) => isOpen(c) && unresolved(c)).length,
            resolved: src.filter((c) => inView(c, 'resolved')).length,
          },
        };
      }),
    get: (id) => respond(() => row(find(id))),
    decide: (input) =>
      respond(() =>
        input.ids.map((id) => {
          const s = find(id);
          const c = row(s);
          if (!isOpen(c)) throw new ApiError(`That draft is ${c.status}; there is nothing to decide.`, 409);
          if (!c.canDecide) throw new ApiError(`Only ${s.owner} can decide changes to ${s.documentTitle}.`, 403);
          Object.assign(s, { status: input.decision === 'approve' ? 'approved' : 'rejected', decidedAt: new Date().toISOString(), decidedBy: deps.me });
          return row(s);
        }),
      ),
    edit: (id, pair) =>
      respond(() => {
        const s = find(id);
        if (s.faq) s.faq = { ...s.faq, ...pair };
        return row(s);
      }),
  };
}
