/**
 * The proposed settings tree (card c-178): where each of the 43 settings in the review (S01 to S43) lives, the flat
 * section list the settings sidebar draws, what the Find box searches, and which dialogs open which forms. Read by the
 * /preview/settings mock only; the live pages and routes do not use it.
 */
import type { SidebarTree } from './settings-tree';

export const PREVIEW_ROOT = '/preview/settings';
const p = (path: string) => `${PREVIEW_ROOT}${path}`;

export interface SettingsSection {
  id: string;
  label: string;
  href: string;
  group: 'Workspace' | 'Team' | 'Govern' | 'Examples';
  description: string;
}

/** The sidebar's sections, a flat list under four labels. Personal items sit below, at the bottom. */
export const SECTIONS: SettingsSection[] = [
  { id: 'workspace', label: 'General', href: p('/workspace'), group: 'Workspace', description: 'Name, address, logo and the defaults every team inherits' },
  { id: 'storage', label: 'Storage', href: p('/workspace/storage'), group: 'Workspace', description: 'Where files are kept, upload limits, retention and download links' },
  { id: 'team', label: 'General', href: p('/team'), group: 'Team', description: 'The team’s name, owner and what it may override' },
  { id: 'notifications', label: 'Notifications', href: p('/team/notifications'), group: 'Team', description: 'Where approvals, SLA warnings and alerts go' },
  { id: 'webhooks', label: 'Webhooks', href: p('/team/webhooks'), group: 'Team', description: 'Send events to the bank’s other systems' },
  { id: 'api-keys', label: 'API keys', href: p('/team/api-keys'), group: 'Team', description: 'Keys for systems that start runs or read logs' },
  { id: 'access', label: 'Access', href: p('/govern/access'), group: 'Govern', description: 'Who is in the team and what each person may do' },
  { id: 'policies', label: 'Policies', href: p('/govern/policies'), group: 'Govern', description: 'Which publishes need a review and how gates decide' },
  { id: 'security', label: 'Security', href: p('/govern/security'), group: 'Govern', description: 'Sign-in, egress and secrets' },
  { id: 'models', label: 'Models', href: p('/govern/models'), group: 'Govern', description: 'Providers, aliases, keys and budgets' },
  { id: 'agent', label: 'Agent settings tab', href: p('/agent'), group: 'Examples', description: 'How an object’s own Settings tab uses the same cards' },
  { id: 'tool', label: 'Tool page and dialogs', href: p('/tool'), group: 'Examples', description: 'Settings forms opened in place from another page' },
  { id: 'kit', label: 'Field kit', href: p('/kit'), group: 'Examples', description: 'Every field and card the settings pages are built from' },
];

export const PERSONAL: { id: string; label: string; href: string }[] = [
  { id: 'my-account', label: 'My account', href: p('/account') },
  { id: 'my-notifications', label: 'My notifications', href: p('/account#my-notifications') },
];

export type Move = 'moved' | 'new home' | 'stays on the object' | 'split';

export interface SettingMapping {
  s: string;
  name: string;
  home: string;
  href: string;
  move: Move;
  role: string;
}

/** Every setting in the review, mapped to its new home. `stays on the object` links to the live page, which does not move. */
export const S_MAP: SettingMapping[] = [
  { s: 'S01', name: 'Profile name', home: 'My account › Profile', href: p('/account#profile'), move: 'moved', role: 'Self' },
  { s: 'S02', name: 'Password', home: 'My account › Security', href: p('/account#password'), move: 'moved', role: 'Self' },
  { s: 'S03', name: 'Two-step devices, recovery codes', home: 'My account › Security', href: p('/account#two-step'), move: 'moved', role: 'Self' },
  { s: 'S04', name: 'Signed-in sessions', home: 'My account › Security', href: p('/account#sessions'), move: 'moved', role: 'Self' },
  { s: 'S05', name: 'Notification routing', home: 'Team › Notifications, and My notifications for the personal part', href: p('/team/notifications'), move: 'split', role: 'Team admin' },
  { s: 'S06', name: 'Members and roles', home: 'Govern › Access', href: p('/govern/access'), move: 'new home', role: 'Admin' },
  { s: 'S07', name: 'Sign-in methods', home: 'Govern › Security › Sign-in', href: p('/govern/security#sign-in'), move: 'new home', role: 'Security admin' },
  { s: 'S08', name: 'SSO connection', home: 'Govern › Security › Sign-in', href: p('/govern/security#sso'), move: 'new home', role: 'Security admin' },
  { s: 'S09', name: 'SSO domains', home: 'Govern › Security › Sign-in', href: p('/govern/security#sso-domains'), move: 'new home', role: 'Security admin' },
  { s: 'S10', name: 'Sign-in security', home: 'Govern › Security › Sign-in', href: p('/govern/security#sign-in-security'), move: 'new home', role: 'Security admin' },
  { s: 'S11', name: 'Self-signup', home: 'Govern › Security › Sign-in', href: p('/govern/security#signup'), move: 'new home', role: 'Security admin' },
  { s: 'S12', name: 'Webhooks', home: 'Team › Webhooks', href: p('/team/webhooks'), move: 'moved', role: 'Team admin' },
  { s: 'S13', name: 'API keys', home: 'Team › API keys', href: p('/team/api-keys'), move: 'moved', role: 'Admin' },
  { s: 'S14', name: 'Publish review policy', home: 'Govern › Policies', href: p('/govern/policies#publish-reviews'), move: 'new home', role: 'Admin' },
  { s: 'S15', name: 'Egress hosts', home: 'Govern › Security › Egress', href: p('/govern/security#egress'), move: 'new home', role: 'Security admin' },
  { s: 'S16', name: 'Egress private ranges', home: 'Govern › Security › Egress', href: p('/govern/security#egress-ranges'), move: 'new home', role: 'Security admin' },
  { s: 'S17', name: 'Secrets', home: 'Govern › Security › Secrets', href: p('/govern/security#secrets'), move: 'new home', role: 'Security admin' },
  { s: 'S18', name: 'Storage credentials', home: 'Workspace › Storage (listed on Secrets)', href: p('/workspace/storage#credentials'), move: 'moved', role: 'Security admin' },
  { s: 'S19', name: 'Storage targets by purpose', home: 'Workspace › Storage', href: p('/workspace/storage#targets'), move: 'moved', role: 'Security admin' },
  { s: 'S20', name: 'Upload limits', home: 'Workspace › Storage', href: p('/workspace/storage#limits'), move: 'moved', role: 'Security admin' },
  { s: 'S21', name: 'Retention class by purpose', home: 'Workspace › Storage', href: p('/workspace/storage#retention'), move: 'moved', role: 'Security admin' },
  { s: 'S22', name: 'Download link lifetime', home: 'Workspace › Storage', href: p('/workspace/storage#links'), move: 'moved', role: 'Security admin' },
  { s: 'S23', name: 'Gate policies', home: 'Govern › Policies', href: p('/govern/policies#gates'), move: 'new home', role: 'Admin' },
  { s: 'S24', name: 'Agent identity, owning team, model', home: 'Agent › Settings tab', href: p('/agent#identity'), move: 'stays on the object', role: 'Builder' },
  { s: 'S25', name: 'Agent instructions', home: 'Agent › Settings tab', href: p('/agent#instructions'), move: 'stays on the object', role: 'Builder' },
  { s: 'S26', name: 'Agent tools, knowledge, widgets, skills, guardrails', home: 'Agent › Settings tab', href: p('/agent#capabilities'), move: 'stays on the object', role: 'Builder' },
  { s: 'S27', name: 'Agent caller limits', home: 'Agent › Settings tab', href: p('/agent#limits'), move: 'stays on the object', role: 'Builder' },
  { s: 'S28', name: 'Per-conversation caps', home: 'Govern › Models (the agent tab shows the value in force)', href: p('/govern/models#caps'), move: 'new home', role: 'Admin' },
  { s: 'S29', name: 'Pause, delete agent', home: 'Agent › Settings tab › Danger zone', href: p('/agent#danger'), move: 'stays on the object', role: 'Builder' },
  { s: 'S30', name: 'Widget deployments', home: 'Agent › Deployments tab', href: p('/agent#deployments'), move: 'stays on the object', role: 'Builder' },
  { s: 'S31', name: 'Workflow details', home: 'Workflow › Settings tab', href: '/workflows', move: 'stays on the object', role: 'Builder' },
  { s: 'S32', name: 'Workflow email intake', home: 'Workflow › its tabs', href: '/workflows', move: 'stays on the object', role: 'Builder' },
  { s: 'S33', name: 'Guardrail rule', home: 'Guardrail › Settings tab', href: '/guardrails', move: 'stays on the object', role: 'Builder' },
  { s: 'S34', name: 'Widget definition', home: 'Widget › Settings tab', href: '/widgets', move: 'stays on the object', role: 'Builder' },
  { s: 'S35', name: 'Tool module connection', home: 'Tool › Connection tab', href: '/tools', move: 'stays on the object', role: 'Builder' },
  { s: 'S36', name: 'Tool module access and approval', home: 'Tool › Access and Approval tabs', href: '/tools', move: 'stays on the object', role: 'Builder, Security reviews' },
  { s: 'S37', name: 'Tool operation limits and approval', home: 'Tool › operation sheet', href: '/tools', move: 'stays on the object', role: 'Builder' },
  { s: 'S38', name: 'KB retrieval', home: 'Knowledge base › Settings tab (new)', href: '/knowledge', move: 'new home', role: 'Builder' },
  { s: 'S39', name: 'KB name, description, owner, collections', home: 'Knowledge base › Settings tab (new)', href: '/knowledge', move: 'new home', role: 'Builder' },
  { s: 'S40', name: 'Source settings', home: 'Connections › Settings tab', href: '/integrations', move: 'stays on the object', role: 'Builder' },
  { s: 'S41', name: 'Connection setup', home: 'Connections › Settings tab', href: '/integrations', move: 'stays on the object', role: 'Builder' },
  { s: 'S42', name: 'Thread settings', home: 'Chat thread sheet', href: '/chat', move: 'stays on the object', role: 'Thread owner' },
  { s: 'S43', name: 'Model providers, aliases, keys', home: 'Govern › Models', href: p('/govern/models#providers'), move: 'new home', role: 'Admin' },
];

/** Settings that exist only in the proposal (no S-number): the new General pages and the personal notification list. */
const NEW_SETTINGS: { name: string; href: string; keywords: string }[] = [
  { name: 'Workspace name and address', href: p('/workspace#name'), keywords: 'slug url brand logo' },
  { name: 'Workspace logo', href: p('/workspace#logo'), keywords: 'image brand' },
  { name: 'Team name and owner', href: p('/team#name'), keywords: 'rename' },
  { name: 'My notifications', href: p('/account#my-notifications'), keywords: 'mute email personal' },
  { name: 'Transfer ownership', href: p('/workspace#transfer'), keywords: 'danger owner' },
  { name: 'Delete workspace', href: p('/workspace#delete'), keywords: 'danger remove' },
];

export interface FindHit {
  label: string;
  where: string;
  href: string;
}

/** What the Find box searches: every mapped setting by name, number, home and role, plus the new ones. */
export function findSettings(query: string): FindHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const all: (FindHit & { hay: string })[] = [
    ...S_MAP.map((m) => ({ label: m.name, where: m.home, href: m.href, hay: `${m.s} ${m.name} ${m.home} ${m.role}`.toLowerCase() })),
    ...NEW_SETTINGS.map((n) => ({ label: n.name, where: 'New in the proposal', href: n.href, hay: `${n.name} ${n.keywords}`.toLowerCase() })),
  ];
  return all.filter((h) => q.split(/\s+/).every((w) => h.hay.includes(w))).slice(0, 12);
}

export interface DialogDoc {
  dialog: string;
  form: string;
  mother: string;
  motherLabel: string;
  opensFrom: string;
  calls: string;
}

/** Each contextual dialog and the settings page it is the same form as. */
export const DIALOGS: DialogDoc[] = [
  { dialog: 'Add allowed host', form: 'EgressHostForm', mother: p('/govern/security#egress'), motherLabel: 'Govern › Security › Egress', opensFrom: 'A tool page whose operation points at a host that is not allowed', calls: 'POST /v1/egress/hosts' },
  { dialog: 'Add secret', form: 'SecretForm', mother: p('/govern/security#secrets'), motherLabel: 'Govern › Security › Secrets', opensFrom: 'A tool page whose header names a secret that does not exist', calls: 'POST /v1/secrets' },
  { dialog: 'Model alias', form: 'ModelAliasForm', mother: p('/govern/models#aliases'), motherLabel: 'Govern › Models › Aliases', opensFrom: 'An agent’s Settings tab, from the model picker', calls: 'POST /v1/models/aliases' },
];

const GROUPS = ['Workspace', 'Team', 'Govern', 'Examples'] as const;

/** The mock's sidebar: its sections, its personal items, Find over the S01 to S43 mapping, and the role switch. */
export const PREVIEW_TREE: SidebarTree = {
  home: PREVIEW_ROOT,
  groups: GROUPS.map((g) => ({ label: g, items: SECTIONS.filter((s) => s.group === g).map((s) => ({ id: s.id, label: s.label, href: s.href })) })),
  personal: PERSONAL,
  find: findSettings,
  roleSwitch: true,
};
