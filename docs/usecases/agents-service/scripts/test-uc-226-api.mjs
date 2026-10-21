// uc-226 a mailbox workflow takes every shape of email, api layer: docs/usecases/agents-service/every-shape-of-email.md
// (c-259). The demo stack with platform sign-in, documents-service, the fake model and a worker. James publishes a
// workflow that switches on what came in and starts it with three emails as the Email received trigger hands them on:
// text only, two attachments, and a text that disagrees with its attachment.
import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, check, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const LEVY = { id: 'levy_notice', version: 1 };

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 120_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, parameters });
const wire = (pairs) => pairs.map(([from, port, to]) => ({ from: { node: from, port }, to: { node: to, port: 'in' } }));
const read = (id, file) => node(id, 'ops.ai.extract', { file, documentType: LEVY });

/** One document, read: the child each attachment starts. */
const READ_ONE = {
  schemaVersion: 2,
  id: 'uc226_read_one',
  name: 'Read one document',
  nodes: [node('start', 'ops.trigger.request'), read('read', '$.input.fileId'), node('done', 'ops.flow.end', { outcome: 'read', output: '$.nodes.read.out.records.0.values' }), node('not_read', 'ops.flow.end', { outcome: 'not_read' })],
  connections: wire([['start', 'payload', 'read'], ['read', 'ok', 'done'], ['read', 'review', 'not_read'], ['read', 'unreadable', 'not_read'], ['read', 'error', 'not_read']]),
};

/** What came in decides the way: one attachment with text, several attachments, text only, or nothing readable. */
const MAIL = {
  schemaVersion: 2,
  id: 'uc226_mail',
  name: 'Every shape of email',
  nodes: [
    node('start', 'ops.trigger.request'),
    node('what', 'ops.flow.switch', {
      cases: [
        { name: 'one_and_text', conditions: [{ left: '$.input.attachments', op: 'ne', right: [] }, { left: '$.input.attachments.1', op: 'empty' }, { left: '$.input.bodyFile', op: 'exists' }] },
        { name: 'attachments', conditions: [{ left: '$.input.attachments', op: 'ne', right: [] }] },
        { name: 'text_only', conditions: [{ left: '$.input.bodyFile', op: 'exists' }] },
      ],
    }),
    read('read_attachment', '$.input.attachments.0.fileId'),
    read('read_text', '$.input.bodyFile.fileId'),
    node('combine', 'ops.data.combine', { sources: [{ name: 'attachment', values: '$.nodes.read_attachment.out.records.0.values' }, { name: 'email', values: '$.nodes.read_text.out.records.0.values' }] }),
    node('disagree', 'ops.flow.if', { conditions: [{ left: '$.nodes.combine.out.hasConflicts', op: 'eq', right: true }] }),
    node('check', 'ops.flow.humanReview', { title: 'The email and its attachment disagree', summary: { conflicts: '$.nodes.combine.out.conflicts' }, editable: '$.nodes.combine.out.values' }),
    node('each', 'ops.action.workflow', { workflow: 'uc226_read_one', forEach: '$.input.attachments', input: { fileId: '$.item.fileId' } }),
    read('read_text_only', '$.input.bodyFile.fileId'),
    node('combined', 'ops.flow.end', { outcome: 'combined', output: '$.nodes.combine.out.values' }),
    node('checked', 'ops.flow.end', { outcome: 'checked', output: '$.nodes.check.out.edited' }),
    node('dispatched', 'ops.flow.end', { outcome: 'dispatched', output: '$.nodes.each.out' }),
    node('text_read', 'ops.flow.end', { outcome: 'text_read', output: '$.nodes.read_text_only.out.records.0.values' }),
    node('unreadable', 'ops.flow.end', { outcome: 'unreadable' }),
    node('not_read', 'ops.flow.end', { outcome: 'not_read' }),
  ],
  connections: wire([
    ['start', 'payload', 'what'],
    ['what', 'one_and_text', 'read_attachment'], ['what', 'attachments', 'each'], ['what', 'text_only', 'read_text_only'], ['what', 'otherwise', 'unreadable'],
    ['read_attachment', 'ok', 'read_text'], ['read_attachment', 'review', 'not_read'], ['read_attachment', 'unreadable', 'not_read'], ['read_attachment', 'error', 'not_read'],
    ['read_text', 'ok', 'combine'], ['read_text', 'review', 'not_read'], ['read_text', 'unreadable', 'not_read'], ['read_text', 'error', 'not_read'],
    ['combine', 'out', 'disagree'], ['disagree', 'true', 'check'], ['disagree', 'false', 'combined'],
    ['check', 'approve', 'checked'], ['check', 'reject', 'not_read'],
    ['each', 'started', 'dispatched'], ['each', 'error', 'not_read'],
    ['read_text_only', 'ok', 'text_read'], ['read_text_only', 'review', 'not_read'], ['read_text_only', 'unreadable', 'not_read'], ['read_text_only', 'error', 'not_read'],
  ]),
};

async function publish(headers, definition) {
  const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers, body: JSON.stringify({ definition }) });
  const live = await fetch(`${agents}/v1/workflows/definitions/${definition.id}/publish-requests`, { method: 'POST', headers, body: '{}' });
  return `${saved.status}/${live.status}/${(await live.json().catch(() => ({})))?.data?.status ?? ''}`;
}

/** A text file in Files, as the trigger stores an email's text or a person uploads an attachment. */
async function upload(headers, name, text, purpose) {
  const bytes = Buffer.from(text, 'utf8');
  const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'text/plain', purpose }) }));
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'text/plain' }, body: bytes });
  const done = await json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers }));
  return { fileId: done.file.id, name, mime: 'text/plain', size: bytes.length };
}

const notice = (marker, name, address, ssn, amount, court, caseNo) =>
  `${marker}\nNotice of garnishment\nJudgment debtor: ${name}\nAddress: ${address}\nSSN: ***-**-${ssn}\nAmount: ${amount}\nCourt: ${court}\nCase: ${caseNo}\n`;
const MARCUS = ['Marcus Bell', '12 Harbour Street, Halifax NS B3J 1A1', '4471', '3,250.00', 'Nova Scotia Supreme Court'];
const PRIYA = ['Priya Natarajan', '88 Lakeshore Road, Toronto ON M8V 1A5', '9032', '12,400.00', 'Ontario Superior Court of Justice'];

const start = async (headers, input) => (await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers, body: JSON.stringify({ workflowId: 'uc226_mail', mode: 'live', input }) }))).runId;
const run = async (headers, id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers }));
const ended = (headers, id) => until(async () => { const r = await run(headers, id); return ['succeeded', 'failed', 'waiting'].includes(r?.status) ? r : null; });
const wayOf = (r) => (r?.steps ?? []).find((s) => s.nodeId === 'what')?.port;

await withUiStack(
  async (_consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    const james = as(await tokenFor(JAMES));
    const published = [await publish(james, READ_ONE), await publish(james, MAIL)];
    check('1 setup: both workflows are published with Switch and Combine facts in them', published.every((p) => p.startsWith('201/201')), published);

    // A body-only email: the trigger's text file is the one thing to read.
    const text = await upload(james, 'email-body.txt', notice('UC226 BODY ONLY', ...MARCUS, 'NS-2026-GN-01187'), 'email_body');
    const only = await ended(james, await start(james, { attachments: [], bodyFile: text }));
    check('2 an email with no attachment is read from its text file', wayOf(only) === 'text_only' && only?.outcome === 'text_read' && only?.output?.case_no === 'NS-2026-GN-01187', { way: wayOf(only), outcome: only?.outcome, output: only?.output, error: only?.error });

    // Two attachments: one child run reads each.
    const a = await upload(james, 'notice-a.txt', notice('UC226 ATTACHMENT A', ...MARCUS, 'NS-2026-GN-01187'), 'case_attachment');
    const b = await upload(james, 'notice-b.txt', notice('UC226 ATTACHMENT B', ...PRIYA, 'ON-2026-GN-04421'), 'case_attachment');
    const two = await ended(james, await start(james, { attachments: [a, b], bodyFile: null }));
    const childIds = (two?.output?.runs ?? []).map((r) => r.runId);
    const children = await Promise.all(childIds.map((id) => ended(james, id)));
    const names = children.map((c) => c?.output?.name).sort();
    check('3 an email with two attachments reads each in its own run', wayOf(two) === 'attachments' && two?.outcome === 'dispatched' && children.length === 2 && children.every((c) => c?.outcome === 'read') && names.join('|') === 'Marcus Bell|Priya Natarajan', { way: wayOf(two), outcome: two?.outcome, names, children: children.map((c) => [c?.status, c?.outcome, c?.error]) });

    // The text names another case number than its attachment: the run stops for a person with both values.
    const c = await upload(james, 'notice-c.txt', notice('UC226 ATTACHMENT C', ...MARCUS, 'NS-2026-GN-01187'), 'case_attachment');
    const t = await upload(james, 'email-body.txt', notice('UC226 BODY CONFLICT', ...MARCUS, 'NS-2026-GN-01188'), 'email_body');
    const both = await ended(james, await start(james, { attachments: [c], bodyFile: t }));
    const combine = (both?.steps ?? []).find((s) => s.nodeId === 'combine')?.output ?? {};
    const conflict = (combine.conflicts ?? []).map((x) => [x.field, x.values.map((v) => `${v.source}:${v.value}`).join(',')]);
    check('4 a text and an attachment that disagree stop at the read check with both values', wayOf(both) === 'one_and_text' && both?.status === 'waiting' && both?.waiting?.node === 'check' && JSON.stringify(conflict) === JSON.stringify([['case_no', 'attachment:NS-2026-GN-01187,email:NS-2026-GN-01188']]), { way: wayOf(both), status: both?.status, at: both?.waiting?.node, conflict, error: both?.error });

    // Nothing readable takes the otherwise way.
    const none = await ended(james, await start(james, { attachments: [], bodyFile: null }));
    check('5 an email with nothing to read takes the otherwise way', wayOf(none) === 'otherwise' && none?.outcome === 'unreadable', { way: wayOf(none), outcome: none?.outcome });
  },
  { platform: true, demo: true },
);
finish();
