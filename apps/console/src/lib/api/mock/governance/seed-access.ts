import type { AccessGrant, Capability, RoleAssignment } from '@/lib/types/governance';

import * as F from '../fixtures';
import { inDays, minsAgo, moduleLabel, moduleOf, WORKFLOW_ACCESS } from './catalog';

const DAY = 1440;

/** Grants that expire soon or already have, so the expiring view and the denied calls have something to show. */
const EXPIRY: Record<string, number> = {
  'wf_wire|place_wire_hold': 6,
  'wf_lending_inbox|apply_payment_deferral': 3,
  'wf_card_inbox|waive_fee': 11,
  'wf_dispute|Cards & disputes': 9,
  'wf_kyb|screen_watchlists': 13,
};

export function seedGrants(): (AccessGrant & { owner: string })[] {
  const out: (AccessGrant & { owner: string })[] = [];
  let n = 0;
  for (const w of F.WORKFLOWS) {
    const a = WORKFLOW_ACCESS[w.id];
    if (!a) continue;
    const base = { identityId: `wid_${w.id.slice(3)}`, workflowId: w.id, workflowName: w.name, owner: w.owner };
    for (const tool of a.tools) {
      const m = moduleOf(tool);
      const soon = EXPIRY[`${w.id}|${tool}`];
      // Every grant expires: money movement within 180 days, reads and writes within a year.
      const expiresAt = soon != null ? inDays(soon) : m.access === 'money_movement' ? inDays(60 + ((n * 37) % 120)) : inDays(90 + ((n * 41) % 270));
      out.push({
        ...base,
        id: `gr_${++n}`,
        resourceKind: 'module',
        resource: moduleLabel(tool),
        scope: m.access,
        grantedBy: ['James Richardson', 'Priya Shah', 'Maya Okafor'][n % 3],
        grantedAt: minsAgo(DAY * (20 + ((n * 13) % 140))),
        expiresAt,
        status: 'active',
        reason: m.access === 'money_movement' ? 'Approved by the model risk committee for this workflow' : undefined,
      });
    }
    for (const kb of a.kbs) {
      const soon = EXPIRY[`${w.id}|${kb}`];
      out.push({ ...base, id: `gr_${++n}`, resourceKind: 'knowledge_base', resource: kb, scope: 'read', grantedBy: 'James Richardson', grantedAt: minsAgo(DAY * (30 + ((n * 11) % 100))), expiresAt: soon != null ? inDays(soon) : inDays(120 + ((n * 29) % 240)), status: 'active' });
    }
  }
  // A grant left over from the pilot; the branch chat still tries it, and the gateway refuses.
  out.push({ id: `gr_${++n}`, identityId: 'wid_branch_chat', workflowId: 'wf_branch_chat', workflowName: 'Branch chat', owner: 'Retail Banking', resourceKind: 'module', resource: moduleLabel('get_transactions'), scope: 'read', grantedBy: 'Tom Haddad', grantedAt: minsAgo(DAY * 92), expiresAt: inDays(-2), status: 'expired', reason: 'Pilot: show recent transactions in chat' });
  return out;
}

const cap = (...c: Capability[]) => c;

export function seedRoles(teamName: (id: string) => string): RoleAssignment[] {
  const rows: Omit<RoleAssignment, 'id' | 'team' | 'addedAt'>[] = [
    { principal: 'Platform Admins', principalKind: 'group', members: 6, teamId: 'team_platform', capabilities: cap('author', 'approve', 'publish'), addedBy: 'James Richardson' },
    { principal: 'James Richardson', principalKind: 'person', members: 1, teamId: 'team_platform', capabilities: cap('author', 'approve', 'publish'), addedBy: 'James Richardson' },
    { principal: 'Model Risk Committee', principalKind: 'group', members: 5, teamId: 'team_platform', capabilities: cap('approve'), addedBy: 'James Richardson' },
    { principal: 'Fraud Strategy Builders', principalKind: 'group', members: 4, teamId: 'team_fraud', capabilities: cap('author'), addedBy: 'Maya Okafor' },
    { principal: 'Fraud Analysts L2', principalKind: 'group', members: 9, teamId: 'team_fraud', capabilities: cap('approve'), addedBy: 'Maya Okafor' },
    { principal: 'Maya Okafor', principalKind: 'person', members: 1, teamId: 'team_fraud', capabilities: cap('author', 'publish'), addedBy: 'James Richardson' },
    { principal: 'Lending Ops Builders', principalKind: 'group', members: 5, teamId: 'team_lending', capabilities: cap('author'), addedBy: 'Priya Shah' },
    { principal: 'Underwriters', principalKind: 'group', members: 12, teamId: 'team_lending', capabilities: cap('approve'), addedBy: 'Priya Shah' },
    { principal: 'Priya Shah', principalKind: 'person', members: 1, teamId: 'team_lending', capabilities: cap('approve', 'publish'), addedBy: 'James Richardson' },
    { principal: 'Card Services Builders', principalKind: 'group', members: 3, teamId: 'team_cards', capabilities: cap('author'), addedBy: 'Daniel Brooks' },
    { principal: 'Card Disputes', principalKind: 'group', members: 14, teamId: 'team_cards', capabilities: cap('approve'), addedBy: 'Daniel Brooks' },
    { principal: 'Daniel Brooks', principalKind: 'person', members: 1, teamId: 'team_cards', capabilities: cap('author', 'publish'), addedBy: 'James Richardson' },
    { principal: 'KYC Operations', principalKind: 'group', members: 8, teamId: 'team_onboarding', capabilities: cap('approve'), addedBy: 'Anika Singh' },
    { principal: 'Enhanced Due Diligence', principalKind: 'group', members: 4, teamId: 'team_onboarding', capabilities: cap('approve'), addedBy: 'Anika Singh' },
    { principal: 'Anika Singh', principalKind: 'person', members: 1, teamId: 'team_onboarding', capabilities: cap('author', 'publish'), addedBy: 'James Richardson' },
    { principal: 'Retail Digital', principalKind: 'group', members: 6, teamId: 'team_retail', capabilities: cap('author'), addedBy: 'Tom Haddad' },
    { principal: 'Retail Product Leads', principalKind: 'group', members: 3, teamId: 'team_retail', capabilities: cap('approve', 'publish'), addedBy: 'James Richardson' },
    { principal: 'Wealth Advisors', principalKind: 'group', members: 7, teamId: 'team_wealth', capabilities: cap('approve'), addedBy: 'Lena Fischer' },
    { principal: 'Lena Fischer', principalKind: 'person', members: 1, teamId: 'team_wealth', capabilities: cap('author', 'publish'), addedBy: 'James Richardson' },
  ];
  return rows.map((x, i) => ({ ...x, id: `role_${i + 1}`, team: teamName(x.teamId), addedAt: minsAgo(DAY * (15 + i * 9)) }));
}

export const GROUPS = ['Platform Admins', 'Model Risk Committee', 'Fraud Strategy Builders', 'Fraud Analysts L1', 'Fraud Analysts L2', 'Lending Ops Builders', 'Underwriters', 'Card Services Builders', 'Card Disputes', 'Card Services Leads', 'KYC Operations', 'Enhanced Due Diligence', 'Retail Digital', 'Retail Product Leads', 'Wealth Advisors'];
