import type { CaseAction, CaseDetail, CaseEvent, CaseMessage, CaseStatus } from '@/lib/types/cases';

import { EMAIL_CONFIGS, MAILBOXES } from './configs';

/** Seed cases: realistic inbound emails for Northfield Bank. Names and accounts are invented. */

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

interface Template {
  workflowId: string;
  intentId: string;
  subject: string;
  body: string;
  fields: Record<string, string>;
  amount?: number;
  attachments?: { name: string; sizeKb: number; summary: string; infected?: boolean }[];
  account: string;
}

const T: Template[] = [
  {
    workflowId: 'wf_card_inbox', intentId: 'dispute_charge', account: 'Visa •• 4471',
    subject: 'Charge I did not make on my card',
    body: 'Hello,\n\nThere is a charge of $412.18 from TRVL*BOOKINGS AMS on my Visa ending 4471, dated September 28. I have not travelled and did not book anything. Please reverse it.\n\nThanks',
    fields: { card_last4: '4471', merchant: 'TRVL*BOOKINGS AMS', amount: '$412.18', transaction_date: '2026-09-28' }, amount: 412.18,
    attachments: [{ name: 'statement-sep.pdf', sizeKb: 184, summary: 'September statement; the disputed line is highlighted on page 2.' }],
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'dispute_charge', account: 'Mastercard •• 2231',
    subject: 'Charged twice for one purchase',
    body: 'Hi,\n\nLakeside Furniture charged my card ending 2231 twice for the same order ($1,240.18 each, both on October 1). I only placed one order. The receipt is attached.\n\nRegards',
    fields: { card_last4: '2231', merchant: 'Lakeside Furniture', amount: '$1,240.18', transaction_date: '2026-10-01' }, amount: 1240.18,
    attachments: [
      { name: 'receipt-LF-88213.jpg', sizeKb: 912, summary: 'One receipt for order LF-88213, total $1,240.18, paid by card ending 2231.' },
      { name: 'remittance-advice.docm', sizeKb: 58, summary: '', infected: true },
    ],
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'dispute_charge', account: 'Visa •• 9012',
    subject: 'Order never arrived',
    body: 'I ordered headphones from SoundHaus online on September 12 for $89.00. Nothing arrived and the seller stopped replying. Can you get my money back?',
    fields: { card_last4: '9012', merchant: 'SoundHaus', amount: '$89.00', transaction_date: '2026-09-12' }, amount: 89,
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'dispute_charge', account: 'Visa •• 5508',
    subject: 'Subscription charged after I cancelled',
    body: 'StreamBox kept charging me $16.99 for August and September after I cancelled in July. The cancellation email is attached.',
    fields: { card_last4: '5508', merchant: 'StreamBox', amount: '$33.98', transaction_date: '2026-09-03' }, amount: 33.98,
    attachments: [{ name: 'cancellation-confirmation.eml', sizeKb: 22, summary: 'StreamBox cancellation confirmation dated July 14, 2026.' }],
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'lost_stolen', account: 'Visa •• 7720',
    subject: 'URGENT wallet stolen',
    body: 'My wallet was stolen on the subway about an hour ago. My Northfield Visa ending 7720 was in it. Please block it right away.',
    fields: { card_last4: '7720', last_known_use: 'Coffee shop, 08:12 today' },
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'lost_stolen', account: 'Mastercard •• 3349',
    subject: 'Card may be compromised',
    body: 'I used my card at a gas station on Route 9 and now there are three small charges from places I have never been. I think it was skimmed. Card ends 3349.',
    fields: { card_last4: '3349', last_known_use: 'Fuel stop, Route 9, yesterday' },
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'fee_refund', account: 'Visa •• 4471',
    subject: 'Late fee charged by mistake',
    body: 'I was charged a $39 late fee on my statement, but I paid on the due date (September 25). The payment confirmation is attached. Please refund the fee.',
    fields: { fee_type: 'Late fee', amount: '$39.00' }, amount: 39,
    attachments: [{ name: 'payment-confirmation.png', sizeKb: 240, summary: 'Online banking confirmation of a $1,200 card payment on Sept 25, 2026 at 21:40.' }],
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'fee_refund', account: 'Mastercard •• 6610',
    subject: 'Annual fee waiver',
    body: 'I have been a Northfield customer for 12 years. Could you waive this year’s $120 annual fee on my World card?',
    fields: { fee_type: 'Annual fee', amount: '$120.00' }, amount: 120,
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'fee_refund', account: 'Visa •• 1184',
    subject: 'Foreign transaction fee on a CAD purchase',
    body: 'I was charged a 2.5% foreign transaction fee ($4.12) on a purchase that was in Canadian dollars. My card is Canadian. Why?',
    fields: { fee_type: 'Foreign transaction fee', amount: '$4.12' }, amount: 4.12,
  },
  {
    workflowId: 'wf_card_inbox', intentId: 'address_change', account: 'Visa •• 2290',
    subject: 'New address',
    body: 'I moved last month. Please update my address to 88 Harbour Street, Unit 1204, Toronto ON M5J 0B2, effective October 1.',
    fields: { new_address: '88 Harbour Street, Unit 1204, Toronto ON M5J 0B2', effective_date: '2026-10-01' },
    attachments: [{ name: 'utility-bill.pdf', sizeKb: 330, summary: 'Hydro bill dated Sept 20, 2026 addressed to 88 Harbour Street, Unit 1204.' }],
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'payment_deferral', account: 'Mortgage 7700-31842',
    subject: 'Cannot make next mortgage payment',
    body: 'Hello,\n\nI was laid off on September 19 and I will not be able to make the November 1 payment on mortgage 7700-31842. Is it possible to defer two payments while I look for work?\n\nThank you',
    fields: { loan_number: '7700-31842', months: '2', reason: 'Job loss' },
    attachments: [{ name: 'termination-letter.pdf', sizeKb: 96, summary: 'Employer letter confirming termination effective Sept 19, 2026, without cause.' }],
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'payment_deferral', account: 'Auto loan 5512-90031',
    subject: 'Hardship – medical leave',
    body: 'I am on unpaid medical leave until March. Can my car loan payments (loan 5512-90031) be reduced or paused for three months?',
    fields: { loan_number: '5512-90031', months: '3', reason: 'Medical leave' },
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'payment_deferral', account: 'Line of credit 6620-11407',
    subject: 'Skip a payment?',
    body: 'Is there any way to skip the October payment on my line of credit 6620-11407? Business has been slow this quarter.',
    fields: { loan_number: '6620-11407', months: '1', reason: 'Reduced business income' },
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'payoff_statement', account: 'Mortgage 7700-28810',
    subject: 'Payoff statement – 14 Elm Crescent',
    body: 'We act for the vendor in the sale of 14 Elm Crescent. Please provide a mortgage payoff statement for loan 7700-28810 good through November 15, 2026.\n\nOkonjo & Pratt LLP',
    fields: { loan_number: '7700-28810', payoff_date: '2026-11-15' },
    attachments: [{ name: 'borrower-authorization.pdf', sizeKb: 140, summary: 'Signed authorization from both borrowers allowing release of payoff details to Okonjo & Pratt LLP.' }],
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'payoff_statement', account: 'Auto loan 5512-77310',
    subject: 'Payoff amount for my car loan',
    body: 'I am selling my car and need the payoff amount for loan 5512-77310 as of October 31.',
    fields: { loan_number: '5512-77310', payoff_date: '2026-10-31' },
  },
  {
    workflowId: 'wf_lending_inbox', intentId: 'address_change', account: 'Mortgage 7700-30017',
    subject: 'Updated mailing address',
    body: 'We have moved. Please update the mailing address on our mortgage to 2 Birchwood Lane, Oakville ON L6J 4Z9.',
    fields: { new_address: '2 Birchwood Lane, Oakville ON L6J 4Z9' },
  },
];

const NAMES = ['Hartley Brooks', 'Amira Nasser', 'Colin Fraser', 'Leila Haddad', 'Owen Mercer', 'Rosa Delgado', 'Tamsin Clarke', 'Victor Lam', 'Nadia Petrov', 'Elliot Grant', 'Imogen Shaw', 'Felix Moreau', 'June Park', 'Samuel Ofori', 'Bea Lindgren', 'Ravi Menon'];

const TOOL_INPUT: Record<string, (t: Template) => object> = {
  get_transactions: (t) => ({ card: `•• ${t.fields.card_last4}`, from: t.fields.transaction_date ?? '2026-09-01', merchant: t.fields.merchant }),
  issue_provisional_credit: (t) => ({ card: `•• ${t.fields.card_last4}`, amount: t.amount, reasonCode: '12.6' }),
  place_card_block: (t) => ({ card: `•• ${t.fields.card_last4}`, reason: 'lost_or_stolen', reissue: true }),
  waive_fee: (t) => ({ account: t.account, feeType: t.fields.fee_type, amount: t.amount }),
  update_address: (t) => ({ account: t.account, address: t.fields.new_address }),
  get_loan_account: (t) => ({ loan: t.fields.loan_number }),
  apply_payment_deferral: (t) => ({ loan: t.fields.loan_number, months: Number(t.fields.months ?? 1), interestCapitalised: true }),
  send_payoff_statement: (t) => ({ loan: t.fields.loan_number, goodThrough: t.fields.payoff_date }),
};

const money = (n?: number) => `$${(n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** What approving does, for actions that move money or change core banking. Other actions have none. */
const CONSEQUENCE: Record<string, (t: Template) => string> = {
  issue_provisional_credit: (t) => `Posts a provisional credit of ${money(t.amount)} to ${t.account} now and opens a chargeback with ${t.fields.merchant}.`,
  waive_fee: (t) => `Reverses the ${(t.fields.fee_type ?? 'fee').toLowerCase()} of ${money(t.amount)} on ${t.account} now.`,
  apply_payment_deferral: (t) => {
    const m = Number(t.fields.months ?? 1);
    return `Defers ${m} ${m === 1 ? 'payment' : 'payments'} on ${t.account} now. Interest keeps accruing and is added to the loan balance.`;
  },
  place_card_block: (t) => `Blocks ${t.account} now and orders a replacement card. The customer cannot use the card from this point.`,
  update_address: (t) => `Changes the address on ${t.account} in core banking to ${t.fields.new_address}.`,
};

const ACTION_LABEL: Record<string, string> = {
  get_transactions: 'Look up the transactions',
  issue_provisional_credit: 'Issue provisional credit',
  place_card_block: 'Block the card and reissue',
  waive_fee: 'Waive the fee',
  update_address: 'Update the address',
  get_loan_account: 'Look up the loan',
  apply_payment_deferral: 'Apply payment deferral',
  send_payoff_statement: 'Send the payoff statement',
  send_reply: 'Reply to the customer',
};

const REPLY: Record<string, string> = {
  dispute_charge: 'Thank you for letting us know. We have opened a dispute and placed a provisional credit on your account while we investigate. We will write again within 10 business days.',
  lost_stolen: 'Your card has been blocked and a replacement is on its way to the address on file. It should arrive within 5 business days.',
  fee_refund: 'We have reviewed your account and refunded the fee. It will appear on your next statement.',
  address_change: 'We have updated your address. Statements and cards will be sent to the new address from now on.',
  payment_deferral: 'We have reviewed your request and can defer your payments. Interest continues to accrue during the deferral and is added to your loan balance, and your regular payments resume the month after it ends. Reply to this email if you have any questions.',
  payoff_statement: 'Please find the payoff statement attached. The figure is valid through the date shown.',
};

/** Simple deterministic generator so the seed is stable across reloads. */
function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) % 2147483648;
    return s / 2147483648;
  };
}

export function seedCases(me: string, workflowName: (id: string) => string): CaseDetail[] {
  const r = rng(42);
  const out: CaseDetail[] = [];
  const statuses: CaseStatus[] = ['new', 'new', 'in_progress', 'waiting_approval', 'waiting_approval', 'waiting_approval', 'waiting_customer', 'in_progress', 'closed', 'closed'];
  for (let i = 0; i < 36; i++) {
    const t = T[i % T.length];
    const cfg = EMAIL_CONFIGS[t.workflowId];
    const intent = cfg.intents.find((x) => x.id === t.intentId)!;
    const route = cfg.routes.find((x) => x.intentId === t.intentId)!;
    const status = statuses[Math.floor(r() * statuses.length)];
    const name = NAMES[i % NAMES.length];
    const email = `${name.toLowerCase().replace(/[^a-z]+/g, '.')}@example.com`;
    // Spread receipt times; every fifth open case is old enough to have breached its SLA.
    const breach = status !== 'closed' && i % 5 === 1;
    const minutesAgo = breach ? route.slaHours * 60 + 30 + Math.floor(r() * 300) : Math.floor(r() * route.slaHours * 50);
    const receivedAt = ago(minutesAgo);
    const slaDueAt = new Date(new Date(receivedAt).getTime() + route.slaHours * 3_600_000).toISOString();
    const assignee = status === 'new' ? null : [me, 'Maya Okafor', 'Anika Singh', 'Daniel Brooks'][i % 4];
    const confidence = 0.74 + r() * 0.24;
    const id = `CASE-${4100 + i}`;

    const messages: CaseMessage[] = [
      { id: `${id}-m1`, direction: 'inbound', from: `${name} <${email}>`, to: MAILBOXES[t.workflowId], at: receivedAt, subject: t.subject, body: t.body, attachments: (t.attachments ?? []).map((a) => ({ fileId: '', name: a.name, size: a.sizeKb * 1024, mime: '', scan: a.infected ? 'infected' : 'clean', summary: a.summary })) },
    ];

    const actions: CaseAction[] = intent.actions.map((tool, k) => {
      const rule = cfg.approvals.find((a) => a.action === tool);
      const needsApproval = !!rule && !(rule.autoApproveBelow != null && (t.amount ?? 0) < rule.autoApproveBelow);
      const input = tool === 'send_reply' ? `Hi ${name.split(' ')[0]},\n\n${REPLY[t.intentId]}\n\nNorthfield Bank` : JSON.stringify(TOOL_INPUT[tool]?.(t) ?? {}, null, 2);
      let actionStatus: CaseAction['status'] = 'drafted';
      let approvals: CaseAction['approvals'] = [];
      let result: string | undefined;
      if (status === 'closed' || status === 'waiting_customer' || (!needsApproval && status !== 'new')) {
        actionStatus = 'executed';
        approvals = needsApproval ? [{ by: rule!.fourEyes ? 'Maya Okafor' : (assignee ?? me), at: ago(minutesAgo - 20) }] : [];
        if (needsApproval && rule!.fourEyes) approvals.push({ by: 'Daniel Brooks', at: ago(minutesAgo - 25) });
        result = tool === 'send_reply' ? 'Sent' : tool.startsWith('get_') ? 'Returned 1 matching record' : 'Completed';
      } else if (status === 'waiting_approval' && needsApproval && rule!.fourEyes && i % 2 === 0) {
        actionStatus = 'awaiting_second';
        approvals = [{ by: 'Maya Okafor', at: ago(Math.max(minutesAgo - 30, 5)) }];
      } else if (!needsApproval && status === 'new') {
        actionStatus = tool.startsWith('get_') ? 'executed' : 'drafted';
        result = tool.startsWith('get_') ? 'Returned 1 matching record' : undefined;
      }
      return {
        id: `${id}-a${k + 1}`,
        kind: tool === 'send_reply' ? 'reply' : 'tool',
        label: ACTION_LABEL[tool] ?? tool,
        tool,
        input,
        evidence: [`Extracted from the email: ${Object.values(t.fields).slice(0, 2).join(', ')}`, ...(t.attachments ?? []).filter((a) => !a.infected).map((a) => `Attachment ${a.name}: ${a.summary}`)],
        needsApproval,
        approverGroup: rule?.approverGroup,
        fourEyes: !!rule?.fourEyes && needsApproval,
        approvals,
        status: actionStatus,
        result,
        consequence: needsApproval ? CONSEQUENCE[tool]?.(t) : undefined,
      };
    });

    if (actions.some((a) => a.status === 'executed' && a.tool === 'send_reply')) {
      messages.push({ id: `${id}-m2`, direction: 'outbound', from: MAILBOXES[t.workflowId], to: email, at: ago(Math.max(minutesAgo - 40, 2)), subject: `Re: ${t.subject}`, body: actions.find((a) => a.tool === 'send_reply')!.input, attachments: [] });
    }

    const events: CaseEvent[] = [
      { at: receivedAt, kind: 'received', text: `Email received in ${MAILBOXES[t.workflowId]}`, by: 'Mailbox intake' },
      { at: receivedAt, kind: 'classified', text: `Classified as ${intent.name} (${Math.round(confidence * 100)}%)`, by: 'Email intake agent' },
      { at: receivedAt, kind: 'routed', text: `Routed to ${route.queue}, SLA ${route.slaHours} h`, by: 'Routing' },
      { at: receivedAt, kind: 'drafted', text: `Drafted ${actions.length} action${actions.length === 1 ? '' : 's'}`, by: 'Email intake agent' },
      ...(assignee ? [{ at: ago(Math.max(minutesAgo - 10, 1)), kind: 'assigned' as const, text: `Assigned to ${assignee}`, by: assignee }] : []),
      ...actions.flatMap((a): CaseEvent[] => [
        ...a.approvals.map((ap): CaseEvent => ({ at: ap.at, kind: 'approved', text: `${a.label} approved`, by: ap.by })),
        ...(a.status === 'executed' && a.result ? [{ at: ago(Math.max(minutesAgo - 26, 1)), kind: 'executed' as const, text: `${a.label}: ${a.result}`, by: 'Workflow runtime' }] : []),
      ]),
      ...(status === 'closed' ? [{ at: ago(Math.max(minutesAgo - 45, 1)), kind: 'closed' as const, text: 'Case closed: resolved', by: assignee ?? me }] : []),
    ];

    out.push({
      id,
      subject: t.subject,
      requester: name,
      requesterEmail: email,
      account: t.account,
      workflowId: t.workflowId,
      workflowName: workflowName(t.workflowId),
      mailbox: MAILBOXES[t.workflowId],
      intentId: intent.id,
      intentName: intent.name,
      confidence,
      queue: route.queue,
      priority: route.priority,
      status,
      assignee,
      receivedAt,
      slaDueAt,
      slaMinutes: null,
      pendingApprovals: 0,
      awaitingMe: 0,
      fields: intent.fields.map((f) => ({ key: f.key, label: f.label, value: t.fields[f.key] ?? null, edited: false })),
      messages,
      actions,
      events,
    });
  }
  return out;
}
