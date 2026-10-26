import { plural } from '@/lib/format';
import type { ActionField, DocumentRead, Review, TaskAction, TypedTask } from '@/lib/types/domain';
import type { KindNode } from '@/lib/types/widgets';

/**
 * A Human Task as the page draws it (design: the Human Task redesign, version 2):
 * one question, the evidence for it, what to decide on, and everything else under Details. Built from today's review
 * data here, and nowhere else, so c-288's task types replace this one function. No engine words (gates, run ids, event
 * names, raw calls) reach `question`, `evidence`, `decide` or `consequence`; they live in `details`.
 */
export interface TaskView {
  question: string;
  /** Shown beside the decision (a document, an email): two panes from 1024px when present. */
  evidence: KindNode[];
  /** What the person decides on or corrects. */
  decide: KindNode[];
  /** Folded by default. */
  details: KindNode[];
  /** Engine detail (task type, step, policy, run, its event log): folded again inside Details. */
  technical?: KindNode[];
  /** The main action's effect, said once in the footer. */
  consequence: string;
  /** A review whose type has no regions yet draws today's body inside the page instead. */
  legacy: boolean;
  /** A typed task's actions, in its type's order; absent for a review the page decides with today's forms. */
  actions?: TaskAction[];
  /** The action the AI assist suggests, by name: marked on its button, never chosen for the person. */
  suggested?: string;
  /** A typed read check's values, for the key-field confirmations its Approve waits for. */
  read?: DocumentRead;
}

type Data = Record<string, unknown>;
type EmailNode = Extract<KindNode, { type: 'email' }>;
const text = (v: unknown) => (typeof v === 'string' ? v : '');
const pairsOf = (v: unknown) =>
  (Array.isArray(v) ? v : [])
    .filter((x): x is Data => !!x && typeof x === 'object')
    .map((x) => ({ label: text(x.label) || text(x.name), value: typeof x.value === 'number' ? x.value : text(x.value) || String(x.value ?? '') }))
    .filter((x) => x.label);
const factOf = (facts: { label: string; value: string | number }[], label: string) => String(facts.find((f) => f.label.toLowerCase() === label.toLowerCase())?.value ?? '');
const attachmentsOf = (v: unknown): EmailNode['attachments'] =>
  (Array.isArray(v) ? v : [])
    .filter((x): x is Data => !!x && typeof x === 'object')
    .map((x) => ({
      name: text(x.name) || text(x.fileName),
      fileId: text(x.fileId) || text(x.id) || undefined,
      type: text(x.type) || text(x.mime) || undefined,
      size: typeof x.size === 'number' ? x.size : undefined,
    }))
    .filter((a) => a.name);
const emailOf = (e: Omit<EmailNode, 'type'>): EmailNode => ({ type: 'email', ...e });

/** A typed read check's fields (as the Extract step gives them) as the read the field check draws. */
function readOf(fileId: string, fields: unknown, name: string | undefined): DocumentRead | undefined {
  const list = (Array.isArray(fields) ? fields : []).filter((x): x is Data => !!x && typeof x === 'object' && typeof x.key === 'string');
  if (!list.length) return undefined;
  return {
    fileId,
    fileName: name ?? null,
    floor: null,
    editable: false,
    corrected: null,
    schema: list.map((f) => ({ key: String(f.key), label: text(f.label) || String(f.key), type: text(f.type) || 'text', required: !!f.required, keyField: f.keyField === true })),
    records: [
      {
        values: Object.fromEntries(list.map((f) => [String(f.key), f.value])),
        fields: Object.fromEntries(
          list.map((f) => [
            String(f.key),
            {
              value: f.value,
              extractedValue: f.extractedValue ?? f.value,
              confidence: typeof f.confidence === 'number' ? f.confidence : null,
              needsReview: !!f.needsReview,
              citation: (f.citation as DocumentRead['records'][number]['fields'][string]['citation']) ?? null,
              boxes: Array.isArray(f.boxes) ? (f.boxes as { page: number; x: number; y: number; w: number; h: number }[]) : undefined,
            },
          ]),
        ),
      },
    ],
  };
}

/**
 * A typed task as the page's regions (c-288): the server bound each region from the task's params, so this only
 * chooses the kind that draws it. The question is the header's; a document or a received email is the evidence, and a
 * message joins it when there is one; why it waits, facts, the write and the form are what the person decides on;
 * history and the engine's own facts fold under Details.
 */
function typedView(r: Review, task: TypedTask, details: KindNode[]): TaskView {
  const regions = Object.fromEntries(task.regions.map((x) => [x.region, x.data])) as Record<string, Data | undefined>;
  const evidence: KindNode[] = [];
  const decide: KindNode[] = [];
  const facts = pairsOf(regions.facts?.facts);
  const doc = regions.document;
  const fileId = text(doc?.file) || r.read?.fileId || '';
  const regionBoxes = Array.isArray(doc?.boxes) ? (doc!.boxes as Extract<KindNode, { type: 'viewer' }>['boxes']) : [];
  if (fileId) evidence.push({ type: 'viewer', fileId, boxes: regionBoxes?.length || !r.read ? regionBoxes : boxesOf(r.read) });
  const received = doc?.received as Data | undefined;
  if (received)
    evidence.push(
      emailOf({
        label: 'Received',
        from: text(received.from),
        to: text(received.to) || factOf(facts, 'From'),
        subject: text(received.subject),
        date: text(received.date) || text(received.receivedAt) || text(received.at),
        body: text(received.body) || text(received.text) || text(received.summary),
        html: text(received.html) || undefined,
        attachments: attachmentsOf(received.attachments),
      }),
    );
  const message = text(regions.message?.text);
  const reply = r.reply;
  if (reply || (message && (evidence.length || received))) {
    (evidence.length ? evidence : decide).push(
      emailOf({
        label: 'The reply',
        from: reply?.mailbox || factOf(facts, 'From'),
        to: reply?.to || factOf(facts, 'To') || text(received?.from),
        subject: reply?.subject || (text(received?.subject) ? `Re: ${text(received?.subject)}` : ''),
        body: reply?.body || message,
      }),
    );
  } else if (message) {
    (evidence.length ? evidence : decide).push({ type: 'document', name: 'Why it was asked', passage: message });
  }
  // The AI assist (c-302) comes first when the team has it on, labelled as AI so nobody reads it as the record.
  const assist = regions.assist;
  if (assist?.pending)
    decide.push({ type: 'entity', title: 'AI assist', category: 'AI', subtitle: 'Writing a summary and a suggestion…', fields: [] });
  else if (assist) {
    const formFields = (Array.isArray(regions.form?.fields) ? regions.form!.fields : []) as Data[];
    const labelOf = (key: string) => text(formFields.find((f) => f.key === key)?.label) || key;
    const doubtful = Array.isArray(assist.doubtful) ? (assist.doubtful as string[]).map(labelOf) : [];
    const suggestion = assist.suggestion as Data | null | undefined;
    const actionLabel = suggestion ? task.actions.find((a) => a.name === text(suggestion.action))?.label : undefined;
    decide.push({
      type: 'entity',
      title: 'AI assist',
      category: 'AI',
      subtitle: text(assist.question) || undefined,
      fields: [
        { label: 'Summary', value: text(assist.summary) },
        { label: 'Worth checking', value: doubtful.join(', ') },
        { label: 'Suggests', value: actionLabel ? `${actionLabel}${text(suggestion?.reason) ? ` · ${text(suggestion?.reason)}` : ''}` : '' },
      ].filter((f) => f.value),
    });
  }
  const why = regions.why_source;
  const whyFields = [
    { label: 'Why it waits', value: text(why?.why) },
    { label: 'Where it came from', value: text(why?.source) },
  ].filter((x) => x.value);
  if (whyFields.length) decide.push({ type: 'entity', title: 'Why it is here', fields: whyFields });
  // The question already says some values ("Hold 2,000.00 on account CHQ-2219?"); the card adds what it does not say.
  const question = text(regions.header?.title) || r.question || r.title || '';
  const inQuestion = (v: unknown) => String(v ?? '').length > 2 && question.toLowerCase().includes(String(v).toLowerCase());
  const emailShown = [...evidence, ...decide].some((n) => n.type === 'email');
  const unsaid = facts.filter((f) => !inQuestion(f.value) && !(emailShown && /^(from|to|subject)$/i.test(f.label)));
  if (unsaid.length) decide.push({ type: 'entity', title: task.type.name, fields: unsaid });
  // The write's fields as the operation labels them, worded by the API (write_preview.fields, c-508).
  const described = Array.isArray(regions.write_preview?.fields) ? (regions.write_preview!.fields as Data[]) : [];
  if (described.length) {
    // A value the facts or the question already show (account, amount, reason) is said once: matched by its label, or
    // by its value with number formatting set aside (2000 is the facts' 2,000.00).
    const plainNumber = (v: unknown) => String(v ?? '').replace(/,/g, '').replace(/\.0+$/, '');
    const saidLabels = new Set(facts.map((f) => f.label.toLowerCase()));
    const saidValues = new Set(facts.map((f) => plainNumber(f.value)));
    const changes = described
      .map((f) => ({ label: text(f.label), value: text(f.value) }))
      .filter((f) => f.label && !saidLabels.has(f.label.toLowerCase()) && !saidValues.has(plainNumber(f.value)) && !inQuestion(f.value));
    if (changes.length) decide.push({ type: 'confirm', title: 'What it changes', details: changes, confirm: { label: 'Approve', reply: '' }, actionsOff: true });
  }
  // The review's own read, when the server still sends it, carries what correcting and confirming need (records,
  // corrections, key fields); the form region's copy is the fallback.
  const read = r.read ?? (regions.form ? readOf(fileId, regions.form.fields, undefined) : undefined);
  if (read) decide.push({ type: 'field_check', read });
  // The cases the run and its child runs opened (the type's `cases` region, else the reply preview): one row per case,
  // by its subject, opening its case.
  const regionCases = Array.isArray(regions.cases?.cases) ? (regions.cases!.cases as Data[]).map((c) => ({ caseId: text(c.caseId) || null, subject: text(c.subject) || null })) : [];
  const cases = regionCases.length ? regionCases : (r.reply?.cases ?? []);
  if (cases.length)
    decide.push({ type: 'entity', title: 'Cases this covers', fields: cases.map((c) => ({ label: c.subject || 'Opening', value: c.caseId ? 'Open case' : 'Opening', href: c.caseId ? `/cases/${encodeURIComponent(c.caseId)}` : undefined })) });
  const history = (Array.isArray(regions.history?.events) ? regions.history!.events : []) as Data[];
  const historyNodes: KindNode[] = history.length
    ? [{ type: 'timeline', title: 'What happened before', events: history.map((e) => ({ at: text(e.at), title: text(e.title) || text(e.text) || text(e.label), detail: text(e.detail) || undefined })) }]
    : [];
  return {
    // A read is asked by what it holds ("Check 2 key fields read from TEST012.pdf"), the same words on its list row.
    question: (read && readQuestion(read)) || text(regions.header?.title) || r.question || r.title,
    evidence,
    decide,
    details: [...historyNodes, ...details],
    consequence: '',
    legacy: false,
    actions: task.actions,
    suggested: assist?.suggestion ? text((assist.suggestion as Data).action) || undefined : undefined,
    read,
  };
}

const pairs = (rows: [string, string | number | null | undefined][]) => rows.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([label, value]) => ({ label, value: value as string | number }));

/**
 * Where the review came from and how it is governed. What a person reads (the workflow, who decides, the deadline) is
 * Details; what the engine knows it by (task type, step, policy, run, its event log) is folded again under it.
 */
function detailsOf(r: Review): { details: KindNode[]; technical: KindNode[] } {
  // Who decides is the deciding team the header names, so the page says it one way; the policy's role name is engine detail.
  const decider = r.decidingTeam ? (r.decidingTeam.name ?? r.decidingTeam.id) : r.policy?.reviewers;
  // "8h (workspace)" is where the deadline is set; said in words.
  const deadline = r.policy?.sla?.replace(/\s*\((workspace|team)\)$/, (_m, scope: string) => `, the ${scope === 'team' ? "team's" : 'workspace'} default`);
  const facts = pairs([
    ['Workflow', r.workflowName],
    ['Decided by', decider],
    ['Deadline', deadline],
    ['If no one decides', r.policy?.onTimeout],
    ['Case', r.caseId ?? undefined],
  ]);
  const engine = pairs([
    // Which form a person decided on, and which version of it.
    ['Task type', r.task ? `${r.task.type.name} · v${r.task.type.version}` : undefined],
    ['Step', r.stepName ?? undefined],
    ['Policy', r.policy?.name],
    ['Run', r.runId ?? undefined],
  ]);
  const details: KindNode[] = facts.length ? [{ type: 'entity', title: 'Where it came from', fields: facts }] : [];
  const technical: KindNode[] = engine.length ? [{ type: 'entity', title: 'How the engine knows it', fields: engine }] : [];
  if (r.evidence?.length) technical.push({ type: 'timeline', title: 'What the run did', events: r.evidence.map((e) => ({ at: '', title: e.label, detail: e.detail })) });
  return { details, technical };
}

/** Where each read value sits on the page, marked when it needs a person's check. */
function boxesOf(read: DocumentRead): Extract<KindNode, { type: 'viewer' }>['boxes'] {
  return read.records.flatMap((rec) => Object.entries(rec.fields).flatMap(([key, f]) => (f.boxes ?? []).map((b) => ({ key, ...b, check: f.needsReview }))));
}

/** A read's question: its key fields when the document type marks any, else the values still in doubt, else all of them. */
function readQuestion(read: DocumentRead): string {
  const per = Math.max(1, read.records.length);
  const file = read.fileName ?? 'the file';
  const keys = read.schema.filter((f) => f.keyField).length * per;
  const doubtful = read.records.reduce((n, rec) => n + Object.values(rec.fields).filter((f) => f.needsReview && !f.corrected).length, 0);
  return keys ? `Check ${plural(keys, 'key field')} read from ${file}` : doubtful ? `Check ${plural(doubtful, 'field')} read from ${file}` : `Confirm the ${plural(read.schema.length * per, 'field')} read from ${file}`;
}

/** Today's review as the page's regions. */
export function taskView(r: Review): TaskView {
  const { details, technical } = detailsOf(r);
  return { ...regionsOf(r, details), technical };
}

function regionsOf(r: Review, details: KindNode[]): TaskView {
  if (r.task) return typedView(r, r.task, details);
  if (r.read) {
    return {
      question: readQuestion(r.read),
      evidence: r.read.fileId ? [{ type: 'viewer', fileId: r.read.fileId, name: r.read.fileName ?? 'the file', boxes: boxesOf(r.read) }] : [],
      decide: [{ type: 'field_check', read: r.read }],
      details,
      consequence: 'Approve: the workflow continues with these values. Reject: it continues without them.',
      legacy: false,
    };
  }
  if (r.reply) {
    // A case by its subject; the id is engine detail and stays under Details.
    const cases = r.reply.cases.map((c, i) => ({ label: `Case ${i + 1}`, value: c.caseId ? (c.subject ?? 'Opened') : 'Opening' }));
    return {
      question: `Send this reply to ${r.reply.to}?`,
      evidence: [
        emailOf({
          label: 'The reply',
          from: r.reply.mailbox ?? '',
          to: r.reply.to,
          subject: r.reply.subject,
          body: r.reply.body,
        }),
      ],
      decide: cases.length ? [{ type: 'entity', title: 'Cases this covers', fields: cases }] : [],
      details,
      consequence: `Approve: the reply goes to ${r.reply.to} from ${r.reply.mailbox ?? 'the workspace sender'}. Reject: nothing is sent.`,
      legacy: false,
    };
  }
  const special = r.toolModule || r.publish || r.modelValidation || r.skillPublish || r.agentPublish || r.templateSubmission;
  if (special) return { question: r.title, evidence: [], decide: [], details, consequence: '', legacy: true };
  // A held action: the document it is about and the agent's reason first; then what each choice does and sends, as
  // the server words it. The question is the server's too, so no tool name or raw value reaches the page.
  const reason = r.reasoning?.filter(Boolean) ?? [];
  const evidence: KindNode[] = [];
  if (r.sourceFile) evidence.push({ type: 'viewer', fileId: r.sourceFile });
  if (reason.length) evidence.push({ type: 'document', name: 'Why it was asked', passage: reason.join(' ') });
  const preview = (title: string, summary: string | null | undefined, fields: ActionField[] | undefined): KindNode => ({
    type: 'confirm',
    title,
    summary: summary ?? undefined,
    details: (fields ?? []).map((f) => ({ label: f.label, value: f.value })),
    confirm: { label: title, reply: '' },
    actionsOff: true,
  });
  return {
    question: r.question ?? r.title,
    evidence,
    // Who it is about is already in the page's description line; the decide pane is what each choice does.
    decide: r.options?.length ? r.options.map((o) => preview(o.label ?? o.name, o.consequence, o.fields)) : [preview('If you approve', r.consequence, r.actionFields)],
    details,
    // The server's consequence is a sentence of its own, often already ending in a full stop.
    consequence: `Approve: ${(r.consequence ?? 'the step runs with the values shown').replace(/\.+$/, '')}. Reject: nothing runs.`,
    legacy: false,
  };
}
