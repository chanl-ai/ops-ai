// uc-224 a person corrects a document read in Human Tasks, ui layer: docs/usecases/agents-service/a-person-corrects-a-document-read.md.
// The demo stack with platform sign-in and a worker. James uploads a faxed levy notice to Files and starts the mailed
// document workflow on it, as the mailbox trigger does for each attachment. The fake model misreads the debtor's name,
// so the read stops at Check the read. Maya opens it in Human Tasks, sees the file, each field's confidence and page
// quote, corrects the name and approves; the levy case starts on her value, and the acknowledgement shows the reply.
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const NOTICE = readFileSync(join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice_smudged.pdf'));
const SEED = Object.fromEntries(JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).map((w) => [w.id, w]));
const SENDER = 'registry@court.example';
const MAILBOX = 'intake@harborpine.test';

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, type = 'application/json') => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': type });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 90_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

async function publish(headers, id) {
  const { teamId: _team, ...definition } = SEED[id];
  const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers, body: JSON.stringify({ definition }) });
  const live = await fetch(`${agents}/v1/workflows/definitions/${id}/publish-requests`, { method: 'POST', headers, body: '{}' });
  return `${saved.status}/${live.status}/${(await live.json()).data?.status}`;
}

// The demo stack seeds and publishes both workflows, so saving or publishing answers 409 here (saving a draft of a live
// workflow is allowed, so the 409 can come from either call); a fresh database gets them published by this call.
/** A person's upload, as the Files page makes it: a ticket, the bytes, then complete. */
async function upload(headers, name, bytes) {
  const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/pdf' }, body: bytes });
  return json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers }));
}

const runs = async (headers, workflowId) => (await json(await fetch(`${agents}/v1/runs?workflowId=${workflowId}&pageSize=50`, { headers }))).data;
const run = async (headers, id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers }));

await withUiStack(
  async (consoleUrl, stack) => {
    // The worker reads the uploaded file from the run's files-service, as the shared stack's worker does.
    await stack.startWorker({ OPS_FILES_URL: files });
    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = as(await tokenFor(JAMES));
      const maya = as(await tokenFor(MAYA));
      const published = [await publish(james, 'levy_case'), await publish(james, 'mail_document')];
      const { file } = await upload(james, 'levy_notice_smudged.pdf', NOTICE);
      const started = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'mail_document', input: { fileId: file?.id, name: 'levy_notice_smudged.pdf', from: SENDER, subject: 'Levy notice', mailbox: MAILBOX } }) }));
      const waiting = await until(async () => {
        const r = await run(james, started.runId);
        return r.status === 'waiting' || ['succeeded', 'failed', 'cancelled'].includes(r.status) ? r : null;
      });
      check('1 setup: the workflows are published and the faxed notice stops at Check the read', published.every((p) => p.endsWith('/approved') || p.split('/').includes('409')) && waiting?.waiting?.node === 'check', { published, file: file?.id, status: waiting?.status, outcome: waiting?.outcome, at: waiting?.waiting?.node, error: waiting?.error, steps: (waiting?.steps ?? []).map((x) => [x.node, x.port, JSON.stringify(x.output ?? {}).slice(0, 300)]) });

      // Human Tasks opens a task beside its queue (no side sheet), so the task's text is read from the page's main area.
      // Step 2: Maya opens it in Human Tasks and sees the file, the fields and which one needs a check.
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await page.goto(`${consoleUrl}/reviews?review=${started.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const read = page.getByTestId('document-read');
      await read.waitFor({ timeout: 120_000 });
      const fileName = await page.getByTestId('read-file-link').innerText();
      const nameRow = page.getByTestId('read-field-0-name');
      const flagged = await nameRow.getAttribute('data-needs-review');
      const nameRowText = await nameRow.innerText();
      const others = await page.locator('[data-testid^="read-field-0-"][data-needs-review="true"]').count();
      const raw = (await page.locator('main').innerText()).includes('"records"');
      const subtitle = await page.getByTestId('review-run-link').innerText();
      const runHref = await page.getByTestId('review-run-link').getAttribute('href');
      const returnable = await page.getByTestId('review-decision-form').getByRole('button', { name: /^Return/ }).count();
      const amount = await page.getByTestId('read-input-0-amount').inputValue();
      check(
        '2 the check shows the file, each field with its confidence and page quote, and only the misread name marked',
        fileName.includes('levy_notice_smudged.pdf') && flagged === 'true' && others === 1 && /Check/.test(nameRowText) && /0%/.test(nameRowText) && nameRowText.includes('p. 1') && !raw,
        { fileName, flagged, others, nameRowText, raw },
      );
      check(
        '2b the sheet names the workflow, its version and the step and links the run, offers no Return on a workflow step, and shows money to two decimals',
        /^Mailed document v\d+ · Check the read/.test(subtitle) && runHref === `/workflows/runs/${started.runId}` && returnable === 0 && amount === '100.00',
        { subtitle, runHref, returnable, amount },
      );

      // The card's evidence: the check at desktop and phone width.
      const shots = evidenceDir('169');
      mkdirSync(shots, { recursive: true });
      await page.locator('main').screenshot({ path: join(shots, 'read-check-1280.png') });
      await page.setViewportSize({ width: 400, height: 900 });
      await page.locator('main').screenshot({ path: join(shots, 'read-check-400.png') });
      await page.setViewportSize({ width: 1440, height: 1000 });

      // Step 3: she corrects the name and approves; the case starts on her value.
      await page.getByTestId('read-input-0-name').fill('Ana Example');
      const marked = await page.getByTestId('read-corrected-0-name').innerText();
      const decided = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes('/reviews/') && r.url().endsWith('/decision'), { timeout: 60_000 });
      // The read check is a typed document_check task: it decides by its type's own Approve, picked and then sent with
      // Decide in the task's panel.
      await page.getByTestId('option-approve').click();
      await page.getByTestId('decide').click();
      const response = await decided;
      const sent = response.request().postDataJSON();
      const levy = await until(async () => (await runs(james, 'levy_case')).find((r) => r.input?.record?.name) ?? null);
      check(
        '3 corrected and approved: the decision sends the whole read with her name, and the levy case starts on it',
        response.status() === 200 && marked.includes('Anna Exempel') && sent?.inputs?.edited?.[0]?.values?.name === 'Ana Example' && sent.inputs.edited[0].values.case_no === 'NS-2026-GN-09999' && levy?.input?.record?.name === 'Ana Example',
        { status: response.status(), marked, sent: sent?.inputs, levy: levy?.input?.record },
      );

      // Step 3b: the decided task leaves her queue and the queue opens the next one (c-460); 3c shows who decided it.
      const left = await page.waitForFunction((id) => !document.querySelector(`[data-testid^="queue-item-${id}"]`), started.runId, { timeout: 30_000 }).then(() => true, () => false);
      const now = new URL(page.url()).searchParams.get('review');
      check('3b after deciding, the task leaves her queue and the next task opens', left && now !== started.runId, { left, now });

      // Step 3c: the run keeps the decision: who, when and why, linked to the task it was made on.
      await page.goto(`${consoleUrl}/workflows/runs/${started.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const decisions = page.getByTestId('run-decisions');
      // The step's name comes from the run's pinned definition, which loads beside the run.
      const decisionsShown = await decisions.getByText(/Check the read/).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const decisionText = decisionsShown ? (await decisions.innerText()).replace(/\s+/g, ' ') : '';
      const taskHref = decisionsShown ? await decisions.getByRole('link').first().getAttribute('href') : null;
      check(
        '3c the run page lists the decision with the person, when, and a link to the task',
        decisionsShown && /Check the read/.test(decisionText) && /Approve by Maya Okafor/.test(decisionText) && /(just now|\dm ago)/.test(decisionText) && new RegExp(`^/reviews/${started.runId}%3Acheck%3A\\d+$`).test(taskHref ?? ""),
        { decisionText, taskHref },
      );

      // Step 4: the acknowledgement shows the reply as it will leave and the levy case run it follows.
      const ack = await until(async () => {
        const r = await run(james, started.runId);
        return r.waiting?.node === 'ack' ? r : null;
      });
      await page.goto(`${consoleUrl}/reviews?review=${started.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Human Tasks opens the task beside its queue as its page draws it: the question, the email and reply, who and from
      // where, the cases.
      const sheet = page.locator('main');
      await sheet.getByTestId('task-decide').waitFor({ timeout: 120_000 });
      const sheetText = (await sheet.innerText()).replace(/\s+/g, ' ');
      const listed = await sheet.getByTestId('task-decide').getByRole('link', { name: 'Open case' }).count();
      check(
        '4 the acknowledgement shows who the reply goes to, from which mailbox, and the case it covers',
        !!ack && sheetText.includes(`Send the acknowledgement to ${SENDER}?`) && new RegExp(`To ${SENDER.replace(/[.+]/g, '\\$&')}`).test(sheetText) && new RegExp(`From ${MAILBOX.replace(/[.+]/g, '\\$&')}`).test(sheetText) && listed === 1,
        { at: ack?.waiting?.node, sheet: sheetText.slice(0, 500), listed },
      );

      // The acknowledgement opened from its own address (c-289), which Human Tasks now opens beside its queue (c-460):
      // the question, the reply as it will leave, the cases. The question, body and footer are the decision panel's.
      const taskShots = join(ROOT, 'docs/console/proposed/tasks');
      mkdirSync(taskShots, { recursive: true });
      await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(started.runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const ackQuestion = await page.getByTestId('decision-question').innerText();
      await page.getByTestId('decision-body').waitFor({ timeout: 60_000 });
      const ackEvidence = await page.getByTestId('decision-body').innerText();
      // Whoever the step lets decide sees its type's buttons; the page is the same for everyone else, with who decides.
      const ackFooter = (await page.getByTestId('decision-footer').innerText()).replace(/\s+/g, ' ');
      let who = null;
      for (const [email, team] of [['m.okafor@harborpine.example', 'team_ops'], ['p.shah@harborpine.example', 'team_ops'], ['n.petrov@harborpine.example', 'team_security'], ['o.haddad@harborpine.example', 'team_fraud'], ['w.kamau@harborpine.example', 'team_platform']]) {
        const signed = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data?.token;
        const seen = await fetch(`${agents}/reviews/${encodeURIComponent(started.runId)}`, { headers: { Authorization: `Bearer ${signed}`, 'X-Team-Id': team } });
        if (seen.ok && (await seen.json()).data?.canDecide) {
          who = email;
          break;
        }
      }
      const decider = await consoleSignIn(browser, consoleUrl, who ?? 'p.shah@harborpine.example', PASSWORD, errors);
      await decider.goto(`${consoleUrl}/reviews/${encodeURIComponent(started.runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await decider.getByTestId('decision-footer').waitFor({ timeout: 60_000 });
      await decider.getByTestId('option-decision-form').waitFor({ timeout: 30_000 }).catch(() => undefined);
      // The panel lists each option as a labelled choice (option-<name>); Decide sends the one picked.
      const ackButtons = await decider.getByTestId('option-decision-form').locator('[data-testid^="option-"]:not([data-testid="option-reason"])').allInnerTexts();
      await decider.close();
      const caseLinks = await page.getByTestId('task-decide').getByRole('link').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.screenshot({ path: join(taskShots, 'task-acknowledgement-1280.png') });
      await page.setViewportSize({ width: 400, height: 800 });
      await page.screenshot({ path: join(taskShots, 'task-acknowledgement-400.png') });
      await page.setViewportSize({ width: 1440, height: 1000 });
      check('4b as a page the acknowledgement asks whether to send it to its sender, shows the email and the reply, and decides by Send or Do not send', ackQuestion === `Send the acknowledgement to ${SENDER}?` && /We received your document/.test(ackEvidence) && ackButtons.some((b) => /^Send/.test(b)) && ackButtons.some((b) => /Do not send/.test(b)) && caseLinks.every((h) => /^\/cases\//.test(h ?? '')), { ackQuestion, ackEvidence: ackEvidence.slice(0, 120), ackButtons, ackFooter, caseLinks, who });

      // The levy case's own Human Task as a page (c-289): one plain question naming both choices, the notice beside it,
      // and a footer that is one row saying what each choice does. No tool name, raw key or raw float on the page.
      // The corrected debtor is no bank customer, so that case ends unmatched; the same notice for a customer the bank
      // has (name and last four of the SSN) reaches the hold-or-flag step.
      const matched = await json(
        await fetch(`${agents}/v1/runs`, {
          method: 'POST',
          headers: { ...james, 'Content-Type': 'application/json' },
          body: JSON.stringify({ workflowId: 'levy_case', input: { ...levy.input, record: { ...levy.input.record, name: 'Marcus Bell', ssn_last4: '4471', amount: 3250 } } }),
        }),
      );
      const held = await until(async () => {
        const r = await run(james, matched.runId);
        return r.status === 'waiting' && r.waiting ? r : null;
      }, 120_000);
      if (!held) {
        const r = await run(james, matched.runId);
        throw new Error(`4c: the levy case never waited for a person: ${r.status} / ${r.outcome} / ${JSON.stringify(r.error ?? null).slice(0, 300)} / steps ${JSON.stringify((r.steps ?? []).map((x) => [x.node ?? x.id, x.status]).slice(-6))}`);
      }
      const heldId = `${matched.runId}:${held.waiting.node}:${held.waiting.iteration}`;
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(heldId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const heldTitle = await page.getByTestId('decision-question').innerText();
      // The notice sits beside the panel, in the task's own column.
      const viewer = await page.locator('main').getByTestId('document-viewer').first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      // Each choice is a labelled option whose second line says what it does; the footer holds Decide and Reassign.
      const options = await page.getByTestId('option-decision-form').locator('[data-testid^="option-"]:not([data-testid="option-reason"])').allInnerTexts();
      const footerHeight = (await page.getByTestId('decision-footer').boundingBox())?.height ?? 0;
      const secondSays = (options[1] ?? '').split('\n').slice(1).join(' ').trim();
      const shown = [heldTitle, await page.getByTestId('task-decide').innerText(), await page.getByTestId('decision-footer').innerText()].join('\n');
      const rawText = shown.match(/\b[a-z]+_[a-z_]+\b|\d\.0\b|\{'/);
      await page.screenshot({ path: join(taskShots, 'task-held-action-1280.png') });
      await page.setViewportSize({ width: 400, height: 800 });
      await page.screenshot({ path: join(taskShots, 'task-held-action-400.png') });
      await page.setViewportSize({ width: 1440, height: 1000 });
      check(
        '4c the levy case asks one plain question with the notice beside it, and each choice says what it does',
        /\?$/.test(heldTitle) && viewer && options.length >= 2 && footerHeight > 0 && secondSays.length > 2 && !rawText,
        { heldTitle, viewer, options, footerHeight, secondSays, raw: rawText?.[0] },
      );

      // The mailed document's run started a levy case for each debtor read (c-209): its page lists each one with its
      // status, and the workflow's canvas says the step repeats and over what.
      await page.goto(`${consoleUrl}/workflows/runs/${encodeURIComponent(started.runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const children = page.getByTestId('run-children');
      const childrenShown = await children.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const childLinks = childrenShown ? await children.locator('a').evaluateAll((els) => els.map((e) => e.getAttribute('href'))) : [];
      const childStatus = childrenShown ? await page.getByTestId('run-child-0').innerText() : '';
      // The canvas draws after the run's lists, so wait for its line before reading it.
      await page.getByTestId('node-repeats').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      // A long line drops what it repeats over on the canvas and keeps it in its title, which this reads.
      const repeats = await page.getByTestId('node-repeats').evaluateAll((els) => els.map((e) => e.getAttribute('title') || e.textContent || ''));
      const eachShots = evidenceDir('306');
      mkdirSync(eachShots, { recursive: true });
      if (childrenShown) await page.getByTestId('run-children').screenshot({ path: join(eachShots, 'run-children-1280.png') });
      await page.locator('[data-testid="node-repeats"]').first().screenshot({ path: join(eachShots, 'node-repeats-1280.png') });
      check(
        '4d the run lists the levy case it started for the debtor with its status, and the canvas says the step runs for each debtor read',
        childrenShown && childLinks.some((h) => h === `/workflows/runs/${encodeURIComponent(levy.id)}` || h === `/workflows/runs/${levy.id}`) && childStatus.length > 0 && repeats.some((t) => /^for each \w+ from /i.test(t.trim())),
        { childLinks, childStatus, repeats },
      );

      // Step 6: a notice naming three debtors reads as three records, one tab each, each with its own fields.
      // A read with Name always for review, so a clean notice naming three debtors still waits for a person.
      const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: { ...james, 'Content-Type': 'application/json' }, body: JSON.stringify({ yaml: JSON.stringify({"schemaVersion": 2, "id": "uc224_three", "name": "Three debtors", "nodes": [{"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Document", "parameters": {"inputSchema": {"type": "object", "properties": {"fileId": {"type": "string", "format": "file"}, "name": {"type": "string"}}}}}, {"id": "read", "type": "ops.ai.extract", "typeVersion": 1, "name": "Read the debtors", "parameters": {"file": "$.input.fileId", "many": true, "fields": [{"key": "name", "label": "Name", "type": "text", "required": true, "alwaysReview": true}, {"key": "address", "label": "Address", "type": "text"}, {"key": "ssn_last4", "label": "SSN last four", "type": "text"}, {"key": "amount", "label": "Amount", "type": "money"}, {"key": "currency", "label": "Currency", "type": "text"}, {"key": "court", "label": "Court", "type": "text"}, {"key": "case_no", "label": "Case number", "type": "text"}]}}, {"id": "check", "type": "ops.flow.humanReview", "typeVersion": 1, "name": "Check the read", "parameters": {"title": "Check the debtors read from the document", "summary": {"document": "$.input.name", "read": "$.nodes.read.out"}, "editable": "$.nodes.read.out.records"}}, {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "done"}}, {"id": "manual", "type": "ops.flow.end", "typeVersion": 1, "name": "Manual", "parameters": {"outcome": "manual"}}], "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}}, {"from": {"node": "read", "port": "ok"}, "to": {"node": "check", "port": "in"}}, {"from": {"node": "read", "port": "review"}, "to": {"node": "check", "port": "in"}}, {"from": {"node": "read", "port": "unreadable"}, "to": {"node": "manual", "port": "in"}}, {"from": {"node": "read", "port": "error"}, "to": {"node": "manual", "port": "in"}}, {"from": {"node": "check", "port": "approve"}, "to": {"node": "done", "port": "in"}}, {"from": {"node": "check", "port": "reject"}, "to": {"node": "manual", "port": "in"}}]}) }) });
      if (saved.status >= 300 && saved.status !== 409) throw new Error(`step 6: saving the read workflow answered ${saved.status}: ${(await saved.text()).slice(0, 300)}`);
      const scan = await upload(james, 'levy_notice.pdf', readFileSync(join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice.pdf')));
      const three = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'uc224_three', mode: 'test', input: { fileId: scan.file?.id, name: 'levy_notice.pdf' } }) }));
      const at = await until(async () => {
        const r = await run(james, three.runId);
        return r.waiting || ['succeeded', 'failed', 'cancelled'].includes(r.status) ? r : null;
      });
      if (at?.waiting?.node !== 'check') throw new Error(`step 6: the read did not wait at the check: ${JSON.stringify({ status: at?.status, waiting: at?.waiting?.node, outcome: at?.outcome, error: at?.error, run: three })}`.slice(0, 500));
      await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(three.runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const tabs = page.getByTestId('read-record-tabs');
      const tabbed = await tabs.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const names = tabbed ? (await tabs.getByRole('tab').allInnerTexts()).map((t) => t.trim()) : [];
      if (tabbed) await page.getByTestId('read-record-tab-1').click();
      const second = tabbed ? await page.getByTestId('read-record-1').isVisible() : false;
      const firstHidden = tabbed ? !(await page.getByTestId('read-record-0').isVisible().catch(() => false)) : false;
      // At 1280 the record's table fits its pane: the Source column wraps instead of being cut off.
      await page.setViewportSize({ width: 1280, height: 800 });
      const overflow = await page.getByTestId('read-record-1').evaluate((el) => [...el.querySelectorAll('table')].map((t) => t.parentElement.scrollWidth - t.parentElement.clientWidth));
      await page.screenshot({ path: join(ROOT, 'docs/console/proposed/tasks/task-read-check-records-1280.png') });
      await page.setViewportSize({ width: 1440, height: 1000 });
      check('6b at 1280 each record table fits its pane, Source included', overflow.length > 0 && overflow.every((d) => d <= 1), { overflow });
      check('6 a notice naming three debtors reads as one tab per record, showing one record at a time', names.length === 3 && second && firstHidden, { names, second, firstHidden, records: await page.locator('[data-testid^="read-record-"]').count(), title: await page.getByTestId('decision-question').innerText().catch(() => ''), body: (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300) });

      check('5 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
