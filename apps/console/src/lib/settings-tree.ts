import { IconAdjustmentsHorizontal, IconBell, IconBrain, IconChartBar, IconCpu, IconGavel, IconGitPullRequest, IconKey, IconLock, IconLockPassword, IconLogin, IconPlug, IconServer, IconShieldCheck, IconUserCircle, IconUserShield, IconWebhook, IconWorld, type Icon } from '@tabler/icons-react';

import { personalSignIn } from './api';

/**
 * The settings tree the owner approved (card c-178; the design is the planning repo docs/plans/ops-ai/settings-design.html):
 * one home per scope. Pages move here one
 * at a time; an entry whose page has not moved yet points at its current route. Team pages live under /settings/team,
 * workspace pages under /settings/workspace, and Govern pages stay where Govern keeps them.
 */
export type SettingsGroup = 'Workspace' | 'Team' | 'Govern';

export interface SettingsEntry {
  id: string;
  title: string;
  href: string;
  icon: Icon;
  description: string;
  group: SettingsGroup;
  /** Entries sharing a section nest under one parent row in the sidebar (Govern > Security). */
  section?: string;
}

export const SETTINGS_NAV: SettingsEntry[] = [
  { id: 'workspace-general', title: 'General', href: '/settings/workspace', icon: IconAdjustmentsHorizontal, description: 'The workspace’s name, address and logo', group: 'Workspace' },
  { id: 'storage', title: 'Storage', href: '/settings/workspace/storage', icon: IconServer, description: 'Where files are kept, upload limits, scanning and retention', group: 'Workspace' },
  { id: 'model-providers', title: 'Model providers', href: '/settings/workspace/model-providers', icon: IconCpu, description: 'Keys the account’s AI models sign in with, never shown again', group: 'Workspace' },
  { id: 'usage', title: 'Usage and cost', href: '/settings/workspace/usage', icon: IconChartBar, description: 'Tokens, model cost and tool calls for chargeback', group: 'Workspace' },
  { id: 'team-general', title: 'General', href: '/settings/team', icon: IconAdjustmentsHorizontal, description: 'The team’s name, owner and the agent new chats start on', group: 'Team' },
  { id: 'notifications', title: 'Notifications', href: '/settings/team/notifications', icon: IconBell, description: 'Where approvals, SLA warnings and alerts go', group: 'Team' },
  { id: 'webhooks', title: 'Webhooks', href: '/settings/team/webhooks', icon: IconWebhook, description: 'Send events to the bank’s other systems', group: 'Team' },
  { id: 'api-keys', title: 'API keys', href: '/settings/team/api-keys', icon: IconKey, description: 'Keys for systems that start runs or read logs', group: 'Team' },
  { id: 'policies', title: 'Workspace policies', href: '/settings/policies', icon: IconShieldCheck, description: 'Who may decide what, and how long things may wait', group: 'Govern', section: 'Policies' },
  { id: 'publish-reviews', title: 'Publish reviews', href: '/settings/policies/publish-reviews', icon: IconGitPullRequest, description: 'Which publishes need a second person’s review', group: 'Govern', section: 'Policies' },
  { id: 'gates', title: 'Gate policies', href: '/settings/policies/gates', icon: IconGavel, description: 'Who reviews at each gate and how long they have', group: 'Govern', section: 'Policies' },
  { id: 'sign-in', title: 'Sign-in', href: '/settings/security/sign-in', icon: IconLogin, description: 'Sign-in methods, single sign-on, two-step verification and sessions', group: 'Govern', section: 'Security' },
  { id: 'egress', title: 'Egress', href: '/settings/security/egress', icon: IconWorld, description: 'Hosts and private ranges tool calls may reach', group: 'Govern', section: 'Security' },
  { id: 'secrets', title: 'Secrets', href: '/settings/security/secrets', icon: IconLockPassword, description: 'Credentials tool calls send, never shown again', group: 'Govern', section: 'Security' },
];

export const SETTINGS_GROUPS: SettingsGroup[] = ['Workspace', 'Team', 'Govern'];

/** The icon of a section's parent row (Govern > Policies, Govern > Security). */
const SECTION_ICON: Record<string, Icon> = { Policies: IconShieldCheck, Security: IconLock };

/** The person's own settings, kept at the bottom of the settings sidebar. */
export const PERSONAL_SETTINGS = [
  { id: 'my-account', label: 'My account', href: '/settings/account', icon: IconUserCircle },
  { id: 'my-security', label: 'My security', href: '/settings/account/security', icon: IconUserShield },
  { id: 'my-memory', label: 'My memory', href: '/settings/account/memory', icon: IconBrain },
  ...(personalSignIn ? [{ id: 'my-connections', label: 'Your connections', href: '/settings/account/connections', icon: IconPlug }] : []),
];

/** True on the routes the settings sidebar replaces the app sidebar for. */
export function inSettings(pathname: string): boolean {
  return pathname === '/settings' || pathname.startsWith('/settings/') || pathname === '/account' || pathname.startsWith('/account/');
}

export interface FoundSetting {
  label: string;
  where: string;
  href: string;
}

/** What the Find box searches on the live tree: every page by its name and what it holds. */
export function findInSettings(query: string): FoundSetting[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const all = [
    ...SETTINGS_NAV.map((e) => ({ label: e.title, where: `${e.group} · ${e.description}`, href: e.href, hay: `${e.title} ${e.description} ${e.group}`.toLowerCase() })),
    ...PERSONAL_SETTINGS.map((e) => ({ label: e.label, where: 'My account', href: e.href, hay: `${e.label} my account profile password`.toLowerCase() })),
  ];
  return all.filter((h) => q.split(/\s+/).every((w) => h.hay.includes(w))).slice(0, 12);
}

/** What the settings sidebar draws. */
export interface SidebarItem {
  id: string;
  label: string;
  href: string;
  icon: Icon;
  children?: { id: string; label: string; href: string; icon: Icon }[];
}

export interface SidebarTree {
  home: string;
  groups: { label: string; items: SidebarItem[] }[];
  personal: { id: string; label: string; href: string; icon: Icon }[];
  find: (query: string) => FoundSetting[];
}

function itemsOf(group: SettingsGroup): SidebarItem[] {
  const out: SidebarItem[] = [];
  for (const e of SETTINGS_NAV.filter((x) => x.group === group)) {
    if (!e.section) {
      out.push({ id: e.id, label: e.title, href: e.href, icon: e.icon });
      continue;
    }
    const parent = out.find((o) => o.id === `section-${e.section}`);
    const child = { id: e.id, label: e.title, href: e.href, icon: e.icon };
    if (parent) parent.children!.push(child);
    else out.push({ id: `section-${e.section}`, label: e.section, href: e.href, icon: SECTION_ICON[e.section] ?? e.icon, children: [child] });
  }
  return out;
}

export const LIVE_TREE: SidebarTree = {
  home: '/settings',
  groups: SETTINGS_GROUPS.map((g) => ({ label: g, items: itemsOf(g) })),
  personal: PERSONAL_SETTINGS,
  find: findInSettings,
};
