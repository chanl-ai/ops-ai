import type { ChatWidget, ToolCall } from '@/lib/types/chat';

/**
 * Canned agent turns. A turn calls tools (each result may carry MCP App widgets), then writes text. Turns with
 * `ground` instead answer from the thread's knowledge bases through the knowledge query API.
 */
export interface TurnPlan {
  steps: { call: Omit<ToolCall, 'id' | 'status'>; widgets: ChatWidget[] }[];
  text: string;
  /** Answer from knowledge instead of `text`. */
  ground?: boolean;
}

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const wid = (p: string) => `${p}_${Math.random().toString(36).slice(2, 7)}`;

/** Open cases per queue, computed from the cases the Cases page lists. */
export interface QueueSla {
  queue: string;
  open: number;
  breaching: number;
  breachingAwaitingApproval: number;
  dueSoon: number;
  oldestOverMinutes: number | null;
}

const pl = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const span = (m: number) => (m < 60 ? `${m} minutes` : m < 60 * 48 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 1440)} days ${Math.floor((m % 1440) / 60)} h`);

function slaTurn(sla: QueueSla[]): TurnPlan {
  const asOf = minsAgo(0);
  const breaching = sla.reduce((n, q) => n + q.breaching, 0);
  const dueSoon = sla.reduce((n, q) => n + q.dueSoon, 0);
  const withBreaches = sla.filter((q) => q.breaching > 0);
  const most = [...withBreaches].sort((a, b) => b.breaching - a.breaching)[0];
  const longest = [...withBreaches].sort((a, b) => (b.oldestOverMinutes ?? 0) - (a.oldestOverMinutes ?? 0))[0];
  const calm = sla.find((q) => q.breaching === 0 && q.dueSoon > 0);
  const rows = sla.map((q) => ({ queue: q.queue, open: q.open, breaching: q.breaching, dueSoon: q.dueSoon, oldest: q.oldestOverMinutes == null ? 'None' : `${span(q.oldestOverMinutes)} over` }));
  const lines = [
    breaching
      ? `**${pl(breaching, 'case is', 'cases are')} past their SLA** across ${pl(withBreaches.length, 'queue', 'queues')}, and ${dueSoon} more ${dueSoon === 1 ? 'falls' : 'fall'} due within the hour.`
      : `**No open cases are past their SLA.** ${pl(dueSoon, 'case falls', 'cases fall')} due within the hour.`,
    '',
    ...(most ? [`- **${most.queue}** has the most: ${most.breaching} breaching, the oldest ${span(most.oldestOverMinutes ?? 0)} over.`] : []),
    ...(longest && longest !== most ? [`- **${longest.queue}** has the longest breach, ${span(longest.oldestOverMinutes ?? 0)} over.`] : []),
    ...(calm ? [`- **${calm.queue}** has none breaching, but ${calm.dueSoon} fall due within the hour.`] : []),
    ...(most && most.breachingAwaitingApproval ? ['', `Start with ${most.queue}: ${most.breachingAwaitingApproval} of its ${most.breaching} breaches are waiting on an approval, not on the agent.`] : []),
  ];
  return {
    steps: [
      {
        call: { name: 'sla_report', server: 'case-engine', input: { status: 'open', groupBy: 'queue' }, output: { queues: sla.length, breaching, dueWithinHour: dueSoon }, durationMs: 412 },
        widgets: [
          {
            id: wid('w'),
            kind: 'table',
            title: 'Open cases by queue',
            app: 'Case engine',
            tool: 'sla_report',
            asOf,
            href: '/cases',
            columns: [
              { key: 'queue', label: 'Queue' },
              { key: 'open', label: 'Open', align: 'right' },
              { key: 'breaching', label: 'Breaching', align: 'right', tone: true },
              { key: 'dueSoon', label: 'Due within 1 h', align: 'right' },
              { key: 'oldest', label: 'Oldest breach' },
            ],
            rows,
          },
          {
            id: wid('w'),
            kind: 'chart',
            chart: 'bar',
            title: 'Breaching and due within the hour',
            app: 'Case engine',
            tool: 'sla_report',
            asOf,
            xKey: 'queue',
            yLabel: 'Cases',
            series: [
              { key: 'breaching', label: 'Breaching' },
              { key: 'dueSoon', label: 'Due within 1 h' },
            ],
            data: sla.map(({ queue, breaching: b, dueSoon: d }) => ({ queue, breaching: b, dueSoon: d })),
          },
        ],
      },
    ],
    text: lines.join('\n'),
  };
}

function disputeTurn(reviewers: string): TurnPlan {
  const asOf = minsAgo(0);
  return {
    steps: [
      {
        call: { name: 'get_review', server: 'ops-ai', input: { id: 'REV-3020' }, output: { id: 'REV-3020', status: 'pending', proposal: 'Provisional credit $1,240.18' }, durationMs: 188 },
        widgets: [],
      },
      {
        call: {
          name: 'get_transactions',
          server: 'core-banking',
          input: { card: '••4417', merchant: 'Northline Electronics', days: 30 },
          output: { matches: 2, amount: 1240.18, secondsApart: 41 },
          durationMs: 634,
        },
        widgets: [
          {
            id: wid('w'),
            kind: 'record',
            title: 'Dispute REV-3020',
            subtitle: 'Priya Natarajan · Visa ••4417',
            status: 'Pending review',
            app: 'Core banking',
            tool: 'get_transactions',
            asOf,
            href: '/reviews?review=REV-3020',
            fields: [
              { label: 'Merchant', value: 'Northline Electronics' },
              { label: 'Charges', value: '2 × $1,240.18, 41 seconds apart' },
              { label: 'Reason code', value: '12.6 Duplicate processing' },
              { label: 'Filed', value: '50 minutes ago by phone' },
              { label: 'Customer tenure', value: '9 years, no prior disputes' },
            ],
          },
        ],
      },
      {
        call: {
          name: 'issue_provisional_credit',
          server: 'core-banking',
          input: { account: 'Chequing ••2290', amount: 1240.18, currency: 'CAD', chargebackReason: '12.6' },
          output: { drafted: true, review: 'REV-3020' },
          durationMs: 96,
          gated: { gate: 'Credit above threshold', reviewers },
        },
        widgets: [
          {
            id: wid('w'),
            kind: 'approval',
            title: 'Provisional credit',
            app: 'Core banking',
            tool: 'issue_provisional_credit',
            asOf,
            reviewId: 'REV-3020',
            action: 'Issue a provisional credit and open a chargeback',
            summary: 'The second charge duplicates the first. The Dispute Rights Guide allows a provisional credit for reason 12.6 while the chargeback runs.',
            fields: [
              { label: 'Amount', value: '$1,240.18 CAD' },
              { label: 'To', value: 'Chequing ••2290' },
              { label: 'Chargeback', value: 'Reason 12.6, Visa' },
            ],
            risk: 'low',
            consequence: 'Posts a provisional credit of $1,240.18 CAD to Chequing ••2290 now and opens a Visa chargeback (reason 12.6) with Northline Electronics.',
            state: 'pending',
          },
        ],
      },
    ],
    text:
      'Priya Natarajan was charged **$1,240.18 twice** by Northline Electronics, 41 seconds apart. Only one purchase appears on the merchant receipt she sent, so the second settlement is a duplicate (reason 12.6).\n\n' +
      'I drafted the provisional credit above. It is over the $1,000 threshold, so it needs your approval before it posts. Approving it here decides REV-3020 in the Reviews queue.',
  };
}

function kycTurn(): TurnPlan {
  const asOf = minsAgo(0);
  return {
    steps: [
      {
        call: { name: 'lookup_customer', server: 'crm', input: { name: 'Daniel Okoye' }, output: { id: 'CUS-58812', lastKyc: '2023-04-18', riskRating: 'medium' }, durationMs: 287 },
        widgets: [
          {
            id: wid('w'),
            kind: 'record',
            title: 'Daniel Okoye',
            subtitle: 'CUS-58812 · Personal banking',
            status: 'KYC overdue',
            app: 'CRM',
            tool: 'lookup_customer',
            asOf,
            fields: [
              { label: 'Last KYC refresh', value: '18 April 2023' },
              { label: 'Risk rating', value: 'Medium (refresh every 24 months)' },
              { label: 'Products', value: 'Chequing, mortgage application in progress' },
              { label: 'Relationship manager', value: 'Anika Singh' },
            ],
          },
          {
            id: wid('w'),
            kind: 'form',
            title: 'KYC refresh request',
            app: 'Case engine',
            tool: 'open_case',
            asOf,
            description: 'Opens a case in the KYC refresh queue. The SLA starts when you submit.',
            submitLabel: 'Open request',
            state: 'open',
            fields: [
              { key: 'customer', label: 'Customer', type: 'text', value: 'Daniel Okoye (CUS-58812)', required: true },
              { key: 'reason', label: 'Reason', type: 'select', options: ['Periodic review due', 'Change in ownership', 'Adverse media', 'Unusual activity'], value: 'Periodic review due', required: true },
              { key: 'priority', label: 'Priority', type: 'select', options: ['Standard (5 business days)', 'Expedited (1 business day)'], value: 'Expedited (1 business day)', required: true },
              { key: 'notes', label: 'Notes', type: 'textarea', value: 'Mortgage application in progress; refresh before underwriting.' },
            ],
          },
        ],
      },
    ],
    text:
      'Daniel Okoye’s last KYC refresh was on **18 April 2023**, so at a medium risk rating it is overdue. His mortgage application cannot go to underwriting until it is refreshed.\n\n' +
      'I filled in the request above and marked it expedited because of the application. Check the details and open it.',
  };
}

function metricsTurn(): TurnPlan {
  const asOf = minsAgo(0);
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const opened = [212, 238, 197, 226, 241, 88, 82];
  const drafted = [151, 172, 139, 163, 175, 61, 59];
  return {
    steps: [
      {
        call: { name: 'case_metrics', server: 'case-engine', input: { range: '7d' }, output: { opened: 1284, autoDrafted: 0.71 }, durationMs: 356 },
        widgets: [
          {
            id: wid('w'),
            kind: 'metric',
            title: 'Last 7 days',
            app: 'Case engine',
            tool: 'case_metrics',
            asOf,
            metrics: [
              { label: 'Cases opened', value: '1,284', delta: '+6% vs prior week', tone: 'neutral' },
              { label: 'Actions drafted by agents', value: '71%', delta: '+4 pts', tone: 'good' },
              { label: 'Median time to approve', value: '14 min', delta: '−3 min', tone: 'good' },
              { label: 'SLA breaches', value: '19', delta: '+5', tone: 'bad' },
            ],
          },
          {
            id: wid('w'),
            kind: 'chart',
            chart: 'line',
            title: 'Cases opened and drafted per day',
            app: 'Case engine',
            tool: 'case_metrics',
            asOf,
            xKey: 'day',
            yLabel: 'Cases',
            series: [
              { key: 'opened', label: 'Opened' },
              { key: 'drafted', label: 'Drafted by an agent' },
            ],
            data: days.map((day, i) => ({ day, opened: opened[i], drafted: drafted[i] })),
          },
        ],
      },
    ],
    text: 'Volume is up 6% on last week and agents drafted the actions on 71% of cases. Breaches rose to 19, mostly in Card disputes on Thursday and Friday when approvals queued behind a single reviewer.',
  };
}

const ATTACH = (name: string): TurnPlan['steps'][number] => ({
  call: { name: 'read_document', server: 'ops-ai', input: { file: name }, output: { pages: 3, extracted: true }, durationMs: 520 },
  widgets: [],
});

/** Picks the turn for a question. Anything unmatched is answered from knowledge. */
export function planTurn(question: string, opts: { attachments: string[]; reviewers: string; sla: QueueSla[] }): TurnPlan {
  const q = question.toLowerCase();
  const plan: TurnPlan = /breach|sla|overdue cases|by queue/.test(q)
    ? slaTurn(opts.sla)
    : /rev-3020|provisional credit|duplicate charge|draft the credit/.test(q)
      ? disputeTurn(opts.reviewers)
      : /kyc|refresh request/.test(q)
        ? kycTurn()
        : /volume|this week|metrics|how are we doing|last 7 days/.test(q)
          ? metricsTurn()
          : { steps: [], text: '', ground: true };
  return { ...plan, steps: [...opts.attachments.map(ATTACH), ...plan.steps] };
}

/** Starter prompts per agent; agents without an entry get the general set. */
export const SUGGESTIONS: Record<string, string[]> = {
  ag_dispute: ['Show breaching SLA cases by queue', 'Summarise dispute REV-3020 and draft the credit', 'How are we doing this week?'],
  ag_fraud: ['What is our new-payee wire hold rule?', 'Show breaching SLA cases by queue', 'Who can release a wire with a risk score of 75?'],
  ag_kyb: ['Open a KYC refresh request for Daniel Okoye', 'How long do we keep customer due diligence records?'],
  ag_loan: ['What is the origination fee on a small business loan over $250k?', 'Show breaching SLA cases by queue'],
  ag_branch: ['What is the refund window for an annual card fee?', 'What is the wire cut-off time at the Halifax branch?'],
};
export const GENERAL_SUGGESTIONS = ['Show breaching SLA cases by queue', 'What is our new-payee wire hold rule?', 'How are we doing this week?'];
