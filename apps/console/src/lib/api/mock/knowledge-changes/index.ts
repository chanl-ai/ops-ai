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
  const inView = (c: KnowledgeChange, v: ChangeView) =>
    v === 'resolved' ? !isOpen(c) : v === 'conflicts' ? isOpen(c) && unresolved(c) : v === 'mine' ? isOpen(c) && c.canDecide : isOpen(c);

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
            conflicts: src.filter((c) => inView(c, 'conflicts')).length,
            resolved: src.filter((c) => inView(c, 'resolved')).length,
          },
        };
      }),
    get: (id) => respond(() => row(find(id))),
    decide: (id, input) =>
      respond(() => {
        const s = find(id);
        const c = row(s);
        if (!isOpen(c)) throw new ApiError(`${id} was already ${c.status}.`, 409);
        if (!c.canDecide) throw new ApiError(`Only ${s.owner} can decide changes to ${s.documentTitle}.`, 403);
        if (!input.reason.trim()) throw new ApiError('Give a reason; it is kept in the document’s history.', 400);
        if (input.decision === 'approved' && unresolved(c)) throw new ApiError(`Resolve the conflict with ${c.conflict!.documentTitle} before approving.`, 409);
        Object.assign(s, {
          status: input.decision,
          decidedAt: new Date().toISOString(),
          decidedBy: deps.me,
          decisionReason: input.reason.trim(),
          retest: input.decision === 'approved' ? { tests: s.citedBy.reduce((n, x) => n + x.tests, 0), workflows: c.citedBy.map((x) => x.workflowName) } : undefined,
          trust: input.decision === 'approved' ? 'verified' : s.trust,
        });
        return row(s);
      }),
    resolveConflict: (id, resolution) =>
      respond(() => {
        const s = find(id);
        if (!s.conflict) throw new ApiError(`${id} has no conflict to resolve.`, 409);
        if (!canDecide(s.owner)) throw new ApiError(`Only ${s.owner} can resolve this conflict.`, 403);
        s.conflict.resolution = resolution;
        return row(s);
      }),
  };
}
