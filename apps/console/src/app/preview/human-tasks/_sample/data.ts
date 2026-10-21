/**
 * Sample queue for the Human Tasks mock (/preview/human-tasks, c-460). Nothing here is read from or written to a
 * service. One queue item is one case or notice; each task inside it is one decision, so a court order notice naming
 * three debtors is one item with three holds to decide. Two kinds are shown, a court order hold and a card dispute's
 * provisional credit, to show the page is drawn from the task's facts and options rather than built for one kind.
 */
import { DOCUMENTS } from './documents';

export const ROOT = '/preview/human-tasks';
export const ME = 'Maya Okafor';
export const PEOPLE = ['James Richardson', 'Wanjiru Kamau', 'Daniel Osei'];

export type TaskKind = 'court_order' | 'card_dispute';

export interface Fact {
  label: string;
  value: string;
  /** Drawn in the warning colour: the fact the decision turns on. */
  warn?: boolean;
}

export interface TaskOption {
  id: string;
  label: string;
  /** What choosing it does, in one sentence. */
  consequence: string;
  /** Money moves: a fresh sign-in is asked for before it is recorded. */
  stepUp?: string;
  /** The toast once decided: the outcome in a few words. */
  outcome: string;
}

export interface Task {
  id: string;
  /** Whom the decision is about, by name. */
  subject: string;
  question: string;
  amount: number;
  /** The account or card it touches. */
  account: string;
  facts: Fact[];
  /** A warning above the options, when the facts say the obvious choice will not work as asked. */
  warning?: { title: string; body: string };
  options: TaskOption[];
  suggested?: string;
  /** Keys of the document's read fields that belong to this task; the first is selected when the task opens. */
  fields: string[];
}

export interface QueueItem {
  id: string;
  kind: TaskKind;
  title: string;
  /** The case every task here writes its outcome to. */
  caseRef: string;
  source: string;
  received: string;
  due: string;
  assignee: string;
  /** The amount at stake across its tasks, as the service sends it. */
  total: number;
  document: { name: string; url: string; boxes: { key: string; page: number; x: number; y: number; w: number; h: number; check?: boolean }[] };
  tasks: Task[];
}

export const KIND_LABEL: Record<TaskKind, string> = { court_order: 'Court order notice', card_dispute: 'Card dispute' };

/** A due time this many hours from now, on the hour, so the sample always reads as live work. */
function dueIn(hours: number): string {
  const d = new Date(Date.now() + hours * 3_600_000);
  d.setMinutes(0, 0, 0);
  return d.toISOString();
}

export const cad = (n: number) => `${n.toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} CAD`;

/** Boxes for the fields this item's tasks read, marked to check where a fact turns on them. */
function doc(key: keyof typeof DOCUMENTS, name: string, check: string[] = []) {
  const d = DOCUMENTS[key];
  return { name, url: d.url, boxes: d.boxes.map((b) => ({ ...b, check: check.includes(b.key) })) };
}

function hold(id: string, n: number, subject: string, accountName: string, account: string, available: number, existing: string, ordered: number): Task {
  const over = ordered > available;
  const heldNow = over ? available : ordered;
  return {
    id,
    subject,
    question: `Place the court-ordered hold on ${subject}'s account?`,
    amount: ordered,
    account,
    fields: [`amount-${n}`, `name-${n}`, `account-${n}`],
    facts: [
      { label: 'Account', value: `${subject}, ${accountName} ${account}` },
      { label: 'Available balance', value: cad(available), warn: over },
      { label: 'Existing holds', value: existing },
      { label: 'Ordered amount', value: cad(ordered), warn: over },
    ],
    warning: over
      ? {
          title: `The order is ${cad(ordered - available)} more than the available balance`,
          body: `A hold places ${cad(available)} now. The shortfall of ${cad(ordered - available)} is reported to the registry on the case.`,
        }
      : undefined,
    options: [
      {
        id: 'hold',
        label: over ? `Hold the available ${cad(heldNow)}` : `Hold ${cad(ordered)}`,
        consequence: over
          ? `Holds ${cad(heldNow)} on ${account} until the court releases it, and reports the shortfall to the registry.`
          : `Holds ${cad(ordered)} on ${account} until the court releases it; ${subject} cannot withdraw it.`,
        stepUp: 'hold',
        outcome: `${cad(heldNow)} held on ${account}`,
      },
      {
        id: 'flag',
        label: 'Flag, no hold',
        consequence: `Writes a note on ${subject}'s record for the legal process team; no funds are held and the registry is not told yet.`,
        outcome: `${subject} flagged for the legal process team`,
      },
    ],
    suggested: 'hold',
  };
}

function credit(id: string, subject: string, card: string, amount: number, merchant: string, when: string, reason: string, prior: string, contacted: string): Task {
  return {
    id,
    subject,
    question: `Give ${subject} a provisional credit of ${cad(amount)}?`,
    amount,
    account: card,
    fields: ['amount', 'reason', 'cardholder', 'merchant', 'date'],
    facts: [
      { label: 'Cardholder', value: subject },
      { label: 'Card', value: card },
      { label: 'Disputed charge', value: `${cad(amount)}, ${merchant}, ${when}` },
      { label: 'Reason', value: reason },
      { label: 'Merchant contacted', value: contacted },
      { label: 'Disputes in the last 12 months', value: prior },
    ],
    options: [
      {
        id: 'credit',
        label: `Give provisional credit of ${cad(amount)}`,
        consequence: `Credits ${cad(amount)} to the card today and opens a chargeback; if the merchant wins it, the credit is reversed with 10 days' notice.`,
        stepUp: 'credit',
        outcome: `${cad(amount)} credited to ${card}`,
      },
      {
        id: 'decline',
        label: 'Decline provisional credit',
        consequence: `No credit now. The chargeback still opens and ${subject} is told the dispute is under review.`,
        outcome: `Provisional credit declined for ${subject}`,
      },
    ],
    suggested: 'credit',
  };
}

/** The queue as the service would send it: open items, each with its tasks. The page sorts by due. */
const ITEMS: Omit<QueueItem, 'total'>[] = [
  {
    id: 'notice-10412',
    kind: 'court_order',
    title: 'Court order notice NS-2026-GN-10412',
    caseRef: 'HP-2026-0412',
    source: 'Court Registry, by email',
    received: '15 Oct, 9:14 am',
    due: dueIn(5),
    assignee: ME,
    document: doc('notice10412', 'court-order-notice-NS-2026-GN-10412.pdf', ['amount-1']),
    tasks: [
      hold('t-10412-1', 1, 'Marcus Bell', 'Chequing', 'CHQ-2219', 2140.55, 'None', 3250),
      hold('t-10412-2', 2, 'Priya Natarajan', 'Savings', 'SAV-4471', 9312.4, '250.00 CAD, court order NS-2026-GN-09871 (2 Oct)', 1800),
      hold('t-10412-3', 3, 'Jordan Whitfield', 'Chequing', 'CHQ-3307', 4020.18, 'None', 975),
    ],
  },
  {
    id: 'dispute-58213',
    kind: 'card_dispute',
    title: 'Card dispute DSP-58213',
    caseRef: 'HP-2026-0398',
    source: 'Branch 014, Spring Garden Road',
    received: '17 Oct, 2:40 pm',
    due: dueIn(22),
    assignee: ME,
    document: doc('dispute58213', 'card-dispute-DSP-58213.pdf'),
    tasks: [credit('t-58213', 'Elena Vasquez', 'Visa ••4417', 486.2, 'Northwind Outdoor Supply', '3 Oct', 'Goods not received', 'None', 'Yes, on 12 and 16 Oct, no reply')],
  },
  {
    id: 'notice-10398',
    kind: 'court_order',
    title: 'Court order notice NS-2026-GN-10398',
    caseRef: 'HP-2026-0401',
    source: 'Court Registry, by email',
    received: '14 Oct, 4:02 pm',
    due: dueIn(46),
    assignee: ME,
    document: doc('notice10398', 'court-order-notice-NS-2026-GN-10398.pdf'),
    tasks: [hold('t-10398-1', 1, 'Owen Tremblay', 'Chequing', 'CHQ-1180', 1512, 'None', 600)],
  },
  {
    id: 'dispute-58190',
    kind: 'card_dispute',
    title: 'Card dispute DSP-58190',
    caseRef: 'HP-2026-0405',
    source: 'Online banking',
    received: '18 Oct, 8:15 am',
    due: dueIn(70),
    assignee: ME,
    document: doc('dispute58190', 'card-dispute-DSP-58190.pdf'),
    tasks: [credit('t-58190', 'Samir Haddad', 'Mastercard ••0921', 129.99, 'StreamBox Plus', '9 Oct', 'Cancelled subscription charged', '1, decided for the cardholder in March', 'Yes, cancellation email on 28 Sep')],
  },
];

export const QUEUE: QueueItem[] = ITEMS.map((i) => ({ ...i, total: i.tasks.reduce((s, t) => s + t.amount, 0) }));

/** "Due in 5 h", "Due tomorrow 2:00 pm", "Due Thu 23 Oct": how close it is, in the words a reviewer scans for. */
export function dueText(iso: string): string {
  const d = new Date(iso);
  const hours = (d.getTime() - Date.now()) / 3_600_000;
  const time = d.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit' });
  if (hours < 0) return 'Overdue';
  if (hours < 12) return `Due in ${Math.max(1, Math.round(hours))} h`;
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return `Due today ${time}`;
  if (d.toDateString() === tomorrow.toDateString()) return `Due tomorrow ${time}`;
  return `Due ${d.toLocaleDateString('en-CA', { weekday: 'short', day: 'numeric', month: 'short' })}`;
}

export const isSoon = (iso: string) => new Date(iso).getTime() - Date.now() < 12 * 3_600_000;
