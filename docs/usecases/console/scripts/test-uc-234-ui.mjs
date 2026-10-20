// uc-234 A Human Task opens as its own page, ui layer: docs/usecases/console/human-task-page.md (c-289). Platform
// sign-in; James reads TEST012.pdf in Operations through files-service, which starts the system extract workflow; the
// fake model leaves the garnishee off the page, so the run waits for a person to check the read. Maya decides it.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, DOCUMENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const documents = `http://127.0.0.1:${DOCUMENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const MAYA = 'm.okafor@northfieldbank.com';
const tokenFor = async (email) =>
  (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const SHOTS = process.env.UC234_SHOTS ?? join(ROOT, 'docs/console/proposed/tasks');
// Words of the engine that belong under Details, never in the question, the evidence or the decision.
const ENGINE_WORDS = /\bGate\b|Every paused step|Not scored|wfrun_|event:|Reviewers:|Runs \S+ on approval|team_ops/;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const listed = await json(await fetch(`${files}/v1/files?page=1&pageSize=20&search=TEST012`, { headers: J }));
    const file = listed.data.find((f) => f.name === 'TEST012.pdf');
    if (!file) throw new Error('setup: TEST012.pdf is not in Operations');
    // A read request starts the system extract workflow; it waits at its check for the field not on the page.
    const readAndWait = async (version) => {
      const req = await json(
        await fetch(`${files}/v1/files/${file.id}/read-requests`, {
          method: 'POST',
          headers: { ...J, 'Content-Type': 'application/json', 'Idempotency-Key': `uc234-${Date.now()}` },
          body: JSON.stringify({ documentTypeId: 'restraining_notice', ...(version ? { version } : {}) }),
        }),
      );
      let id = null;
      let r = null;
      for (let i = 0; i < 180 && !(r?.status === 'waiting' && r.waiting); i++) {
        await sleep(1000);
        id ??= (await json(await fetch(`${files}/v1/files/${file.id}/read-requests/${req.key}`, { headers: J }))).runId;
        if (id) r = await json(await fetch(`${agents}/v1/runs/${id}`, { headers: J }));
      }
      if (!r?.waiting) throw new Error(`setup: the read did not wait for a check: ${r?.status} / ${r?.outcome}`);
      return { runId: id, reviewId: `${id}:${r.waiting.node}:${r.waiting.iteration}` };
    };
    const { runId, reviewId } = await readAndWait();

    const browser = await chromium.launch();
    const errors = [];
    try {
      const signIn = async (width, height = 800, email = MAYA) => {
        const page = await (await browser.newContext({ viewport: { width, height } })).newPage();
        page.setDefaultTimeout(60_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(email);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return page;
      };
      const page = await signIn(1280);
      mkdirSync(SHOTS, { recursive: true });

      const onPage = (u) => decodeURIComponent(u.pathname) === `/reviews/${reviewId}`;
      await step('1 a row opens the task as a page; Quick view on the row peeks wider than 672px, and its Open goes to the page', async () => {
        await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId(`review-row-${reviewId}`).click();
        const rowOpensPage = await page.waitForURL(onPage, { timeout: 30_000 }).then(() => true, () => false);
        await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId(`review-peek-${reviewId}`).click();
        const sheet = page.getByTestId('review-sheet');
        await sheet.waitFor();
        const width = (await sheet.boundingBox())?.width ?? 0;
        const stayed = new URL(page.url()).pathname === '/reviews';
        await page.screenshot({ path: join(SHOTS, 'quick-view-1280.png') });
        await page.getByTestId('review-open-page').click();
        const openGoes = await page.waitForURL(onPage, { timeout: 30_000 }).then(() => true, () => false);
        check('1 a row opens the task as a page; Quick view on the row peeks wider than 672px, and its Open goes to the page', rowOpensPage && stayed && width > 672 && openGoes, { rowOpensPage, stayed, width, openGoes });
      });

      await step('2 the page states one question, with the document beside the fields at 1280', async () => {
        const question = await page.getByTestId('page-title').innerText();
        const viewer = page.getByTestId('task-evidence').getByTestId('document-viewer');
        await viewer.getByTestId('viewer-page-1').locator('img').waitFor({ timeout: 60_000 });
        const boxes = await viewer.locator('[data-box-key]').count();
        const ev = await page.getByTestId('task-evidence').boundingBox();
        const de = await page.getByTestId('task-decide').boundingBox();
        const garnishee = await page.getByTestId('read-field-0-garnishee').getAttribute('data-needs-review');
        await page.waitForTimeout(1500);
        await page.screenshot({ path: join(SHOTS, 'task-read-check-1280.png') });
        check(
          '2 the page states one question, with the document beside the fields at 1280',
          /^Check \d+ fields? read from TEST012\.pdf$/.test(question) && boxes > 0 && !!ev && !!de && ev.x + ev.width <= de.x + 1 && Math.abs(ev.y - de.y) < 4 && garnishee === 'true',
          { question, boxes, ev, de, garnishee },
        );
      });

      await step('3 engine words stay under Details, which starts folded and names the run under Technical details', async () => {
        const outside = [await page.getByTestId('page-header').innerText(), await page.getByTestId('task-evidence').innerText(), await page.getByTestId('task-footer').innerText()].join('\n');
        const decide = page.getByTestId('task-decide');
        const decideText = (await decide.innerText()).replace(await page.getByTestId('task-details').innerText(), '');
        const foldedFirst = (await page.getByTestId('task-details').getAttribute('data-state')) === 'closed';
        await page.getByTestId('task-details-toggle').click();
        const readable = await page.getByTestId('task-details').innerText();
        // The run, the step and the policy are the engine's names for it: folded again under Technical details.
        await page.getByTestId('task-technical-toggle').click();
        const details = await page.getByTestId('task-details').innerText();
        const hits = `${outside}\n${decideText}`.match(ENGINE_WORDS);
        check(
          '3 engine words stay under Details, which starts folded and names the run under Technical details',
          !hits && foldedFirst && !readable.includes(runId) && details.includes(runId),
          { hits: hits?.[0], foldedFirst, readable: readable.slice(0, 200), details: details.slice(0, 300) },
        );
      });

      await step('4 the footer is a row below the body: scrolled to the end, nothing sits under it', async () => {
        const body = page.getByTestId('task-body');
        await body.evaluate((el) => el.scrollTo(0, el.scrollHeight));
        await page.waitForTimeout(300);
        const footer = await page.getByTestId('task-footer').boundingBox();
        const bodyBox = await body.boundingBox();
        const lastBottom = await page.getByTestId('task-decide').evaluate((el) => el.getBoundingClientRect().bottom);
        const position = await page.getByTestId('task-footer').evaluate((el) => getComputedStyle(el).position);
        const consequence = await page.getByTestId('review-consequence').innerText();
        await page.screenshot({ path: join(SHOTS, 'task-read-check-1280-end.png') });
        check(
          '4 the footer is a row below the body: scrolled to the end, nothing sits under it',
          !!footer && !!bodyBox && bodyBox.y + bodyBox.height <= footer.y + 1 && lastBottom <= footer.y + 1 && position === 'static' && consequence.startsWith('Approve:'),
          { footerTop: footer?.y, bodyBottom: bodyBox && bodyBox.y + bodyBox.height, lastBottom, position, consequence },
        );
      });

      await step('4b the footer is one row until Reject asks for a reason, then grows without covering the body', async () => {
        const footer = page.getByTestId('task-footer');
        const before = (await footer.boundingBox())?.height ?? 0;
        // The read check is a typed document_check task: its Reject asks for the reason its type requires.
        const noBoxFirst = await page.getByTestId('option-reason').count();
        await page.getByTestId('decide-reject').click();
        const box = page.getByTestId('option-reason');
        await box.waitFor();
        const focused = await box.evaluate((el) => el === document.activeElement);
        const after = await footer.boundingBox();
        const body = await page.getByTestId('task-body').boundingBox();
        await page.screenshot({ path: join(SHOTS, 'task-read-check-1280-reason.png') });
        // Nothing was decided: a reject needs its reason, so the review stays open.
        const still = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: J }));
        check(
          '4b the footer is one row until Reject asks for a reason, then grows without covering the body',
          before > 0 && before < 90 && noBoxFirst === 0 && focused && !!after && after.height > before && !!body && body.y + body.height <= after.y + 1 && still.status === 'waiting',
          { before, noBoxFirst, focused, after: after?.height, bodyBottom: body && body.y + body.height, footerTop: after?.y, status: still.status },
        );
      });

      await step('5 at 400px one pane shows at a time, switched by Evidence and Decide, and nothing scrolls sideways', async () => {
        const narrow = await signIn(400, 800);
        await narrow.goto(`${consoleUrl}/reviews/${encodeURIComponent(reviewId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await narrow.getByTestId('page-title').waitFor();
        await narrow.getByTestId('task-evidence').getByTestId('viewer-page-1').locator('img').waitFor({ timeout: 60_000 });
        const evidenceFirst = await narrow.getByTestId('task-evidence').isVisible();
        const decideHidden = !(await narrow.getByTestId('task-decide').isVisible());
        await narrow.screenshot({ path: join(SHOTS, 'task-read-check-400-evidence.png') });
        await narrow.getByTestId('task-pane-decide').click();
        const decideShown = await narrow.getByTestId('task-decide').isVisible();
        const evidenceHidden = !(await narrow.getByTestId('task-evidence').isVisible());
        const sideways = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        await narrow.screenshot({ path: join(SHOTS, 'task-read-check-400-decide.png') });
        check('5 at 400px one pane shows at a time, switched by Evidence and Decide, and nothing scrolls sideways', evidenceFirst && decideHidden && decideShown && evidenceHidden && sideways <= 0, {
          evidenceFirst,
          decideHidden,
          decideShown,
          evidenceHidden,
          sideways,
        });
      });

      await step('6 Approve in the footer resumes the run, which saves the read', async () => {
        await page.getByTestId('decide-approve').click();
        let finished;
        for (let i = 0; i < 90; i++) {
          finished = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: J }));
          if (['succeeded', 'failed', 'cancelled'].includes(finished.status)) break;
          await sleep(1000);
        }
        check('6 Approve in the footer resumes the run, which saves the read', finished?.status === 'succeeded' && finished?.outcome === 'saved', { status: finished?.status, outcome: finished?.outcome });
      });

      await step('7 a type marking two key fields: they come first, Approve waits for both, the rest are accepted together', async () => {
        // A fixture version of the type, the same fields with the case number and the court marked key.
        const type = await json(await fetch(`${documents}/v1/document-types/restraining_notice`, { headers: J }));
        const latest = await json(await fetch(`${documents}/v1/document-types/restraining_notice/versions/${type.latestVersion}`, { headers: J }));
        const body = Object.fromEntries(['many', 'reviewBelow', 'dateOrder', 'templates'].filter((k) => latest[k] !== undefined && latest[k] !== null).map((k) => [k, latest[k]]));
        body.fields = latest.fields.map((f) => (['case_no', 'court'].includes(f.key) ? { ...f, keyField: true } : f));
        const made = await json(await fetch(`${documents}/v1/document-types/restraining_notice/versions`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
        const keyed = await readAndWait(made.version);
        await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(keyed.reviewId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const question = await page.getByTestId('page-title').innerText();
        const block = page.getByTestId('read-key-fields-0');
        await block.waitFor();
        const keyRows = await block.locator('[data-testid^="read-field-0-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')));
        const approve = page.getByTestId('decide-approve');
        const lockedText = await approve.innerText();
        const locked = await approve.isDisabled();
        await page.waitForTimeout(1200);
        await page.screenshot({ path: join(SHOTS, 'task-key-fields-1280.png') });
        await page.getByTestId('read-confirm-0-case_no').click();
        const stillLocked = await approve.isDisabled();
        await page.getByTestId('read-confirm-0-court').click();
        const unlocked = !(await approve.isDisabled());
        const othersFolded = (await page.getByTestId('read-other-fields-0').getAttribute('data-state')) === 'closed';
        const foldSays = await page.getByTestId('read-other-summary-0').innerText();
        await page.getByTestId('read-accept-others-0').click();
        const accepted = (await page.getByTestId('read-accept-others-0').getAttribute('aria-pressed')) === 'true';
        await page.screenshot({ path: join(SHOTS, 'task-key-fields-confirmed-1280.png') });
        await approve.click();
        let finished;
        for (let i = 0; i < 90; i++) {
          finished = await json(await fetch(`${agents}/v1/runs/${keyed.runId}`, { headers: J }));
          if (['succeeded', 'failed', 'cancelled'].includes(finished.status)) break;
          await sleep(1000);
        }
        check(
          '7 a type marking two key fields: they come first, Approve waits for both, the rest are accepted together',
          question === 'Check 2 key fields read from TEST012.pdf' &&
            JSON.stringify(keyRows.sort()) === JSON.stringify(['read-field-0-case_no', 'read-field-0-court']) &&
            locked && lockedText.includes('confirm 2 key fields first') && stillLocked && unlocked && othersFolded && foldSays.includes('1 to check') && accepted && finished?.outcome === 'saved',
          { question, keyRows, locked, lockedText, stillLocked, unlocked, othersFolded, foldSays, accepted, outcome: finished?.outcome },
        );
      });

      await step('8 a tool access request opens for the deciding team as one column: a plain question, the reason, what the access is, and Grant or Refuse', async () => {
        const asked = await fetch(`${tools}/v1/tool-modules/mod_core_banking/approvals`, {
          method: 'POST',
          headers: { ...J, 'Content-Type': 'application/json' },
          // The workflow uc-010 requests for; tools-service reads it from agents-service's workflows.
          body: JSON.stringify({ workflowId: 'dispute_email', environment: 'production', operations: ['get_customer_profile'], expiresInDays: 90, justification: 'Wire reviews read the customer profile' }),
        });
        const answered = await asked.json();
        const approval = answered.data;
        if (asked.status !== 201) throw new Error(`the access request answered ${asked.status}: ${JSON.stringify(answered).slice(0, 400)}`);
        // Whoever the server says may decide it: the workflow's own team decides, and James asked, so not him.
        const people = [
          ['m.okafor@northfieldbank.com', 'team_ops'],
          ['p.shah@northfieldbank.com', 'team_ops'],
          ['n.petrov@northfieldbank.com', 'team_security'],
          ['s.adeyemi@northfieldbank.com', 'team_security'],
          ['o.haddad@northfieldbank.com', 'team_fraud'],
          ['l.fischer@northfieldbank.com', 'team_fraud'],
          ['w.kamau@northfieldbank.com', 'team_platform'],
        ];
        let review = null;
        let decider = null;
        for (let i = 0; i < 60 && !decider; i++) {
          await sleep(1000);
          for (const [email, team] of people) {
            const r = await fetch(`${agents}/reviews/by-run-key/${encodeURIComponent(approval.reviewId)}`, { headers: { Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team } });
            if (!r.ok) continue;
            review = (await r.json()).data;
            if (review?.canDecide) {
              decider = email;
              break;
            }
          }
        }
        if (!decider) throw new Error(`no seeded reviewer may decide ${approval.reviewId}; last seen ${JSON.stringify(review ?? null).slice(0, 200)}`);
        const results = {};
        for (const width of [1280, 400]) {
          const nadia = await signIn(width, 800, decider);
          await nadia.goto(`${consoleUrl}/reviews/${encodeURIComponent(review.id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await nadia.getByTestId('task-decide').waitFor({ timeout: 60_000 });
          const body = await nadia.getByTestId('task-body').innerText();
          results[width] = {
            question: await nadia.getByTestId('page-title').innerText(),
            said: (await nadia.getByTestId('page-header').innerText()).replace(/\s+/g, ' '),
            footer: await nadia.getByTestId('task-footer').innerText(),
            body: body.replace(/\s+/g, ' ').slice(0, 400),
            // One column: no evidence pane, and the column is about 760px wide.
            panes: await nadia.getByTestId('task-evidence').count(),
            column: await nadia.getByTestId('task-decide').evaluate((el) => Math.round(el.getBoundingClientRect().width)),
          };
          results[width].sideways = await nadia.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          await nadia.waitForTimeout(800);
          await nadia.screenshot({ path: join(SHOTS, `task-tool-access-${width}.png`) });
        }
        check(
          '8 a tool access request opens for the deciding team as one column: a plain question, the reason, what the access is, and Grant or Refuse',
          results[1280].question === 'Let Dispute email use Core banking?' &&
            // The question names the workflow; the card adds only what it does not say.
            ['Wire reviews read the customer profile', 'Tools', 'get_customer_profile', 'Environment', 'Until'].every((t) => results[1280].body.includes(t)) && !results[1280].body.includes('Used by') && !/Where it came from/.test(results[1280].body) &&
            !/event:|Apply tool access|decision approved/.test(results[1280].said + results[1280].body) &&
            /Grant/.test(results[1280].footer) && /Refuse/.test(results[1280].footer) && /until \d{1,2} \w{3} \d{4}/.test(results[1280].footer) &&
            results[1280].panes === 0 && results[1280].column <= 800 && results[400].sideways <= 0,
          results,
        );
      });

      await step('9 a read combined with a second source shows each source in its own column and marks where they differ', async () => {
        // A workflow of three steps: read the file, combine its case number with the one the request gave, ask a person.
        const wid = `uc234_combine_${Date.now()}`;
        const definition = {
          schemaVersion: 2,
          id: wid,
          name: 'Read and compare',
          nodes: [
            { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', parameters: { inputSchema: { type: 'object', properties: { fileId: { type: 'string' }, caseNo: { type: 'string' } } } } },
            { id: 'read', type: 'ops.ai.extract', typeVersion: 1, name: 'Read the notice', parameters: { file: '$.input.fileId', documentType: { id: 'restraining_notice' } } },
            { id: 'facts', type: 'ops.data.combine', typeVersion: 1, name: 'Compare the case number', parameters: { sources: [{ name: 'document', values: '$.nodes.read.out.fields' }, { name: 'request', values: { case_no: '$.input.caseNo' } }] } },
            { id: 'check', type: 'ops.flow.humanReview', typeVersion: 1, name: 'Check the read', parameters: { title: 'Check the read', summary: { file: 'TEST012.pdf', read: '$.nodes.read.out', facts: '$.nodes.facts.out' } } },
            { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'checked' } },
            { id: 'unread', type: 'ops.flow.end', typeVersion: 1, name: 'Not read', parameters: { outcome: 'not_read' } },
          ],
          connections: [
            { from: { node: 'start', port: 'payload' }, to: { node: 'read', port: 'in' } },
            { from: { node: 'read', port: 'ok' }, to: { node: 'facts', port: 'in' } },
            { from: { node: 'read', port: 'review' }, to: { node: 'facts', port: 'in' } },
            { from: { node: 'read', port: 'unreadable' }, to: { node: 'unread', port: 'in' } },
            { from: { node: 'read', port: 'error' }, to: { node: 'unread', port: 'in' } },
            { from: { node: 'facts', port: 'out' }, to: { node: 'check', port: 'in' } },
            { from: { node: 'check', port: 'approve' }, to: { node: 'done', port: 'in' } },
            { from: { node: 'check', port: 'reject' }, to: { node: 'done', port: 'in' } },
          ],
        };
        const savedDef = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ definition }) });
        if (!savedDef.ok) throw new Error(`saving the workflow answered ${savedDef.status}: ${(await savedDef.text()).slice(0, 300)}`);
        const startedRun = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ workflowId: wid, mode: 'test', input: { fileId: file.id, caseNo: 'SYN-2026-0099' } }) }));
        let r = null;
        for (let i = 0; i < 120 && !(r?.status === 'waiting' && r.waiting); i++) {
          await sleep(1000);
          r = await json(await fetch(`${agents}/v1/runs/${startedRun.runId}`, { headers: J }));
          if (['failed', 'cancelled', 'succeeded'].includes(r.status)) break;
        }
        if (!r?.waiting) throw new Error(`the compare run did not wait: ${r?.status} / ${JSON.stringify(r?.error ?? null).slice(0, 200)}`);
        await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(`${startedRun.runId}:${r.waiting.node}:${r.waiting.iteration}`)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const doc = page.getByTestId('read-source-0-case_no-document');
        await doc.waitFor({ timeout: 60_000 });
        const fromDocument = (await doc.innerText()).trim();
        const fromRequest = (await page.getByTestId('read-source-0-case_no-request').innerText()).trim();
        const differs = await page.getByTestId('read-differs-0-case_no').count();
        const agreesElsewhere = await page.getByTestId('read-differs-0-court').count();
        await page.screenshot({ path: join(SHOTS, 'task-read-sources-1280.png') });
        // c-261's screen evidence: the same check at 1280 and 400.
        mkdirSync(join(ROOT, '.codeloop/evidence/261/screens'), { recursive: true });
        await page.screenshot({ path: join(ROOT, '.codeloop/evidence/261/screens/read-sources-1280.png') });
        await page.setViewportSize({ width: 400, height: 800 });
        // On a phone the sources sit in the Decide pane.
        await page.getByTestId('task-pane-decide').click();
        await page.waitForTimeout(400);
        await page.screenshot({ path: join(ROOT, '.codeloop/evidence/261/screens/read-sources-400.png') });
        await page.setViewportSize({ width: 1280, height: 800 });
        check(
          '9 a read combined with a second source shows each source in its own column and marks where they differ',
          fromDocument === 'SYN-2026-0012' && fromRequest === 'SYN-2026-0099' && differs === 1 && agreesElsewhere === 0,
          { fromDocument, fromRequest, differs, agreesElsewhere },
        );
      });

      await step('10 a typed task draws the regions its type binds and decides by its own actions, a decline asking for a reason', async () => {
        const facts = [{ label: 'Vendor', value: 'Acme Supplies' }, { label: 'New account', value: '****4410' }];
        const posted = await fetch(`${agents}/v1/tasks`, {
          method: 'POST',
          headers: { ...J, 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'write_approval', params: { title: 'Change the bank account for Acme Supplies to ****4410?', why: 'The vendor asked by email', facts, call: { tool: 'update_vendor_bank', input: { vendor: 'Acme Supplies', account: '****4410' } }, onApprove: 'The account is updated now.', onReject: 'Nothing changes.' } }),
        });
        const task = (await posted.json()).data;
        if (posted.status !== 201) throw new Error(`opening the task answered ${posted.status}: ${JSON.stringify(task).slice(0, 300)}`);
        // The task opens as a system run that pauses at its step; its page exists once the run waits there.
        for (let i = 0; i < 60; i++) {
          if ((await fetch(`${agents}/reviews/${encodeURIComponent(task.id)}`, { headers: J })).ok) break;
          await sleep(1000);
        }
        await page.goto(`${consoleUrl}${task.url}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const title = page.getByTestId('page-title');
        const shown = await title.filter({ hasText: 'Acme Supplies' }).waitFor({ timeout: 60_000 }).then(() => true, () => false);
        if (!shown) throw new Error(`the task page showed: ${task.url} / ${(await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(200, 700)}`);
        const question = (await title.innerText()).trim();
        // The header says where the task sits in the open queue, from the server, and offers Close.
        const position = await page.getByTestId('task-position').waitFor({ timeout: 20_000 }).then(() => page.getByTestId('task-position').innerText(), () => '');
        const closes = await page.getByTestId('task-close').count();
        const place = await (await fetch(`${agents}/reviews/${encodeURIComponent(task.id)}/place`, { headers: J })).json().catch(() => null);
        check('10b the task header says "n of N" for the open queue and offers Close', /^\d+ of \d+$/.test(position.trim()) && closes === 1, { position, closes, place: place?.data ?? place });
        const decideText = await page.getByTestId('task-decide').innerText();
        const buttons = await page.getByTestId('option-decision-form').locator('button').allInnerTexts();
        await page.getByTestId('option-decision-form').getByRole('button', { name: /^Decline/ }).hover();
        const says = await page.getByTestId('review-consequence').innerText();
        await page.screenshot({ path: join(SHOTS, 'task-typed-write-approval-1280.png') });
        // Decline asks for its reason first; a second press with the reason sends it.
        await page.getByTestId('option-decision-form').getByRole('button', { name: /^Decline/ }).click();
        await page.getByTestId('option-reason').fill('Call the vendor first');
        const posting = page.waitForResponse((res) => res.request().method() === 'POST' && /\/decision$/.test(res.url()), { timeout: 30_000 }).catch(() => null);
        await page.getByTestId('option-decision-form').getByRole('button', { name: /^Decline/ }).click();
        const answer = await posting;
        const sent = answer ? { status: answer.status(), body: answer.request().postData(), said: (await answer.text()).slice(0, 200) } : null;
        let state = null;
        for (let i = 0; i < 60 && !state?.action; i++) {
          await sleep(1000);
          const r = await fetch(`${agents}/v1/tasks/${task.id}`, { headers: J });
          if (r.ok) state = (await r.json()).data;
        }
        check(
          '10 a typed task draws the regions its type binds and decides by its own actions, a decline asking for a reason',
          // The question says the vendor and the account, so the decide pane does not repeat them.
          question === 'Change the bank account for Acme Supplies to ****4410?' && !/\*\*\*\*4410/.test(decideText) && buttons.some((b) => /Make the change/.test(b)) && buttons.some((b) => /Decline/.test(b)) && says.includes('Nothing changes.') && state?.action === 'reject' && state?.reason === 'Call the vendor first',
          { question, buttons, says, sent, decision: state && { action: state.action, reason: state.reason } },
        );
      });

      await step('11 with task assist on, the task shows the AI assist labelled as AI and marks its suggestion without choosing it', async () => {
        // Priya, admin of Operations, turns task assist on (Govern > Policies).
        const on = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies/taskAssist`, { method: 'PUT', headers: { Authorization: `Bearer ${await tokenFor('p.shah@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ value: true }) });
        const facts = [{ label: 'Vendor', value: 'Acme Supplies' }, { label: 'New account', value: '****4410' }];
        const posted = await fetch(`${agents}/v1/tasks`, {
          method: 'POST',
          headers: { ...J, 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'write_approval', params: { title: 'Change Acme Supplies to ****4410? UC234-ASSIST', why: 'The vendor asked by email', facts, call: { tool: 'update_vendor_bank', input: { vendor: 'Acme Supplies', account: '****4410' } } } }),
        });
        const task = (await posted.json()).data;
        if (posted.status !== 201) throw new Error(`opening the task answered ${posted.status}: ${JSON.stringify(task).slice(0, 300)}`);
        for (let i = 0; i < 60 && task.status !== 'waiting'; i++) {
          if ((await fetch(`${agents}/reviews/${encodeURIComponent(task.id)}`, { headers: J })).ok) break;
          await sleep(1000);
        }
        await page.goto(`${consoleUrl}${task.url}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const decide = page.getByTestId('task-decide');
        // The assist may still be written when the page opens (a pending region); the page reads it again until it lands.
        const shown = await decide.getByText('Worth checking').first().waitFor({ timeout: 90_000 }).then(() => true, () => false);
        const said = shown ? (await decide.innerText()).replace(/\s+/g, ' ') : '';
        const reject = page.getByTestId('option-decision-form').getByRole('button', { name: /Decline/ });
        const marked = await reject.getAttribute('data-suggested');
        const approveMarked = await page.getByTestId('option-decision-form').getByRole('button', { name: /Make the change/ }).getAttribute('data-suggested');
        // Nothing is chosen for the person: no reason row is open and no decision was sent.
        const reasonOpen = await page.getByTestId('option-reason').count();
        const state = (await (await fetch(`${agents}/v1/tasks/${task.id}`, { headers: J })).json()).data;
        await page.screenshot({ path: join(SHOTS, 'task-typed-assist-1280.png') });
        check(
          '11 with task assist on, the task shows the AI assist labelled as AI and marks its suggestion without choosing it',
          on.status === 200 && shown && /AI/.test(said) && /email/.test(said) && /New account/.test(said) && /Decline/.test(said) && marked === 'true' && approveMarked === null && reasonOpen === 0 && !state?.action,
          { policy: on.status, said: said.slice(0, 300), marked, approveMarked, reasonOpen, action: state?.action, regions: ((await (await fetch(`${agents}/reviews/${encodeURIComponent(task.id)}`, { headers: J })).json()).data?.task?.regions ?? []).map((r) => r.region), status: task.status },
        );
      });

      await step('12 Reject sends a read check back to a named person, or to the team queue when none is picked', async () => {
        const back = await readAndWait();
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(back.reviewId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('decide-reject').click();
        const picker = page.getByTestId('option-person-reject-assignee');
        await picker.waitFor({ timeout: 30_000 });
        const label = (await picker.locator('xpath=ancestor::*[@data-slot="form-item" or contains(@class,"flex-col")][1]').innerText().catch(() => '')).replace(/\s+/g, ' ');
        await picker.getByRole('button', { name: /Pick a person/ }).click();
        await page.getByPlaceholder('Search the team\'s people…').fill('maya');
        await page.getByRole('option', { name: /Maya Okafor/ }).first().click();
        await page.keyboard.press('Escape');
        await page.getByTestId('option-reason').fill('Maya knows this court');
        const posting = page.waitForResponse((res) => res.request().method() === 'POST' && /\/decision$/.test(res.url()), { timeout: 30_000 });
        await page.getByTestId('decide-reject').click();
        const answer = await posting;
        const sent = answer.request().postDataJSON();
        check(
          '12 Reject sends a read check back to a named person, or to the team queue when none is picked',
          answer.status() === 200 && sent?.decision === 'reject' && sent?.inputs?.assignee === 'm.okafor@northfieldbank.com' && /Send to/.test(label),
          { status: answer.status(), sent, label },
        );
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);
finish();
