import { Bell, ChartColumn, Globe, HardDrive, KeyRound, KeySquare, LogIn, ShieldCheck, SlidersHorizontal, Webhook, type LucideIcon } from 'lucide-react';

/**
 * The settings tree the owner approved (card c-178, mock at /preview/settings): one home per scope. Pages move here one
 * at a time; an entry whose page has not moved yet points at its current route. Team pages live under /settings/team,
 * workspace pages under /settings/workspace, and Govern pages stay where Govern keeps them.
 */
export type SettingsGroup = 'Workspace' | 'Team' | 'Govern';

export interface SettingsEntry {
  id: string;
  title: string;
  href: string;
  icon: LucideIcon;
  description: string;
  group: SettingsGroup;
  /** Entries sharing a section nest under one parent row in the sidebar (Govern > Security). */
  section?: string;
}

export const SETTINGS_NAV: SettingsEntry[] = [
  { id: 'workspace-general', title: 'General', href: '/settings/workspace', icon: SlidersHorizontal, description: 'The workspace’s name, address and logo', group: 'Workspace' },
  { id: 'storage', title: 'Storage', href: '/settings/workspace/storage', icon: HardDrive, description: 'Where files are kept, upload limits, scanning and retention', group: 'Workspace' },
  { id: 'usage', title: 'Usage and cost', href: '/settings/workspace/usage', icon: ChartColumn, description: 'Tokens, model cost and tool calls for chargeback', group: 'Workspace' },
  { id: 'team-general', title: 'General', href: '/settings/team', icon: SlidersHorizontal, description: 'The team’s name, owner and the agent new chats start on', group: 'Team' },
  { id: 'notifications', title: 'Notifications', href: '/settings/team/notifications', icon: Bell, description: 'Where approvals, SLA warnings and alerts go', group: 'Team' },
  { id: 'webhooks', title: 'Webhooks', href: '/settings/team/webhooks', icon: Webhook, description: 'Send events to the bank’s other systems', group: 'Team' },
  { id: 'api-keys', title: 'API keys', href: '/settings/team/api-keys', icon: KeyRound, description: 'Keys for systems that start runs or read logs', group: 'Team' },
  { id: 'policies', title: 'Workspace policies', href: '/settings/policies', icon: ShieldCheck, description: 'Who may decide what, and how long things may wait', group: 'Govern', section: 'Policies' },
  { id: 'publish-reviews', title: 'Publish reviews', href: '/settings/policies/publish-reviews', icon: ShieldCheck, description: 'Which publishes need a second person’s review', group: 'Govern', section: 'Policies' },
  { id: 'gates', title: 'Gate policies', href: '/settings/policies/gates', icon: ShieldCheck, description: 'Who reviews at each gate and how long they have', group: 'Govern', section: 'Policies' },
  { id: 'sign-in', title: 'Sign-in', href: '/settings/security/sign-in', icon: LogIn, description: 'Sign-in methods, single sign-on, two-step verification and sessions', group: 'Govern', section: 'Security' },
  { id: 'egress', title: 'Egress', href: '/settings/security/egress', icon: Globe, description: 'Hosts and private ranges tool calls may reach', group: 'Govern', section: 'Security' },
  { id: 'secrets', title: 'Secrets', href: '/settings/security/secrets', icon: KeySquare, description: 'Credentials tool calls send, never shown again', group: 'Govern', section: 'Security' },
];

export const SETTINGS_GROUPS: SettingsGroup[] = ['Workspace', 'Team', 'Govern'];

/** The person's own settings, kept at the bottom of the settings sidebar. */
export const PERSONAL_SETTINGS = [
  { id: 'my-account', label: 'My account', href: '/settings/account' },
  { id: 'my-security', label: 'My security', href: '/settings/account/security' },
  { id: 'my-memory', label: 'My memory', href: '/settings/account/memory' },
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

/** What the settings sidebar draws: the live tree and the /preview/settings mock both build one of these. */
export interface SidebarItem {
  id: string;
  label: string;
  href: string;
  children?: { id: string; label: string; href: string }[];
}

export interface SidebarTree {
  home: string;
  groups: { label: string; items: SidebarItem[] }[];
  personal: { id: string; label: string; href: string }[];
  find: (query: string) => FoundSetting[];
  /** The mock draws pages for a chosen role; the live tree never does. */
  roleSwitch?: boolean;
}

function itemsOf(group: SettingsGroup): SidebarItem[] {
  const out: SidebarItem[] = [];
  for (const e of SETTINGS_NAV.filter((x) => x.group === group)) {
    if (!e.section) {
      out.push({ id: e.id, label: e.title, href: e.href });
      continue;
    }
    const parent = out.find((o) => o.id === `section-${e.section}`);
    const child = { id: e.id, label: e.title, href: e.href };
    if (parent) parent.children!.push(child);
    else out.push({ id: `section-${e.section}`, label: e.section, href: e.href, children: [child] });
  }
  return out;
}

export const LIVE_TREE: SidebarTree = {
  home: '/settings',
  groups: SETTINGS_GROUPS.map((g) => ({ label: g, items: itemsOf(g) })),
  personal: PERSONAL_SETTINGS,
  find: findInSettings,
};
