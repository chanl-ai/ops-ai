// Walks a deployed Ops AI through its one public origin, as a person would: sign in, make an agent, chat with it,
// upload a file, run a workflow on the worker, read a document with a document type, then open Agents, the chat and
// Files in a headless browser. Every request goes through the proxy, so a route the proxy misses fails here. Prints
// one PASS or FAIL line per check and exits 1 on any FAIL. Any install with one origin: Fly, compose (deploy/compose).
//   OPS_SMOKE_EMAIL=... OPS_SMOKE_PASSWORD=... node deploy/fly/smoke.mjs https://<your-app>.fly.dev
// OPS_SMOKE_TEAM names the team it acts in (default: the admin's first team); keep it a test team, never a team shown
// to people. At the end it removes what it made where a route allows: the agent, the workflow, the files, the chat and
// the approver it invited. The run and the document type have no delete route and stay in that team.
// Outside dev a publish waits for a second person: the walk invites one as approver (an admin's invite) to decide it.
// The agent and the document read answer on whatever model the alias is bound to: run it against a fake model unless
// real spend is intended. The read's fields match the fake's committed rules (services/models-service/seed/demo-fake-openai).
import { createRequire } from 'node:module';

const { chromium } = createRequire(new URL('../../packages/usecase-runner/package.json', import.meta.url))('playwright');

const origin = (process.argv[2] ?? '').replace(/\/$/, '');
const email = process.env.OPS_SMOKE_EMAIL;
const password = process.env.OPS_SMOKE_PASSWORD;
if (!origin || !email || !password) {
  console.error('usage: OPS_SMOKE_EMAIL=... OPS_SMOKE_PASSWORD=... node deploy/fly/smoke.mjs <origin>');
  process.exit(2);
}
const TAG = Math.random().toString(36).slice(2, 6);
let failed = 0;
const check = (name, ok, detail) => {
  if (!ok) failed += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ` ${(JSON.stringify(detail) ?? '').slice(0, 400)}`}`);
};
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

const session = await data(
  await fetch(`${origin}/api/platform/v1/auth/sign-in`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }),
);
const team = process.env.OPS_SMOKE_TEAM || session.principal.teamId;
check('the admin signs in through /api/platform', Boolean(session.token && team), session.principal);
const as = { Authorization: `Bearer ${session.token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' };

// The second person a publish waits for: invited by the admin into the admin's team as an approver, made once.
let approver;
async function secondPerson() {
  if (approver) return approver;
  const invited = await data(
    await fetch(`${origin}/api/platform/v1/settings/members/invite`, {
      method: 'POST',
      headers: as,
      body: JSON.stringify({ emails: [`smoke-approver-${TAG}@example.com`], role: 'approver' }),
    }),
  );
  const accepted = await data(
    await fetch(`${origin}/api/platform/v1/invites/${invited.invites[0].token}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: `Smoke Approver ${TAG}`, password: `smoke approver password ${TAG}` }),
    }),
  );
  approver = { ...as, Authorization: `Bearer ${accepted.token}` };
  return approver;
}
/** A publish request answered `pending` is approved by the second person; returns the request as it ends. */
async function published(request) {
  if (request?.status !== 'pending') return request;
  return data(
    await fetch(`${origin}/api/agents/v1/publish-requests/${request.id}/decision`, {
      method: 'POST',
      headers: await secondPerson(),
      body: JSON.stringify({ decision: 'approved' }),
    }),
  );
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// An agent names its model alias; the walk takes the first chat alias models-service offers, as the agent picker does.
const aliases = await data(await fetch(`${origin}/api/agents/v1/model-aliases`, { headers: as }));
const model = aliases[0]?.name ?? '';
check('agents-service lists the model aliases models-service serves', model !== '', aliases);
const agent = await data(
  await fetch(`${origin}/api/agents/v1/agents`, {
    method: 'POST',
    headers: as,
    body: JSON.stringify({ name: `Smoke ${TAG}`, role: 'Answers questions about the staging install', model }),
  }),
);
const publish = await fetch(`${origin}/api/agents/v1/agents/${agent.id}/publish-requests`, {
  method: 'POST',
  headers: as,
  body: JSON.stringify({ version: agent.version, note: 'smoke' }),
});
const request = await publish.json().catch(() => ({}));
const decided = publish.status < 300 ? await published(request.data).catch((e) => ({ error: String(e) })) : request;
check(
  'an agent is made and published through /api/agents (a second person approving when the policy asks)',
  publish.status < 300 && decided?.status !== 'pending' && !decided?.error,
  { status: publish.status, request: decided },
);

const thread = (
  await data(
    await fetch(`${origin}/api/agents/chat/threads`, {
      method: 'POST',
      headers: as,
      body: JSON.stringify({ agentId: agent.id, kbIds: [] }),
    }),
  )
).id;
const stream = await (
  await fetch(`${origin}/api/agents/chat/threads/${thread}/messages`, {
    method: 'POST',
    headers: { ...as, Accept: 'text/event-stream' },
    body: JSON.stringify({ content: `Hello from the smoke run ${TAG}` }),
  })
).text();
const messages = await data(await fetch(`${origin}/api/agents/chat/threads/${thread}`, { headers: as }));
const reply = JSON.stringify(messages).match(/"role":"assistant"[^}]*"content":"([^"]+)"/)?.[1] ?? '';
check('the agent answers a chat message on the model behind its alias', reply.length > 0, stream.slice(-400));

const bytes = new TextEncoder().encode(`smoke file ${TAG}\n`);
const ticket = await data(
  await fetch(`${origin}/api/files/v1/files/uploads`, {
    method: 'POST',
    headers: { ...as, 'Idempotency-Key': `smoke-${TAG}` },
    body: JSON.stringify({ name: `smoke-${TAG}.txt`, size: bytes.length, mime: 'text/plain', purpose: 'chat_attachment' }),
  }),
);
const put = await fetch(new URL(ticket.uploadUrl, origin), {
  method: 'PUT',
  headers: { Authorization: as.Authorization, 'X-Team-Id': team, 'Content-Type': 'text/plain', ...ticket.headers },
  body: bytes,
});
const done = await data(await fetch(`${origin}/api/files/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: as }));
check(
  'a file uploads through the URL files-service hands out, and completes clean',
  put.status < 300 && done.file?.scanStatus !== 'pending',
  { put: put.status, uploadUrl: ticket.uploadUrl, file: done.file },
);

// A workflow published and run on the workflow worker: a request trigger, a Set step and an If choosing the end.
const WORKFLOW = `smoke_${TAG}`;
const definition = `
schemaVersion: 2
id: ${WORKFLOW}
name: Smoke ${TAG}
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: fields, type: ops.data.set, typeVersion: 1, name: Set fields, parameters: {values: {amount: "$.input.amount"}}}
  - {id: big, type: ops.flow.if, typeVersion: 1, name: Over 100, parameters: {conditions: [{left: "$.nodes.fields.out.amount", op: gt, right: 100}]}}
  - {id: large, type: ops.flow.end, typeVersion: 1, name: Large, parameters: {outcome: large}}
  - {id: small, type: ops.flow.end, typeVersion: 1, name: Small, parameters: {outcome: small}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: big, port: in}}
  - {from: {node: big, port: "true"}, to: {node: large, port: in}}
  - {from: {node: big, port: "false"}, to: {node: small, port: in}}
`;
const wf = await fetch(`${origin}/api/agents/v1/workflows/definitions`, { method: 'POST', headers: as, body: JSON.stringify({ yaml: definition }) });
const wfPublish = await fetch(`${origin}/api/agents/v1/workflows/definitions/${WORKFLOW}/publish-requests`, { method: 'POST', headers: as, body: '{}' });
const wfDecided = wfPublish.status < 300 ? await published((await wfPublish.json()).data).catch((e) => ({ error: String(e) })) : await wfPublish.text();
const started = await fetch(`${origin}/api/agents/v1/runs`, {
  method: 'POST',
  headers: as,
  body: JSON.stringify({ workflowId: WORKFLOW, input: { amount: 250 }, runKey: `smoke-${TAG}` }),
});
const runId = (await started.json().catch(() => ({}))).data?.runId;
let run;
for (let i = 0; runId && i < 60; i++) {
  run = await data(await fetch(`${origin}/api/agents/v1/runs/${runId}`, { headers: as }));
  if (['succeeded', 'failed', 'cancelled'].includes(run.status)) break;
  await sleep(1000);
}
check(
  'a workflow is published and its run finishes on the worker at the end its input picks',
  wf.status < 300 && wfDecided?.status !== 'pending' && run?.status === 'succeeded' && run?.outcome === 'large',
  { definition: wf.status, publish: wfDecided, run: run && { status: run.status, outcome: run.outcome, steps: (run.steps ?? []).map((x) => `${x.nodeId}:${x.port ?? x.status}`) } },
);

// A one-page receipt read with a document type: uploaded to files-service, read by documents-service on the model.
const RECEIPT_TYPE = {
  id: `smoke_receipt_${TAG}`,
  name: `Smoke receipt ${TAG}`,
  description: 'A receipt for a payment: who paid, how much, when, and its reference.',
  many: false,
  fields: [
    { key: 'payer_name', label: 'Payer', type: 'text', required: true },
    { key: 'amount', label: 'Amount', type: 'money', required: true },
    { key: 'paid_on', label: 'Paid on', type: 'date' },
    { key: 'reference', label: 'Reference', type: 'text' },
  ],
};
const docType = await fetch(`${origin}/api/documents/v1/document-types`, { method: 'POST', headers: as, body: JSON.stringify(RECEIPT_TYPE) });
// The walk's tag makes each run's bytes its own, so files-service never hands back an earlier run's file.
const pdf = receiptPdf(['Payment receipt', 'Payer: Marcus Bell', 'Amount paid: CAD 2,000.00', 'Paid on: 2026-09-30', 'Reference: RECEIPT-UC249', `Walk ${TAG}`]);
const pdfTicket = await data(
  await fetch(`${origin}/api/files/v1/files/uploads`, {
    method: 'POST',
    headers: { ...as, 'Idempotency-Key': `smoke-pdf-${TAG}` },
    body: JSON.stringify({ name: `receipt-${TAG}.pdf`, size: pdf.length, mime: 'application/pdf', purpose: 'case_attachment' }),
  }),
);
await fetch(new URL(pdfTicket.uploadUrl, origin), {
  method: 'PUT',
  headers: { Authorization: as.Authorization, 'X-Team-Id': team, 'Content-Type': 'application/pdf', ...pdfTicket.headers },
  body: pdf,
});
// files-service dedupes by content within a team: a repeat walk gets the first upload's file back, so the read takes
// the id the completion returns, not the ticket's.
const pdfFile = await data(await fetch(`${origin}/api/files/v1/files/uploads/${pdfTicket.fileId}/complete`, { method: 'POST', headers: as }));
const extraction = await fetch(`${origin}/api/documents/v1/documents/extractions`, {
  method: 'POST',
  headers: as,
  body: JSON.stringify({ fileId: pdfFile.file?.id ?? pdfTicket.fileId, documentTypeId: RECEIPT_TYPE.id }),
});
const read = await extraction.json().catch(() => ({}));
const fields = read.data?.fields ?? {};
check(
  'a PDF is read with a document type through /api/documents, each field with its value',
  docType.status === 201 && read.data?.status === 'done' && fields.payer_name?.value === 'Marcus Bell' && fields.reference?.value === 'RECEIPT-UC249',
  { type: docType.status, status: extraction.status, read: read.data ? { status: read.data.status, fields: Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, v?.value])) } : read },
);

const browser = await chromium.launch();
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  const refused = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) refused.push(`${r.status()} ${r.url()}`);
  });
  await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  check('the console signs in through platform-service', true);

  await page.goto(`${origin}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  // Searched for by name: a busy test team's list pages, and the new agent can sort onto any page (c-441).
  await page.getByPlaceholder('Search agents…').fill(`Smoke ${TAG}`, { timeout: 60_000 });
  const listed = await page.getByText(`Smoke ${TAG}`).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
  check('Agents lists the new agent from agents-service', listed);

  await page.goto(`${origin}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const chat = await page.getByText(`Hello from the smoke run ${TAG}`).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
  check('the chat page shows the conversation', chat);

  await page.goto(`${origin}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const file = await page.getByText(`smoke-${TAG}.txt`).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
  check('Files lists the uploaded file from files-service', file);

  check('no page errors', errors.length === 0, errors);
  check('no /api/ request refused or failed', refused.length === 0, refused);
} finally {
  await browser.close();
}
await removeWhatWasMade();
console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
process.exit(failed ? 1 : 0);

/** Deletes the walk's records through their routes; a refusal is printed, never a failed check. */
async function removeWhatWasMade() {
  const steps = [
    ['agent', 'DELETE', `/api/agents/v1/agents/${agent.id}`],
    ['workflow', 'DELETE', `/api/agents/v1/workflows/definitions/${WORKFLOW}`],
    ['chat', 'POST', '/api/agents/chat/threads/bulk-delete', { ids: [thread] }],
    ['file', 'DELETE', `/api/files/v1/files/${done.file?.id ?? ticket.fileId}`],
    ['receipt', 'DELETE', `/api/files/v1/files/${pdfFile.file?.id ?? pdfTicket.fileId}`],
  ];
  if (approver) {
    const members = await data(await fetch(`${origin}/api/platform/v1/settings/members`, { headers: as })).catch(() => []);
    const rows = Array.isArray(members) ? members : members.data ?? [];
    const made = rows.find((m) => m.email === `smoke-approver-${TAG}@example.com`);
    if (made) steps.push(['approver', 'POST', '/api/platform/v1/settings/members/delete', { ids: [made.id] }]);
  }
  for (const [what, method, path, body] of steps) {
    let r = await fetch(`${origin}${path}`, { method, headers: as, body: body ? JSON.stringify(body) : undefined }).catch((e) => ({ status: String(e) }));
    if (what === 'workflow' && r.status === 409) {
      // A workflow that has run keeps its versions for its runs: archived, it leaves the lists and starts nothing.
      r = await fetch(`${origin}${path}/archive`, { method: 'POST', headers: as }).catch((e) => ({ status: String(e) }));
    }
    console.log(`${typeof r.status === 'number' && r.status < 300 ? 'REMOVED' : 'KEPT   '} ${what} ${path} ${r.status}`);
  }
}

/** A one-page PDF with each line in Helvetica, its xref offsets computed, so the walk carries no binary fixture. */
function receiptPdf(lines) {
  const text = lines.map((line, i) => `BT /F1 12 Tf 72 ${720 - i * 28} Td (${line.replace(/[()\\]/g, '\\$&')}) Tj ET`).join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
  ];
  let body = '%PDF-1.4\n';
  const offsets = objects.map((o, i) => {
    const at = body.length;
    body += `${i + 1} 0 obj\n${o}\nendobj\n`;
    return at;
  });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(body);
}
