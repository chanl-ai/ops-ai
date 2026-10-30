// The workflows and email parts uc-226's api and ui scripts share (docs/usecases/agents-service/every-shape-of-email.md):
// a child that reads one document, the mailbox workflow that switches on what an email holds, and the notices sent.
import { FILES_PORT } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const json = async (r) => (await r.json()).data;
export const LEVY = { id: 'levy_notice', version: 1 };

const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, parameters });
const wire = (pairs) => pairs.map(([from, port, to]) => ({ from: { node: from, port }, to: { node: to, port: 'in' } }));
const read = (id, file) => node(id, 'ops.ai.extract', { file, documentType: LEVY });

/** One document, read: the child each attachment starts. */
export const READ_ONE = {
  schemaVersion: 2,
  id: 'uc226_read_one',
  name: 'Read one document',
  nodes: [node('start', 'ops.trigger.request', { inputSchema: { type: 'object', properties: { fileId: { type: 'string', format: 'file' } } } }), read('read', '$.input.fileId'), node('done', 'ops.flow.end', { outcome: 'read', output: '$.nodes.read.out.records.0.values' }), node('not_read', 'ops.flow.end', { outcome: 'not_read' })],
  connections: wire([['start', 'payload', 'read'], ['read', 'ok', 'done'], ['read', 'review', 'not_read'], ['read', 'unreadable', 'not_read'], ['read', 'error', 'not_read']]),
};

/** What came in decides the way: one attachment with text, several attachments, text only, or nothing readable. */
export const MAIL = {
  schemaVersion: 2,
  id: 'uc226_mail',
  name: 'Every shape of email',
  nodes: [
    // A step that reads a file names the trigger's file fields, so the start form offers files, not ids.
    node('start', 'ops.trigger.request', {
      inputSchema: {
        type: 'object',
        properties: {
          attachments: { type: 'array', items: { type: 'object', properties: { fileId: { type: 'string' }, name: { type: 'string' } } } },
          bodyFile: { type: 'object', properties: { fileId: { type: 'string' }, name: { type: 'string' } } },
        },
      },
    }),
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

/** A text file in Files, as the trigger stores an email's text or a person uploads an attachment. */
export async function upload(headers, name, text, purpose) {
  const bytes = Buffer.from(text, 'utf8');
  const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'text/plain', purpose }) }));
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'text/plain' }, body: bytes });
  const done = await json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers }));
  return { fileId: done.file.id, name, mime: 'text/plain', size: bytes.length };
}

export const notice = (marker, name, address, ssn, amount, court, caseNo) =>
  `${marker}\nNotice of garnishment\nJudgment debtor: ${name}\nAddress: ${address}\nSSN: ***-**-${ssn}\nAmount: ${amount}\nCourt: ${court}\nCase: ${caseNo}\n`;
export const MARCUS = ['Marcus Bell', '12 Harbour Street, Halifax NS B3J 1A1', '4471', '3,250.00', 'Nova Scotia Supreme Court'];
export const PRIYA = ['Priya Natarajan', '88 Lakeshore Road, Toronto ON M8V 1A5', '9032', '12,400.00', 'Ontario Superior Court of Justice'];

