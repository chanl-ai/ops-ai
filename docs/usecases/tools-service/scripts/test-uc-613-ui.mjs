// uc-613 An agent reads a team's file and a document's fields by its type, ui layer: step 5 of
// docs/usecases/tools-service/an-agent-reads-a-team-file.md. withUiStack's demo stack: tools-service reads
// through the run's files-service and documents-service, and the demo fake-OpenAI's uc613 rules have the agent call
// read_file, then read_document with the restraining notice type, then answer. Signed in as James, a builder of
// Operations, who grants ag_advisor the two tools and publishes it. The notice is a fixture documents-service's fake
// model answers; a trailing comment makes its bytes the team's own, apart from the seeded samples.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PRIYA = 'p.shah@harborpine.example';
const PASSWORD = 'northfield-demo';
const AGENT = 'ag_advisor';
const NAME = 'notice-uc613.pdf';
const SHOTS = evidenceDir('613', 'uc-613');
mkdirSync(SHOTS, { recursive: true });

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const data = async (r, what) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`setup: ${what} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const armed = (p) => (p.catch(() => undefined), p);

async function upload(headers) {
  const body = Buffer.concat([readFileSync(join(ROOT, 'services/documents-service/tests/fixtures/restraining/TEST006.pdf')), Buffer.from('\n%uc613')]);
  const meta = { name: NAME, size: body.length, mime: 'application/pdf', purpose: 'case_attachment', digest: createHash('sha256').update(body).digest('hex') };
  const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify(meta) }), 'upload ticket');
  const put = await fetch(ticket.uploadUrl.startsWith('http') ? ticket.uploadUrl : `${files}${ticket.uploadUrl}`, { method: 'PUT', headers: { ...(ticket.headers ?? {}), Authorization: headers.Authorization, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/pdf' }, body });
  if (!put.ok) throw new Error(`setup: put answered ${put.status}`);
  return (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers }), 'complete')).file.id;
}

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const fileId = await upload(J);
    const agent = await data(await fetch(`${agents}/v1/agents/${AGENT}`, { headers: J }), 'agent');
    const toolIds = [...new Set([...(agent.toolIds ?? []), 'read_file', 'read_document'])];
    const saved = await data(await fetch(`${agents}/v1/agents/${AGENT}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds }) }), 'grant');
    // The save opens a publish review (or one is open already); another person of the team, Priya, approves it.
    const pub = await fetch(`${agents}/v1/agents/${AGENT}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: saved.version, note: 'uc-613 file tools' }) });
    const asked = await pub.json().catch(() => ({}));
    const reviewId = asked.data?.id ?? /Publish request (\S+) is already open/.exec(asked.error?.message ?? '')?.[1];
    if (asked.data?.status !== 'approved') {
      if (!reviewId) throw new Error(`setup: publish answered ${pub.status}: ${JSON.stringify(asked).slice(0, 300)}`);
      const P = as(await tokenFor(PRIYA));
      const decided = await fetch(`${agents}/v1/publish-requests/${reviewId}/decision`, { method: 'POST', headers: P, body: JSON.stringify({ decision: 'approved' }) });
      if (!decided.ok) throw new Error(`setup: approval answered ${decided.status}: ${await decided.text()}`);
    }
    const granted = (await data(await fetch(`${agents}/v1/agents/${AGENT}`, { headers: J }), 'agent again')).toolIds;
    const offered = (await data(await fetch(`${agents}/v1/tools?pageSize=200`, { headers: J }), 'tools')).data.map((t) => t.id ?? t.name).filter((n) => /read_/.test(n));
    const thread = await data(await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: AGENT, kbIds: [] }) }), 'thread');

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/chat/${thread.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      await box.fill(`uc613 read ${NAME} and tell me the case number`);
      const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const res = await sent;
      await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 120_000))]);
      await page.getByText('SYN-2026-0006').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      await page.screenshot({ path: join(SHOTS, 'chat-1440.png'), fullPage: true });

      const cards = page.getByTestId('chat-tool-call');
      const labels = (await cards.allInnerTexts()).join(' | ');
      const last = (await data(await fetch(`${agents}/chat/threads/${thread.id}`, { headers: J }), 'thread read')).messages.at(-1);
      const calls = (last?.toolCalls ?? []).map((c) => [c.name, c.status]);
      check(
        '5 in chat the agent reads the file by name and pulls the notice fields, each shown as a tool row, and answers with the case number',
        JSON.stringify(calls) === JSON.stringify([['read_file', 'success'], ['read_document', 'success']]) &&
          String(last?.content).includes('SYN-2026-0006') &&
          /read_file|Read file|Files/i.test(labels) &&
          /read_document|Read document|Document types/i.test(labels),
        { calls, labels: labels.slice(0, 300), text: String(last?.content).slice(0, 200), fileId, granted, offered },
      );
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
