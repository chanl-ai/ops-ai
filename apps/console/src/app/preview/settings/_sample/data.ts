/** Sample rows for the settings mock (c-178). Nothing here is read from or written to a service. */
const ago = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

export interface SampleMember {
  id: string;
  name: string;
  email: string;
  role: 'Builder' | 'Approver' | 'Admin' | 'Security admin';
  team: string;
  lastActiveAt: string;
}
export const MEMBERS: SampleMember[] = [
  { id: 'usr_3f9a1c70', name: 'James Richardson', email: 'j.richardson@harborpine.example', role: 'Builder', team: 'Operations', lastActiveAt: ago(8) },
  { id: 'usr_a41d7e22', name: 'Maya Okafor', email: 'm.okafor@harborpine.example', role: 'Approver', team: 'Operations', lastActiveAt: ago(95) },
  { id: 'usr_58c2b9f4', name: 'Sam Adeyemi', email: 's.adeyemi@harborpine.example', role: 'Security admin', team: 'Security', lastActiveAt: ago(3) },
  { id: 'usr_e07b36d1', name: 'Nadia Petrov', email: 'n.petrov@harborpine.example', role: 'Approver', team: 'Security', lastActiveAt: ago(60 * 7) },
  { id: 'usr_91d4a8c5', name: 'Priya Shah', email: 'p.shah@harborpine.example', role: 'Admin', team: 'Platform', lastActiveAt: ago(22) },
];

export interface SampleKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  team: string;
  lastUsedAt?: string;
}
export const API_KEYS: SampleKey[] = [
  { id: 'key_6b2e9d03', name: 'Core banking runs', prefix: 'opk_live_8f3a', scopes: ['runs:write', 'logs:read'], team: 'Operations', lastUsedAt: ago(4) },
  { id: 'key_c85f1a47', name: 'Branch dashboard', prefix: 'opk_live_21de', scopes: ['logs:read'], team: 'Operations', lastUsedAt: ago(60 * 30) },
  { id: 'key_0e7d4b92', name: 'Fraud alerts', prefix: 'opk_live_b90c', scopes: ['runs:write'], team: 'Fraud' },
];

export interface SampleWebhook {
  id: string;
  name: string;
  url: string;
  events: string[];
  health: 'ok' | 'warn' | 'error';
  lastDeliveryAt: string;
}
export const WEBHOOKS: SampleWebhook[] = [
  { id: 'wh_2d8c5e71', name: 'Case system', url: 'https://cases.harborpine.example/hooks/ops', events: ['run.finished', 'review.requested'], health: 'ok', lastDeliveryAt: ago(2) },
  { id: 'wh_77a1f0b3', name: 'Pager', url: 'https://pager.harborpine.example/in/ops-ai', events: ['sla.breached'], health: 'warn', lastDeliveryAt: ago(60 * 5) },
];

export interface SampleGate {
  id: string;
  name: string;
  workflow: string;
  reviewers: string;
  sla: string;
  onTimeout: string;
}
export const GATES: SampleGate[] = [
  { id: 'gp_1a9e3c58', name: 'Wire over $10,000', workflow: 'Wire transfer', reviewers: 'Treasury approvers', sla: '4 hours', onTimeout: 'Escalate' },
  { id: 'gp_8c24d7e0', name: 'Fee waiver over $200', workflow: 'Fee dispute', reviewers: 'Branch managers', sla: '1 day', onTimeout: 'Reject' },
  { id: 'gp_d3f60b19', name: 'Account closure', workflow: 'Account servicing', reviewers: 'Retention team', sla: '2 hours', onTimeout: 'Escalate' },
];

/** The shape GET and PUT /v1/policies will serve (c-186): one object per policy. Every default is open. */
export interface PolicyDef {
  key: string;
  title: string;
  value: string;
  default: string;
  role: 'Admin';
  effect: string;
  options: { value: string; title: string; description: string }[];
}
export const POLICIES: PolicyDef[] = [
  {
    key: 'requester_may_decide_own',
    title: 'Requester may decide their own request',
    value: 'yes',
    default: 'yes',
    role: 'Admin',
    effect: 'Whether the person who asked for a write may also approve it.',
    options: [
      { value: 'yes', title: 'Yes', description: 'Anyone who may approve can approve their own request.' },
      { value: 'no', title: 'No', description: 'A different person has to approve.' },
    ],
  },
  {
    key: 'distinct_second_approver',
    title: 'Distinct second approver',
    value: 'off',
    default: 'off',
    role: 'Admin',
    effect: 'Whether a gate that needs two approvers insists on two different people.',
    options: [
      { value: 'off', title: 'Off', description: 'One person may give both approvals.' },
      { value: 'on', title: 'On', description: 'The two approvals must come from two people.' },
    ],
  },
  {
    key: 'publish_review',
    title: 'Publish review',
    value: 'off',
    default: 'off',
    role: 'Admin',
    effect: 'Which publishes open a review that a different person decides.',
    options: [
      { value: 'off', title: 'Off', description: 'Publishes go live at once.' },
      { value: 'risky_writes', title: 'Risky writes', description: 'A version that adds a write tool opens a review.' },
      { value: 'every_change', title: 'Every change', description: 'Every publish opens a review.' },
    ],
  },
  {
    key: 'resign_before_deciding',
    title: 'Re-sign-in before deciding',
    value: 'off',
    default: 'off',
    role: 'Admin',
    effect: 'Whether an approver confirms their password before a money approval counts.',
    options: [
      { value: 'off', title: 'Off', description: 'A signed-in approver decides directly.' },
      { value: 'on', title: 'On', description: 'The approver re-enters their password within five minutes of deciding.' },
    ],
  },
  {
    key: 'extraction_confidence_floor',
    title: 'Extraction confidence floor',
    value: 'none',
    default: 'none',
    role: 'Admin',
    effect: 'Below this, a value read from a document waits for a person to check it.',
    options: [
      { value: 'none', title: 'None', description: 'Every extracted value is used as read.' },
      { value: '0.7', title: '70%', description: 'Low-confidence values wait for a check.' },
      { value: '0.85', title: '85%', description: 'Only confident values pass unchecked.' },
      { value: '0.95', title: '95%', description: 'Almost every value is checked.' },
    ],
  },
  {
    key: 'chat_thread_visibility',
    title: 'Chat thread visibility',
    value: 'owner',
    default: 'owner',
    role: 'Admin',
    effect: 'Who can open a chat thread besides the person who started it.',
    options: [
      { value: 'owner', title: 'Owner only', description: 'Only the person who started the thread.' },
      { value: 'team_admins', title: 'Team admins', description: 'Admins of the thread’s team can read it too.' },
      { value: 'team', title: 'The team', description: 'Everyone in the thread’s team can read it.' },
    ],
  },
];

export const CHANNELS = [
  { value: 'app', title: 'In Ops AI', description: 'The bell and the Reviews queue.' },
  { value: 'email', title: 'Email', description: 'To the team address. Approvals can be decided from the email.' },
  { value: 'slack', title: 'Slack', description: 'To #ops-ai-alerts. Approvals can be decided from Slack.' },
  { value: 'pager', title: 'Pager', description: 'Pages the on-call person. Alerts only.' },
];

export const STORAGE_PURPOSES = ['Wiki', 'Chat uploads', 'Mail attachments', 'Exports'];
