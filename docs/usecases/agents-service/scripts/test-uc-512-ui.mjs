// uc-512 a builder reads a workflow step in plain words and picks values from earlier steps by name, ui layer:
// docs/usecases/agents-service/step-sheet-plain-words.md, steps 6 to 17. Platform sign-in (James builds, Ravi views),
// a workflow worker this script starts, and the console. The sample route is slowed and failed in the browser only to
// draw the loading and error states. No model is called.
import fs from 'node:fs';
import path from 'node:path';

import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, saveAndPublish, settled, start, until } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const SHOTS = process.env.OPS_UC_SHOTS ?? path.resolve('.logs/usecases/512/shots');
fs.mkdirSync(SHOTS, { recursive: true });

const node = (id, type, name, parameters = {}) => ({ id, type, typeVersion: 1, name, parameters });
const wire = (a, port, b) => ({ from: { node: a, port }, to: { node: b, port: 'in' } });
const refund = (id) => ({
  schemaVersion: 2,
  id,
  name: `Refund check ${id}`,
  nodes: [
    node('start', 'ops.trigger.request', 'Refund asked', { inputSchema: { type: 'object', properties: { amount: { type: 'number' }, customer: { type: 'string' } } } }),
    node('fields', 'ops.data.set', 'Fields', { values: { amount: '$.input.amount', contact: '$.input.customer' } }),
    node('done', 'ops.flow.end', 'Done', { outcome: 'ok' }),
  ],
  connections: [wire('start', 'payload', 'fields'), wire('fields', 'out', 'done')],
});

async function signIn(browser, consoleUrl, email, width = 1440) {
  const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function openEditor(page, consoleUrl, id) {
  await page.goto(`${consoleUrl}/build/workflows/definitions/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('definition-node').first().waitFor({ timeout: 90_000 });
}

async function openStep(page, id) {
  // The sheet may sit over the step to open next, so it closes first.
  const sheet = page.getByTestId('step-sheet');
  if (await sheet.isVisible().catch(() => false)) {
    await page.keyboard.press('Escape');
    await sheet.waitFor({ state: 'hidden', timeout: 10_000 }).catch(() => undefined);
  }
  await page.locator(`[data-testid="definition-node"][data-node-id="${id}"]`).dblclick();
  await page.getByTestId('step-sheet-body').waitFor({ timeout: 30_000 });
}

const sheetText = async (page) => (await page.getByTestId('step-sheet').innerText()).replace(/\s+/g, ' ');
// Sheets and popovers slide and fade in; a screenshot waits for them to settle.
const shot = async (page, name) => {
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

await withUiStack(
  async (consoleUrl, stack) => {
    let H = await as(JAMES);
    const A = `uc512_${TAG}`;
    const B = `uc512_norun_${TAG}`;
    const a = await saveAndPublish(H, refund(A));
    const b = await saveAndPublish(H, refund(B));
    // C carries a loose step, a type that is not installed and a tool step with no operation in its working copy,
    // saved before the editor first opens it.
    const C = `uc512_copy_${TAG}`;
    const c = await saveAndPublish(H, refund(C));
    const cv = (await (await fetch(`${agents}/v1/workflows/definitions/${C}`, { headers: H })).json()).data;
    const copy = refund(C);
    copy.nodes.push(node('loose', 'ops.data.set', 'Loose note', { values: { note: 'x' } }), node('ghost', 'ops.flow.teleport', 'Old step'), node('lookup', 'ops.action.tool', 'Look up the order'));
    // Each one wired, so the canvas lays it out; Loose note only leads into Done, so nothing runs before it.
    copy.connections.push(wire('fields', 'out', 'lookup'), wire('fields', 'out', 'ghost'), wire('loose', 'out', 'done'));
    const put = await fetch(`${agents}/v1/workflows/definitions/${C}/working-copy`, { method: 'PUT', headers: H, body: JSON.stringify({ definition: copy, baseVersion: cv.saveBase.version, baseDigest: cv.saveBase.digest }) });
    if (!c.live) throw new Error('setup: C did not go live');
    const worker = await stack.startWorker();
    const first = await settled(H, await start(H, A, { amount: 42, customer: 'alex.moreau@harborpine.example' }));
    if (!a.live || !b.live || first?.status !== 'succeeded') throw new Error(`setup: ${JSON.stringify({ a: a.asked?.status, b: b.asked?.status, run: first?.status })}`);

    const browser = await chromium.launch();
    try {
      const page = await signIn(browser, consoleUrl, JAMES);
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await openEditor(page, consoleUrl, A);

      // 6. Done in plain words, with what it receives from the run.
      await openStep(page, 'done');
      const receives = page.getByTestId('step-receives');
      await receives.getByText('42', { exact: true }).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const text = await sheetText(page);
      check('6 Done reads in plain words: its summary, the Fields values from the run with the email masked, when it fails and what it gives',
        /Ends the workflow/.test(text) && (await receives.innerText()).includes('42') && !text.includes('alex.moreau') && (await page.getByTestId('step-when-it-fails').isVisible()) && (await page.getByTestId('step-what-it-gives').isVisible()),
        text.slice(0, 600));
      await shot(page, 'sheet-done-1440.png');

      // 7. Text scan at 1440 and 390.
      const leaks = (t) => ['ops.', '$.', 'Effects:'].filter((w) => t.includes(w));
      const wide = await noSideScroll(page);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(500);
      const narrow = await noSideScroll(page);
      await shot(page, 'sheet-done-390.png');
      await page.setViewportSize({ width: 1440, height: 1000 });
      check('7 no type id, path or Effects shows in the sheet, and neither width scrolls sideways', leaks(text).length === 0 && wide && narrow, { leaks: leaks(text), wide, narrow });

      // 8. The trigger's own panel sits under Problems and above Settings.
      await openStep(page, 'start');
      const top = async (id) => (await page.getByTestId(id).boundingBox())?.y ?? NaN;
      const how = await top('step-how-it-starts');
      const settings = await top('step-settings');
      check('8 How it starts shows on the trigger, above Settings', how < settings, { how, settings });
      await shot(page, 'sheet-trigger-1440.png');

      // 9. Use a field…: no match, then Fields → Amount.
      await openStep(page, 'done');
      const output = page.locator('[data-mapping="node-done-output"]');
      await output.getByTestId('field-picker-open').click();
      const picker = page.getByTestId('field-picker');
      await picker.getByPlaceholder('Search fields…').fill('zzzz');
      const none = await picker.getByText('Nothing matches.').isVisible().catch(() => false);
      await shot(page, 'picker-no-match-1440.png');
      await picker.getByPlaceholder('Search fields…').fill('fields.out.amount');
      await shot(page, 'picker-results-1440.png');
      await picker.getByRole('option').first().click();
      const chip = await output.getByTestId('field-chip').innerText().catch(() => '');
      check('9 the picker says Nothing matches for a miss and puts Fields → Amount as a chip with its sample', none && chip.includes('Fields → Amount') && chip.includes('42'), { none, chip });

      // 10. The picked path is saved, published and read by the next run. A slow machine can outlast the first token.
      H = await as(JAMES);
      const view = await until(async () => {
        const v = (await (await fetch(`${agents}/v1/workflows/definitions/${A}`, { headers: H })).json()).data;
        const done = v?.workingCopy?.definition?.nodes?.find((n) => n.id === 'done');
        return done?.parameters?.output === '$.nodes.fields.out.amount' ? v : undefined;
      }, 60);
      const base = view?.saveBase ?? {};
      const pub = await fetch(`${agents}/v1/workflows/definitions/${A}/publish-requests`, { method: 'POST', headers: H, body: JSON.stringify({ note: 'Output from Fields', baseVersion: base.version, baseDigest: base.digest }) });
      const next = await settled(H, await start(H, A, { amount: 57, customer: 'kim@harborpine.example' }));
      check('10 the next run reads the picked field: its output is the amount it was given', !!view && pub.ok && next?.status === 'succeeded' && Number(next?.output) === 57, { saved: !!view, publish: pub.status, run: next?.status, output: next?.output });

      // 11. Loading: the sample answers slowly.
      await page.route('**/sample?*', async (route) => {
        await new Promise((r) => setTimeout(r, 4000));
        await route.continue().catch(() => undefined);
      });
      await openStep(page, 'fields');
      const loading = await page.getByTestId('step-receives-loading').isVisible();
      await shot(page, 'receives-loading-1440.png');
      await page.unroute('**/sample?*');
      check('11 What it receives shows skeleton rows while the sample loads', loading, { loading });

      // 12. Error: the sample fails; Settings stay usable; Retry reads it again. 13. No run yet on B.
      await page.route('**/sample?*', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'internal', message: 'Down', status: 500 } }) }));
      await openEditor(page, consoleUrl, B);
      await openStep(page, 'done');
      const failed = await page.getByTestId('step-receives-error').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const editable = await page.locator('#definition-node-name').isEditable();
      await shot(page, 'receives-error-1440.png');
      check('12 a failing sample shows its own error with Retry while the Name field stays editable', failed && editable, { failed, editable });
      await page.unroute('**/sample?*');
      await page.getByTestId('step-receives-error').getByRole('button').first().click();
      const noRun = await page.getByTestId('step-receives-no-run').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await shot(page, 'receives-no-run-1440.png');
      check('13 a workflow that never ran says No run yet', noRun, { noRun });

      // 14-15, 17: a loose step, a type that is not installed and a tool step with no operation, in B's working copy.
      await openEditor(page, consoleUrl, C);
      await openStep(page, 'loose');
      const firstStep = await page.getByTestId('step-receives').getByText('This is the first step').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('14 a step nothing runs before says This is the first step', put.ok && firstStep, { put: put.status, firstStep });
      await openStep(page, 'ghost');
      const missing = await page.getByTestId('step-not-installed').isVisible();
      const locked = !(await page.locator('#definition-node-name').isEditable());
      await shot(page, 'not-installed-1440.png');
      check("15 a step whose type is not installed says so and its settings are read-only", missing && locked, { missing, locked });
      await openStep(page, 'lookup');
      const fix = page.getByTestId('step-problem-fix').first();
      const hasFix = await fix.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      if (hasFix) await fix.click();
      await page.waitForTimeout(800);
      const focused = await page.evaluate(() => document.activeElement?.id || document.activeElement?.getAttribute('data-field') || '');
      await shot(page, 'problems-fix-1440.png');
      check('17 Fix on a problem focuses the field it names', hasFix && focused.includes('lookup'), { hasFix, focused });

      // 16. Ravi, a viewer: no Delete, no picker, fields disabled.
      const viewer = await signIn(browser, consoleUrl, RAVI);
      await openEditor(viewer, consoleUrl, A);
      await openStep(viewer, 'done');
      const del = await viewer.getByTestId('definition-node-delete').count();
      const pick = await viewer.getByTestId('field-picker-open').count();
      const disabled = !(await viewer.locator('#definition-node-name').isEditable());
      await shot(viewer, 'viewer-1440.png');
      check('16 a viewer sees no Delete and no field picker, and cannot change a field', del === 0 && pick === 0 && disabled, { del, pick, disabled });
      if (errors.length) console.log('page errors', errors.slice(0, 3));
    } finally {
      await browser.close();
      await worker.stop();
    }
  },
  { platform: true },
);
finish();
