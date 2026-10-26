// uc-525 a workflow waits for long-running work and carries on when it finishes, ui layer:
// docs/usecases/console/wait-for-long-work.md (c-525). The demo stack with a worker, files-service and documents-service.
// 1-3: a tax levy over five pages, which documents-service reads in the background: Extract from file parks instead of
// holding a worker, documents-service reports extraction.finished, the run resumes on it, and a Decide step branches on
// the amount it found. 4-6: a Wait for step parks and resumes on its signed callback; a forged token and a second call
// are refused. 7: a Wait for step whose work never finishes leaves by its Timeout port, and a late callback is refused.
// 8: the run page says what a waiting run waits for.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const SHOTS = evidenceDir('525', 'uc');

const tokenFor = async (email) =>
  (
    await (
      await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
    ).json()
  ).data.token;
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** TAXLEVY01 with five blank pages after it: over the five pages documents-service reads inside a request. */
function longLevy() {
  const src = join(ROOT, 'services/documents-service/tests/fixtures/tax_levy/TAXLEVY01.pdf');
  const code = `
import io, sys, pypdfium2 as pdfium
src = pdfium.PdfDocument(sys.argv[1])
out = pdfium.PdfDocument.new()
out.import_pages(src)
w, h = src[0].get_size()
for _ in range(5):
    out.new_page(w, h)
buf = io.BytesIO()
out.save(buf)
sys.stdout.buffer.write(buf.getvalue())`;
  const made = spawnSync('uv', ['run', 'python', '-c', code, src], { cwd: join(ROOT, 'services/documents-service'), maxBuffer: 64 << 20 });
  if (made.status !== 0) throw new Error(`setup: building the long levy failed: ${made.stderr}`);
  return made.stdout;
}

/** The run's recorded event types, read once (`follow=false`). */
async function eventTypes(runId, headers) {
  const text = await (await fetch(`${agents}/v1/runs/${runId}/events?follow=false`, { headers })).text();
  return [...text.matchAll(/^event: (.+)$/gm)].map((m) => m[1].trim());
}

const trigger = {
  id: 'start',
  type: 'ops.trigger.request',
  typeVersion: 1,
  name: 'Request',
  parameters: { onlyFromWorkflows: false, inputSchema: { type: 'object', properties: { fileId: { type: 'string', format: 'file' } } } },
};
const end = (id, outcome, result) => ({ id, type: 'ops.flow.end', typeVersion: 1, name: id, parameters: { outcome, ...(result ? { result } : {}) } });
const link = (from, port, to) => ({ from: { node: from, port }, to: { node: to, port: 'in' } });

/** Read the levy, then decide on the amount it found: the case the owner asked for. */
const READ_AND_DECIDE = {
  schemaVersion: 2,
  id: 'uc525_read_decide',
  name: 'Read a long levy and decide (uc-525)',
  nodes: [
    trigger,
    { id: 'read', type: 'ops.ai.extract', typeVersion: 1, name: 'Read the levy', parameters: { file: '$.input.fileId', detect: true, onTimeout: 'port' } },
    { id: 'decide', type: 'ops.flow.if', typeVersion: 1, name: 'Over 1,000?', parameters: { conditions: [{ left: '$.nodes.read.out.fields.amount_due.value', op: 'gt', right: 1000 }] } },
    end('large', 'large_levy'),
    end('small', 'small_levy'),
    end('not_read', 'not_read', 'failed'),
    end('too_slow', 'too_slow'),
  ],
  connections: [
    link('start', 'payload', 'read'),
    link('read', 'ok', 'decide'),
    link('read', 'review', 'decide'),
    link('read', 'unreadable', 'not_read'),
    link('read', 'error', 'not_read'),
    link('read', 'timeout', 'too_slow'),
    link('decide', 'true', 'large'),
    link('decide', 'false', 'small'),
  ],
};

/** Wait for an outside system's answer, then decide on it. */
const waitFor = (id, timeoutSeconds) => ({
  schemaVersion: 2,
  id,
  name: `Wait for an answer (${id})`,
  nodes: [
    trigger,
    {
      id: 'wait',
      type: 'ops.flow.waitFor',
      typeVersion: 1,
      name: 'Wait for the core system',
      parameters: { timeoutSeconds, outputSchema: { type: 'object', properties: { approved: { type: 'boolean' } } } },
    },
    { id: 'decide', type: 'ops.flow.if', typeVersion: 1, name: 'Approved?', parameters: { conditions: [{ left: '$.nodes.wait.out.approved', op: 'eq', right: true }] } },
    end('yes', 'approved'),
    end('no', 'declined'),
    end('late', 'timed_out'),
  ],
  connections: [link('start', 'payload', 'wait'), link('wait', 'ok', 'decide'), link('wait', 'timeout', 'late'), link('decide', 'true', 'yes'), link('decide', 'false', 'no')],
});

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const save = async (definition) => fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition }) });
    const start = async (workflowId, input = {}) => (await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId, mode: 'test', input }) })))?.runId;
    const run = async (id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers: J }));
    const done = async (id, ms) =>
      until(async () => {
        const r = await run(id);
        return ['succeeded', 'failed', 'cancelled'].includes(r?.status) ? r : null;
      }, ms);
    const parked = async (id) =>
      until(async () => {
        const r = await run(id);
        return r?.status === 'waiting' && r.waiting?.payload?.kind === 'external' ? r : null;
      }, 60_000);

    let readRun = null;
    await step('1 a long levy parks Extract from file instead of holding a worker', async () => {
      const pdf = longLevy();
      const ticket = await json(
        await fetch(`${files}/v1/files/uploads`, {
          method: 'POST',
          headers: J,
          body: JSON.stringify({ name: 'TAXLEVY01-long.pdf', size: pdf.length, mime: 'application/pdf', purpose: 'case_attachment', digest: createHash('sha256').update(pdf).digest('hex') }),
        }),
      );
      await fetch(new URL(ticket.uploadUrl, files), { method: 'PUT', headers: { Authorization: J.Authorization, 'X-Team-Id': 'team_ops', ...ticket.headers }, body: pdf });
      const stored = (await json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J })))?.file;
      const saved = await save(READ_AND_DECIDE);
      if (saved.status >= 300) throw new Error(`saving the workflow answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
      readRun = await start(READ_AND_DECIDE.id, { fileId: stored.id });
      const finished = await done(readRun, 240_000);
      const types = await eventTypes(readRun, J);
      check('1 a long levy parks Extract from file instead of holding a worker', types.includes('waiting_external'), { status: finished?.status, types });
    });

    await step('2 the run resumes on extraction.finished', async () => {
      const types = await eventTypes(readRun, J);
      check('2 the run resumes on extraction.finished', types.includes('resumed_by_event'), types);
    });

    await step('3 the Decide step branches on the amount the read found', async () => {
      const r = await run(readRun);
      check('3 the Decide step branches on the amount the read found', r?.status === 'succeeded' && ['large_levy', 'small_levy'].includes(r.outcome), {
        status: r?.status,
        outcome: r?.outcome,
        error: r?.error,
      });
    });

    let waitRun = null;
    let resume = null;
    await step('4 a Wait for step parks and gives its signed resume URL', async () => {
      const saved = await save(waitFor('uc525_wait', 600));
      if (saved.status >= 300) throw new Error(`saving the workflow answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
      waitRun = await start('uc525_wait');
      const r = await parked(waitRun);
      resume = r?.waiting?.payload?.resume ?? null;
      check('4 a Wait for step parks and gives its signed resume URL', !!resume?.url && !!resume?.token && resume.url.includes(`/v1/runs/${waitRun}/steps/`), r?.waiting);
    });

    await step('5 a forged token is refused, then the real callback resumes the run and the Decide step reads its answer', async () => {
      const post = (token) =>
        fetch(new URL(resume.url, agents), { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ approved: true }) });
      const forged = await post(`${resume.token.slice(0, -4)}AAAA`);
      const real = await post(resume.token);
      const r = await done(waitRun, 60_000);
      check('5 a forged token is refused, then the real callback resumes the run and the Decide step reads its answer', forged.status === 401 && real.status === 202 && r?.outcome === 'approved', {
        forged: forged.status,
        real: real.status,
        outcome: r?.outcome,
      });
    });

    await step('6 a second callback is refused as already resumed', async () => {
      const again = await fetch(new URL(resume.url, agents), {
        method: 'POST',
        headers: { Authorization: `Bearer ${resume.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: false }),
      });
      check('6 a second callback is refused as already resumed', again.status === 409, { status: again.status, body: (await again.text()).slice(0, 200) });
    });

    await step('7 work that never finishes leaves by the Timeout port, and a late callback is refused', async () => {
      const saved = await save(waitFor('uc525_timeout', 5));
      if (saved.status >= 300) throw new Error(`saving the workflow answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
      const id = await start('uc525_timeout');
      const late = (await parked(id))?.waiting?.payload?.resume;
      const r = await done(id, 90_000);
      const after = late
        ? await fetch(new URL(late.url, agents), { method: 'POST', headers: { Authorization: `Bearer ${late.token}`, 'Content-Type': 'application/json' }, body: '{"approved": true}' })
        : null;
      check('7 work that never finishes leaves by the Timeout port, and a late callback is refused', r?.outcome === 'timed_out' && after?.status === 409, { outcome: r?.outcome, late: after?.status });
    });

    await step('8 the run page says what a waiting run waits for', async () => {
      const id = await start('uc525_wait');
      await parked(id);
      const browser = await chromium.launch();
      try {
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, []);
        await page.goto(`${consoleUrl}/workflows/runs/${id}`, { waitUntil: 'domcontentloaded' });
        const said = page.getByText(/Waiting for: Wait for the core system/).first();
        const shown = await said.waitFor({ timeout: 60_000 }).then(
          () => true,
          () => false,
        );
        for (const width of [1280, 400]) {
          await page.setViewportSize({ width, height: 900 });
          await page.waitForTimeout(600);
          await page.screenshot({ path: join(SHOTS, `waiting-run-${width}.png`), fullPage: true });
        }
        check('8 the run page says what a waiting run waits for', shown);
      } finally {
        await browser.close();
      }
    });
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
