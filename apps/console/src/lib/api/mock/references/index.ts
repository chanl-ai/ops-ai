import type { RefKind, ReferenceGroup, ReferenceItem, ReferenceSearch } from '@/lib/types/references';

import type { ReferencesApi } from '../../references-contract';
import { ApiError } from '../../contract';
import { respond } from '../runtime';

const GROUP_LABEL: Record<RefKind, string> = { tool: 'Tools', knowledge: 'Knowledge', skill: 'Skills', agent: 'Agents', workflow: 'Workflows' };

/** A pick's wording as the service sends it: what the agent already has, and what picking the rest adds. */
const row = (kind: RefKind, id: string, label: string, held: boolean, opts: { writes?: boolean; hint?: string } = {}): ReferenceItem => ({
  kind,
  id,
  label,
  hint: opts.hint ?? (held ? (opts.writes ? 'On this agent · writes need approval' : 'On this agent') : 'Adds it to this agent'),
  held,
  adds: held ? null : `Adds ${label} to this agent.${opts.writes ? ' Its writes need approval.' : kind === 'tool' ? ' It only reads, so it needs no approval.' : ''}`,
  needsApproval: !!opts.writes,
  disabled: null,
});

/** Sample references from several lines of work, for the all-mock console only; a real stack reads agents-service. */
const ITEMS: ReferenceItem[] = [
  row('tool', 'dispute_status_lookup', 'Dispute status lookup', false),
  row('tool', 'open_dispute', 'Open dispute', true, { writes: true }),
  row('tool', 'search_transactions', 'Search transactions', true),
  row('tool', 'loan_file_lookup', 'Loan file lookup', false),
  row('tool', 'claim_lookup', 'Claim lookup', false),
  row('tool', 'book_visit', 'Book visit', false, { writes: true }),
  row('tool', 'send_email', 'Send email', true, { writes: true }),
  row('knowledge', 'kb_card_disputes', 'Card dispute handbook', true),
  row('knowledge', 'kb_lending_policy', 'Lending policy', false),
  row('knowledge', 'kb_claims_guide', 'Claims guide', false),
  row('skill', 'card_dispute', 'Card dispute', true),
  row('skill', 'verify_identity', 'Verify identity', true, { hint: 'Returns verified or failed' }),
  row('skill', 'dispute_evidence_checklist', 'Dispute evidence checklist', false),
  row('skill', 'check_referral_papers', 'Check referral papers', false, { hint: 'Returns complete or missing' }),
  row('agent', 'fraud_desk', 'Fraud desk', true),
  row('agent', 'disputes_review', 'Disputes review', false),
  row('agent', 'claims_adjuster', 'Claims adjuster', false),
  row('workflow', 'refund_approval', 'Refund approval', false),
];

/** Whether the team offers what a `kind:id` token names; the skills mock's publish check asks. */
export const isOffered = (token: string) => ITEMS.some((i) => `${i.kind}:${i.id}` === token);

const grouped = (items: ReferenceItem[], limit: number): ReferenceGroup[] =>
  (Object.keys(GROUP_LABEL) as RefKind[])
    .map((kind) => {
      const all = items.filter((i) => i.kind === kind);
      return { kind, label: GROUP_LABEL[kind], items: all.slice(0, limit), nextCursor: all.length > limit ? String(limit) : null };
    })
    .filter((g) => g.items.length);

export function createReferencesMock(): ReferencesApi {
  return {
    search: (_context, p) =>
      respond((m): ReferenceSearch => {
        if (m === 'empty') return { groups: [] };
        const q = p.search.trim().toLowerCase();
        return { groups: grouped(ITEMS.filter((i) => (!p.kind || i.kind === p.kind) && i.label.toLowerCase().includes(q)), p.limit ?? 8) };
      }),
    add: (_agentId, ref) =>
      respond(() => {
        const item = ITEMS.find((i) => i.kind === ref.kind && i.id === ref.id);
        if (!item) throw new ApiError('The team does not offer that.', 422, undefined, 'unknown_reference');
        return { added: [{ ...item, held: true, adds: null }], agentVersion: 2 };
      }),
    labels: (_context, ids) => respond((): ReferenceSearch => ({ groups: grouped(ITEMS.filter((i) => ids.includes(`${i.kind}:${i.id}`)), 100) })),
  };
}
