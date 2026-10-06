import type { AgentTestTurn } from '@/lib/types/domain';
import type { Sensitivity } from '@/lib/types/knowledge';
import type { PermissionScope, RunAsPrincipal } from '@/lib/types/run-as';

import { ApiError } from '../../contract';
import type { RunAsApi } from '../../run-as-contract';
import { playgroundAnswers } from '../knowledge/seed-kbs';
import { sources } from '../knowledge/seed-sources';
import { respond } from '../runtime';
import { inTeam } from '../teams';
import { PRINCIPALS } from './principals';

const RANK: Record<Sensitivity, number> = { internal: 0, confidential: 1, restricted: 2 };
/** Item ids are `<sourceId>_it_<n>`, so a cited document's source (collection, sensitivity) is its prefix. */
const sourceOf = (documentId: string) => sources.find((s) => s.id === documentId.replace(/_it_\d+$/, ''));

function principal(runAsId?: string): RunAsPrincipal | undefined {
  if (!runAsId) return undefined;
  const p = PRINCIPALS.find((x) => x.id === runAsId);
  if (!p) throw new ApiError('That person or role no longer exists. Choose another to run as.', 404);
  return p;
}

function canSee(p: RunAsPrincipal, documentId: string) {
  const s = sourceOf(documentId);
  if (!s) return true;
  return (p.collections === null || p.collections.includes(s.collection)) && RANK[s.sensitivity] <= RANK[p.clearance];
}

function scope(p: RunAsPrincipal, hidden: string[], blockedTools: string[] = []): PermissionScope {
  return {
    runAsId: p.id,
    runAsName: p.name,
    hiddenDocuments: hidden.length,
    hiddenCollections: [...new Set(hidden.map((d) => sourceOf(d)?.collection).filter((c): c is string => !!c))],
    blockedTools,
  };
}

const docs = (n: number) => `${n} ${n === 1 ? 'document' : 'documents'}`;

const KNOWLEDGE_TOOL = 'search_knowledge';

/** Applies a principal's knowledge access and tool entitlements to one sandbox agent turn. */
export function scopeTurn(turn: AgentTestTurn, message: string, runAsId?: string): AgentTestTurn {
  const p = principal(runAsId);
  if (!p) return turn;
  const q = message.toLowerCase();
  const match = playgroundAnswers
    .map((a) => ({ a, score: a.matchers.filter((m) => q.includes(m.toLowerCase())).length }))
    .sort((x, y) => y.score - x.score)[0];
  const usesKnowledge = turn.toolCalls.some((t) => t.name === KNOWLEDGE_TOOL);
  const cited = !usesKnowledge
    ? []
    : match?.score
      ? match.a.citations.map((c) => ({ source: c.title, section: c.section, documentId: c.documentId, snippet: c.snippet }))
      : turn.citations.map((c) => ({ ...c, documentId: 'src_eng_confluence_it_0', snippet: '' }));
  const visible = cited.filter((c) => canSee(p, c.documentId));
  const hidden = [...new Set(cited.filter((c) => !canSee(p, c.documentId)).map((c) => c.documentId))];
  const blocked = turn.toolCalls.filter((t) => p.tools !== null && !p.tools.includes(t.name)).map((t) => t.name);
  const permissions = scope(p, hidden, blocked);

  const toolCalls = turn.toolCalls.map((t) =>
    blocked.includes(t.name)
      ? { ...t, output: `Blocked · ${p.name} is not entitled to ${t.name}` }
      : t.name === KNOWLEDGE_TOOL
        ? { ...t, output: `${visible.length} ${visible.length === 1 ? 'passage' : 'passages'}${hidden.length ? ` · ${docs(hidden.length)} hidden by permissions` : ''}` }
        : t,
  );
  const parts: string[] = [];
  if (usesKnowledge && cited.length && !visible.length)
    parts.push(`I can’t see the documents that cover this. ${docs(hidden.length)} in ${permissions.hiddenCollections.join(', ')} ${hidden.length === 1 ? 'is' : 'are'} outside what ${p.name} can access, so I won’t answer from them and would hand this to someone who can.`);
  else if (match?.score && visible.length) parts.push(hidden.length ? visible.map((c) => c.snippet).join(' ') : match.a.answer.replace(/\s*\[\d+\]/g, ''));
  else parts.push(turn.reply);
  if (blocked.length) parts.push(`I can’t run ${blocked.join(' or ')} for ${p.name}; their role doesn’t allow it.`);
  return {
    ...turn,
    reply: parts.join(' '),
    toolCalls,
    citations: visible.map(({ source, section }) => ({ source, section })),
    // A blocked action never reaches the review gate.
    wouldPause: blocked.length && turn.wouldPause ? undefined : turn.wouldPause,
    permissions,
  };
}

/** Principals in the current team; Platform sees everyone. */
export const runAsApi: RunAsApi = {
  principals: () => respond(() => PRINCIPALS.filter((p) => inTeam(p.team))),
};
