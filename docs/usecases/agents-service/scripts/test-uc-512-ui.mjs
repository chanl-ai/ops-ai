// uc-512 a builder reads a workflow step in plain words and picks values from earlier steps by name, ui layer:
// docs/usecases/agents-service/step-sheet-plain-words.md, steps 6 to 17. Platform sign-in (James builds, Ravi views),
// a workflow worker this script starts, and the console. The sample route is slowed and failed in the browser only to
// draw the loading and error states. No model is called.
import fs from 'node:fs';
import path from 'node:path';

import { check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, saveAndPublish, settled, start, until } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const SHOTS = evidenceDir('uc-512');
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
    // Its close button, not Escape: Escape goes to whatever holds focus, which a closed picker may still have.
    await sheet.getByRole('button', { name: 'Close', exact: true }).click();
    await sheet.waitFor({ state: 'hidden', timeout: 10_000 }).catch(() => undefined);
  }
  await page.locator(`[data-testid="definition-node"][data-node-id="${id}"]`).dblclick();
  await page.getByTestId('step-sheet-body').waitFor({ timeout: 30_000 });
}

const sheetText = async (page) => (await page.getByTestId('step-sheet').innerText()).replace(/\s+/g, ' ');
// The sheet without the fields of other steps (What it receives, What it gives): those are data names, not the sheet's words.
const wordsOf = (page) =>
  page.evaluate(() => {
    const sheet = document.querySelector('[data-testid="step-sheet"]');
    const hidden = ['step-receives', 'step-what-it-gives'].map((id) => sheet.querySelector(`[data-testid="${id}"]`)).filter(Boolean);
    hidden.forEach((el) => { el.style.display = 'none'; });
    const text = sheet.innerText.replace(/\s+/g, ' ');
    hidden.forEach((el) => { el.style.display = ''; });
    return text;
  });
// Sheets and popovers slide and fade in; a screenshot waits for them to settle.
const shot = async (page, name) => {
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
// The page and the sheet's own scroller: the sheet is fixed, so the page alone could not show it overflowing.
const noSideScroll = (page) =>
  page.evaluate(() => {
    const body = document.querySelector('[data-testid="step-sheet"] .overflow-y-auto');
    const page = { scroll: document.documentElement.scrollWidth, width: window.innerWidth };
    const sheet = body ? { scroll: body.scrollWidth, width: body.clientWidth } : null;
    return { ok: page.scroll <= page.width && (!sheet || sheet.scroll <= sheet.width), page, sheet };
  });
// What reads as code to a builder: type ids, paths, Effects, the run call, an agent tool name and "input schema".
const leaks = (t) => ['ops.', '$.', 'Effects:', 'POST /v1/runs', 'workflow__', 'input schema'].filter((w) => t.toLowerCase().includes(w.toLowerCase()));
// Every kind of code word the sheet and its open lists must never show: type ids, paths, port words, schema words,
// backticks, operator codes, snake_case and camelCase names, an `[object Object]` and the scan's own step ids.
const CODE_WORDS = [
  /\bops\.[a-z]/i, /\$\./, /\bports?\b/i, /json/i, /\bschemas?\b/i, /`/, /\b(?:Eq|Ne|Gt|Gte|Lt|Lte)\b/, /\b(?:eq|ne|gt|gte|lt|lte)\b/,
  /\b[a-z]+_[a-z]+\b/, /\b[a-z]+[A-Z][a-zA-Z]+\b/, /\[object Object\]/, /zz\d\d/i, /\bnodes?\b/i, /\bnull\b/i, /\bpayloads?\b/i,
  /\{id, version\}/, /\bUTC\b/, /\btokens?\b/i, /\bchild(?:ren)?\b/i, /\bkeys?\b/i, /\b[a-z]+\([^)]*\)/, /\bregistry\b/i, /\bgateway\b/i,
  /does not match|is not valid|is not one of|is a required property|should not|\(\d+\.\w+\)/i,
];
// A list of choices must also show no id of an agent or another record (lowercase words joined by a hyphen).
const LIST_WORDS = [...CODE_WORDS, /\b[a-z]{3,}-[a-z]{3,}\b/];
const codeIn = (t, words = CODE_WORDS) => words.map((re) => re.exec(t)).filter(Boolean).map((m) => `${m[0]} in "${t.slice(Math.max(0, m.index - 40), m.index + 40)}"`);
const atWidths = async (page, name) => {
  const wide = await noSideScroll(page);
  await shot(page, `${name}-1440.png`);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const narrow = await noSideScroll(page);
  await shot(page, `${name}-390.png`);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(300);
  return { wide, narrow, ok: wide.ok && narrow.ok };
};

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
    // An Email received trigger whose daily cap breaks its rule (at least 1), so its sheet has a problem to fix.
    copy.nodes[0] = node('start', 'ops.trigger.email', 'Email in', { folder: 'inbox', dailyCap: 0 });
    // Done reads a step no longer in the workflow: its chip says Missing step.
    copy.nodes[2] = node('done', 'ops.flow.end', 'Done', { outcome: 'ok', output: '$.nodes.gone.out.total' });
    copy.nodes.push(node('loose', 'ops.data.set', 'Loose note', { values: { note: 'x' } }), node('ghost', 'ops.flow.teleport', 'Old step'), node('lookup', 'ops.action.tool', 'Look up the order'));
    // Each one wired, so the canvas lays it out; Loose note only leads into Done, so nothing runs before it.
    copy.connections.push(wire('fields', 'out', 'lookup'), wire('fields', 'out', 'ghost'), wire('loose', 'out', 'done'));
    const put = await fetch(`${agents}/v1/workflows/definitions/${C}/working-copy`, { method: 'PUT', headers: H, body: JSON.stringify({ definition: copy, baseVersion: cv.saveBase.version, baseDigest: cv.saveBase.digest }) });
    if (!c.live) throw new Error('setup: C did not go live');
    // E holds one step of every installed type, so the lists of every type can be opened. The tool step and the review
    // carry names, the rest the type's own name.
    const E = `uc512_all_${TAG}`;
    const e = await saveAndPublish(H, refund(E));
    const ev = (await (await fetch(`${agents}/v1/workflows/definitions/${E}`, { headers: H })).json()).data;
    const installed = (await (await fetch(`${agents}/v1/workflows/node-types`, { headers: H })).json()).data;
    const newest = [...new Map(installed.sort((x, y) => x.version - y.version).map((t) => [t.id, t])).values()].sort((x, y) => x.group.localeCompare(y.group) || x.id.localeCompare(y.id));
    const NAMED = { 'ops.action.tool': 'Pay the refund', 'ops.flow.humanReview': 'Check the refund', 'ops.ai.classify': 'Sort the mail', 'ops.data.match': 'Match payers', 'ops.ai.extract': 'Read the invoice', 'ops.flow.if': 'Check the amount' };
    // A value for a setting, from its schema: the first listed choice, one entry of a list, the required fields of an object.
    const sample = (sc) => {
      if (!sc || typeof sc !== 'object') return 'sample';
      const titled = (sc.oneOf ?? []).find((o) => o.const !== undefined);
      if (titled) return titled.const;
      if (sc.enum) return sc.enum[0];
      if (sc.anyOf) return sample(sc.anyOf[0]);
      if (sc.type === 'string') return sc.format === 'file' ? '$.input.amount' : 'sample';
      if (sc.type === 'number' || sc.type === 'integer') return Math.max(1, sc.minimum ?? 1);
      if (sc.type === 'boolean') return true;
      if (sc.type === 'array') return [sample(sc.items)];
      if (sc.type === 'object') return Object.fromEntries((sc.required ?? []).map((k) => [k, sample(sc.properties?.[k])]));
      return 'sample';
    };
    const filled = (t) => {
      const props = t.parameters.properties ?? {};
      const need = [...(t.parameters.required ?? [])];
      if (t.parameters.anyOf?.every((o) => o.required)) need.push(...t.parameters.anyOf[0].required);
      return Object.fromEntries(need.map((k) => [k, sample(props[k])]));
    };
    // Settings a person might mistype, to read what Problems say about them.
    const MISTYPED = {
      'ops.ai.classify': { categories: [{ name: 'otherwise' }, { name: 'billing' }] },
      'ops.data.match': { item: '$.input.amount', candidates: '$.input.amount', all: [{ left: '$.input.amount', op: 'equals', right: 'amount' }] },
      'ops.ai.extract': { file: '$.input.amount', read: '$.input.read', fields: [{ key: 'Bad Key', type: 'text' }] },
      // A tool the saved copy names that the list does not offer (a platform tool a system workflow uses).
      'ops.action.tool': { operation: 'apply_tool_access' },
      'ops.flow.if': { conditions: [{ left: 1, op: 'big' }] },
    };
    const every = refund(E);
    every.nodes = newest.map((t, i) => ({ ...node(`zz${String(i).padStart(2, '0')}`, t.id, NAMED[t.id], { ...filled(t), ...MISTYPED[t.id] }), typeVersion: t.version, position: { x: (i % 6) * 320, y: Math.floor(i / 6) * 200 } }));
    // One chain from the Request trigger through every step to End, each by its first way out, so every step has a step
    // before it and the field picker has something to list. The other triggers stand alone.
    const chain = every.nodes.filter((n) => n.type !== 'ops.trigger.request' && !n.type.startsWith('ops.trigger.') && n.type !== 'ops.flow.end');
    const order = [every.nodes.find((n) => n.type === 'ops.trigger.request'), ...chain, every.nodes.find((n) => n.type === 'ops.flow.end')];
    const firstOut = (n) => {
      const t = newest.find((x) => x.id === n.type);
      const list = t.outputsFrom ? n.parameters[t.outputsFrom] : undefined;
      if (Array.isArray(list) && list.length) return typeof list[0] === 'string' ? list[0] : list[0].name;
      return t.outputs[0]?.name ?? t.extraOutputs?.[0] ?? 'out';
    };
    every.connections = order.slice(0, -1).map((n, i) => wire(n.id, firstOut(n), order[i + 1].id));
    const putAll = await fetch(`${agents}/v1/workflows/definitions/${E}/working-copy`, { method: 'PUT', headers: H, body: JSON.stringify({ definition: every, baseVersion: ev.saveBase.version, baseDigest: ev.saveBase.digest }) });
    if (!e.live || !putAll.ok) throw new Error(`setup: E ${e.live} ${putAll.status}`);
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

      // 7. Text scan at 1440 and 390, on Done and on the Request trigger.
      const doneWidths = await atWidths(page, 'sheet-done');
      await openStep(page, 'start');
      const triggerText = await sheetText(page);
      const triggerWidths = await atWidths(page, 'sheet-trigger');
      const found = [...leaks(text), ...leaks(triggerText)];
      check('7 no type id, path, Effects, run call, tool name or "input schema" shows on Done or the trigger, and neither width scrolls sideways',
        found.length === 0 && doneWidths.ok && triggerWidths.ok, { found, doneWidths, triggerWidths });

      // 8. The trigger's own panel sits above Settings; the call and tool name wait behind Technical details.
      const top = async (id) => (await page.getByTestId(id).boundingBox())?.y ?? NaN;
      const how = await top('step-how-it-starts');
      const settings = await top('step-settings');
      await page.getByTestId('trigger-technical-toggle').click();
      const technical = await page.getByTestId('trigger-technical').innerText();
      check('8 How it starts shows on the trigger above Settings, and Technical details names the run call and tool', how < settings && technical.includes('POST /v1/runs') && technical.includes(`workflow__${A}`), { how, settings, technical });

      // 9. Use a field…: no match, then Fields → Amount.
      await openStep(page, 'done');
      const output = page.locator('[data-mapping="node-done-output"]');
      await output.getByTestId('field-picker-open').click();
      const picker = page.getByTestId('field-picker');
      await picker.getByPlaceholder('Search fields…').fill('zzzz');
      const none = await picker.getByText('Nothing matches.').isVisible().catch(() => false);
      await shot(page, 'picker-no-match-1440.png');
      await picker.getByPlaceholder('Search fields…').fill('amou');
      await shot(page, 'picker-results-1440.png');
      // The trigger gives an amount too; the one wanted is Fields'.
      await picker.locator('[cmdk-group]').filter({ hasText: 'Fields' }).getByRole('option').first().click();
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
      const givesError = await page.getByTestId('step-gives-error').isVisible();
      await shot(page, 'receives-error-1440.png');
      await page.locator('[data-mapping="node-done-output"]').getByTestId('field-picker-open').click();
      const pickerError = await page.getByTestId('field-picker-error').waitFor({ timeout: 10_000 }).then(() => true, () => false);
      await shot(page, 'picker-error-1440.png');
      // Its own button closes the picker; Escape could close the sheet as well.
      await page.locator('[data-mapping="node-done-output"]').getByTestId('field-picker-open').click();
      check('12 a failing sample shows its own error with Retry in What it receives, What it gives and the picker, while the Name field stays editable', failed && editable && givesError && pickerError, { failed, editable, givesError, pickerError });
      await page.unroute('**/sample?*');
      await page.getByTestId('step-receives-error').getByRole('button').first().click();
      const noRun = await page.getByTestId('step-receives-no-run').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await shot(page, 'receives-no-run-1440.png');
      check('13 a workflow that never ran says No run yet', noRun, { noRun });

      // 14-15, 17: a loose step, a type that is not installed and a tool step with no operation, in B's working copy.
      await page.route('**/sample?*', async (route) => {
        await new Promise((r) => setTimeout(r, 4000));
        await route.continue().catch(() => undefined);
      });
      await openEditor(page, consoleUrl, C);
      await openStep(page, 'loose');
      await page.getByTestId('step-settings').getByTestId('field-picker-open').first().click();
      const pickerLoading = await page.getByTestId('field-picker-loading').isVisible();
      await shot(page, 'picker-loading-1440.png');
      await page.getByTestId('step-settings').getByTestId('field-picker-open').first().click();
      await page.unroute('**/sample?*');
      check('11b the picker shows skeleton rows while the sample loads', pickerLoading, { pickerLoading });
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

      // 18. An Email received trigger with a problem: Problems, then How it starts, then Settings, at both widths.
      await openStep(page, 'start');
      const problems = await page.getByTestId('step-sheet-errors').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const order = [await top('step-sheet-errors'), await top('step-how-it-starts'), await top('step-settings')];
      const emailText = await sheetText(page);
      const emailWidths = await atWidths(page, 'sheet-email-trigger');
      check('18 an Email received trigger shows Problems, then How it starts, then Settings, in plain words, at 1440 and 390 with no sideways scroll',
        problems && order[0] < order[1] && order[1] < order[2] && /from a mailbox/i.test(emailText) && leaks(emailText).length === 0 && emailWidths.ok,
        { problems, order, leaks: leaks(emailText), emailWidths });

      // 19. A value read from a step that is gone shows as Missing step.
      await openStep(page, 'done');
      const missingChip = await page.locator('[data-mapping="node-done-output"]').getByTestId('field-chip').innerText().catch(() => '');
      await shot(page, 'chip-missing-step-1440.png');
      check('19 a value read from a step that is gone shows the Missing step chip', missingChip.includes('Missing step'), { missingChip });


      // 20. Every installed step type, opened one after the other with every list open: no code word anywhere.
      // The checks the editor shows come with the working copy (a save) or with a validation; the newest says which
      // setting each problem is about.
      let checksNow = [];
      page.on('response', async (r) => {
        if (!r.url().includes('/definitions/')) return;
        const body = await r.json().catch(() => undefined);
        const got = body?.data?.checks ?? body?.data?.workingCopy?.checks;
        if (Array.isArray(got) && (r.url().includes(E) || r.url().includes('/validate'))) checksNow = got;
      });
      await openEditor(page, consoleUrl, E);
      // Thirty-odd steps do not fit the canvas at a readable size, so each opens by a click event rather than a pointer.
      await page.locator('[data-testid="definition-node"][data-node-id="zz00"]').dispatchEvent('click');
      await page.getByTestId('step-sheet-body').waitFor({ timeout: 30_000 });
      const seen = [];
      const lists = {};
      const badFix = [];
      const problemsOf = {};

      // A control a step lacks must not hold the scan for the default half minute.
      page.setDefaultTimeout(4000);
      for (let i = 0; i < newest.length; i += 1) {
        const t = newest[i];
        const sheet = page.getByTestId('step-sheet');
        // Learn more, then one more row in every list the settings offer, then each list and the field picker.
        await sheet.getByTestId('step-how-it-works-open').click().catch(() => undefined);
        for (let round = 0; round < 2; round += 1) {
          const adds = sheet.getByTestId('step-settings').getByRole('button', { name: /^Add/ });
          // The count is taken once: a new row brings its own Add button, so reading it again never ends.
          const before = await adds.count();
          for (let k = 0; k < before; k += 1) await adds.nth(k).click().catch(() => undefined);
        }
        // The editor checks the draft a moment after each change.
        await page.waitForTimeout(1500);
        const found = [await wordsOf(page)];
        const names = await sheet.getByRole('combobox').count();
        for (let k = 0; k < names; k += 1) {
          const box = sheet.getByRole('combobox').nth(k);
          await box.scrollIntoViewIfNeeded().catch(() => undefined);
          // Read before opening: an open list hides the rest of the page from the accessibility tree.
          const field = (await box.getAttribute('data-field')) ?? '';
          // What the control shows before it opens is read like any option: a saved value reads in words too.
          const selected = ((await box.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
          const shownWords = codeIn(selected, LIST_WORDS);
          if (shownWords.length) seen.push({ type: t.id, hits: shownWords.map((w) => `selected value of ${field || k}: ${w}`).slice(0, 3) });
          await box.click();
          const list = page.getByRole('listbox');
          await list.waitFor({ timeout: 10_000 }).catch(() => undefined);
          // A searched list loads its choices after it opens.
          await page.waitForTimeout(600);
          const opened = await list.isVisible().catch(() => false);
          const options = (await list.getByRole('option').allInnerTexts().catch(() => [])).map((o) => o.replace(/\s+/g, ' ').trim());
          if (!opened || options.length === 0) seen.push({ type: t.id, hits: [`a list did not open or came back empty: ${field || k}`] });
          const words = codeIn(options.join(' | '), LIST_WORDS);
          if (words.length) seen.push({ type: t.id, hits: words.slice(0, 3).map((w) => `option of ${field || k}: ${w}`) });
          // Two entries a person cannot tell apart are no choice.
          const twins = options.filter((o, n) => options.indexOf(o) !== n);
          if (twins.length) seen.push({ type: t.id, hits: [`identical options in ${field || k}: ${[...new Set(twins)].slice(0, 3).join(' | ')}`] });
          lists[`${t.id}:${field.split('-').pop() || k}`] = options;
          found.push(options.join(' | '));
          await page.keyboard.press('Escape');
          await list.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => undefined);
        }
        const opener = sheet.getByTestId('field-picker-open').first();
        if (await opener.isVisible().catch(() => false)) {
          await opener.click();
          await page.getByTestId('field-picker').waitFor({ timeout: 10_000 }).catch(() => undefined);
          // The picker lists other steps' names and field names, which are data; only code words are scanned there.
          const pickerText = (await page.getByTestId('field-picker').innerText().catch(() => '')).replace(/\s+/g, ' ');
          const pickerHits = codeIn(pickerText, [CODE_WORDS[0], CODE_WORDS[1], /zz\d\d/i, /\[object Object\]/]);
          if (pickerHits.length) seen.push({ type: t.id, hits: pickerHits });
          await opener.click();
        }
        const hits = codeIn(found.join(' || '));
        if (hits.length) seen.push({ type: t.id, hits: hits.slice(0, 4) });
        // Every Fix lands on a field of the step, never on Name.
        const problemTexts = (await sheet.getByTestId('step-sheet-errors').locator('li').allInnerTexts().catch(() => [])).map((x) => x.replace(/\s+/g, ' '));
        const codeInProblems = codeIn(problemTexts.join(' || '));
        if (codeInProblems.length) seen.push({ type: t.id, problems: codeInProblems.slice(0, 3) });
        problemsOf[t.id] = problemTexts;
        for (let k = 0; k < problemTexts.length; k += 1) {
          const text = problemTexts[k].replace(/\s*Fix$/, '');
          const check = checksNow.find((c) => c.node === `zz${String(i).padStart(2, '0')}` && c.message === text);
          const fix = sheet.getByTestId('step-sheet-errors').locator('li').nth(k).getByTestId('step-problem-fix');
          const hasFix = (await fix.count()) > 0;
          if (!check) { badFix.push({ type: t.id, problem: text, why: 'no matching check from the editor' }); continue; }
          // A problem about a setting offers Fix and Fix reaches that setting; one about no setting offers none.
          if (!check.field) { if (hasFix) badFix.push({ type: t.id, problem: text, why: 'Fix offered for a problem with no setting' }); continue; }
          if (!hasFix) { badFix.push({ type: t.id, problem: text, why: `no Fix for the setting ${check.field}` }); continue; }
          await fix.click({ timeout: 5000 }).catch(() => undefined);
          await page.waitForTimeout(400);
          const want = `node-${check.node}-${check.field}`;
          const landed = await page.evaluate((w) => {
            const el = document.activeElement;
            return !!el && (el.id.startsWith(w) || (el.getAttribute('data-field') ?? '').startsWith(w) || !!el.closest(`[data-mapping^="${w}"], [data-testid^="${w}-rows"], [data-testid="step-settings"] [id^="${w}"]`));
          }, want);
          if (!landed) badFix.push({ type: t.id, problem: text, why: `Fix did not reach ${want}` });
        }
        // The next step opens by its own click: forty steps are not all on screen at a readable size.
        if (i < newest.length - 1) await (page.locator(`[data-testid="definition-node"][data-node-id="zz${String(i + 1).padStart(2, '0')}"]`).dispatchEvent('click'));
        await page.waitForTimeout(250);
      }
      page.setDefaultTimeout(30_000);
      await shot(page, 'every-type-last-1440.png');
      fs.writeFileSync(path.join(SHOTS, 'every-type-lists.json'), JSON.stringify({ lists, seen, badFix }, null, 2));
      check(`20 every one of ${newest.length} step types opened with every list open shows no type id, path, port, schema, operator code or snake_case word`, seen.length === 0, seen.slice(0, 12));
      check('20b every problem about a setting offers Fix and Fix reaches that setting, and a problem about no setting offers none', badFix.length === 0, badFix.slice(0, 6));

      // 20c. Mistyped settings read as one plain problem each that names the step and the setting.
      const MIS = { 'ops.ai.classify': ['Sort the mail', 'Categories'], 'ops.data.match': ['Match payers', 'Record field'], 'ops.ai.extract': ['Read the invoice', 'Fields'], 'ops.flow.if': ['Check the amount', 'Is'] };
      const mis = Object.entries(MIS).map(([type, [step, setting]]) => {
        const all = problemsOf[type] ?? [];
        const about = all.filter((x) => x.includes(setting));
        // One problem per wrong value, each naming the step; a wrong choice reads as one problem, not two.
        const choice = type === 'ops.flow.if' ? all.filter((x) => /must be one of|accepts/.test(x)).length === 1 : true;
        return { type, step, setting, about, ok: about.length >= 1 && choice && about.every((x) => x.includes(step) && codeIn(x).length === 0) };
      });
      check('20c a mistyped category, rule field, field key or choice reads as one plain problem naming the step and the setting', mis.every((m) => m.ok), mis.filter((m) => !m.ok));

      // 21. The lists offer plain words and only what fits: Approves lists tool steps by name, Approved by lists
      // reviews, the operator list reads in words.
      const only = (key) => Object.entries(lists).find(([k]) => k === key)?.[1] ?? [];
      const approves = only('ops.flow.humanReview:approves');
      const approvedBy = only('ops.action.tool:approvedBy');
      const operators = Object.entries(lists).filter(([k]) => k.startsWith('ops.flow.if:')).flatMap(([, v]) => v).join(' | ');
      check('21 Approves offers only the tool step by its name, Approved by only the review, and an If condition offers its operators in words',
        approves.length === 2 && approves[1].startsWith('Pay the refund') && approvedBy.length === 2 && approvedBy[1].startsWith('Check the refund') && /Equal to/.test(operators) && !/\bEq\b/.test(operators), { approves, approvedBy, operators });

      // 22. Friction: the review says it waits, Classify categories carry no review wording.
      const openFar = async (type) => {
        await page.locator(`[data-testid="definition-node"][data-node-id="zz${String(newest.findIndex((t) => t.id === type)).padStart(2, '0')}"]`).dispatchEvent('click');
        await page.waitForTimeout(500);
      };
      await openFar('ops.flow.humanReview');
      const reviewText = await sheetText(page);
      await openFar('ops.ai.classify');
      const classifyText = await sheetText(page);
      check('22 the review does not say it gives up after seconds or tries once, and Classify categories offer no Authorises choice',
        !/Gives up after \d+ seconds/.test(reviewText) && !/It tries once/.test(reviewText) && !/Authorises/.test(classifyText), { review: reviewText.slice(reviewText.indexOf('When it fails'), reviewText.indexOf('When it fails') + 300), classify: /Authorises[^|]*/.exec(classifyText)?.[0] });

      // 16. Ravi, a viewer: no Delete, no picker, fields disabled.
      const viewer = await signIn(browser, consoleUrl, RAVI);
      await openEditor(viewer, consoleUrl, A);
      await openStep(viewer, 'done');
      const del = await viewer.getByTestId('definition-node-delete').count();
      const pick = await viewer.getByTestId('field-picker-open').count();
      const disabled = !(await viewer.locator('#definition-node-name').isEditable());
      await shot(viewer, 'viewer-1440.png');
      // Opening a step, even by a double click, must not zoom the canvas.
      await viewer.waitForTimeout(900);
      const frame = await viewer.evaluate(() => {
        const sheet = document.querySelector('[data-testid="step-sheet"]')?.getBoundingClientRect();
        const done = document.querySelector('[data-testid="definition-node"][data-node-id="done"]')?.getBoundingClientRect();
        const first = document.querySelector('[data-testid="definition-node"]')?.getBoundingClientRect();
        return { nodeWidth: Math.round(first?.width ?? 0), openedClear: !!done && !!sheet && done.left >= 0 };
      });
      check('16b a viewer opening a step by double click leaves the zoom as it was (a step is 288 px wide at full size)', frame.nodeWidth <= 300 && frame.openedClear, frame);
      await viewer.setViewportSize({ width: 390, height: 844 });
      await viewer.waitForTimeout(500);
      const viewerNarrow = await noSideScroll(viewer);
      await shot(viewer, 'viewer-390.png');
      check('16 a viewer sees no Delete and no field picker, and cannot change a field, with no sideways scroll at 390', del === 0 && pick === 0 && disabled && viewerNarrow.ok, { del, pick, disabled, viewerNarrow });
      if (errors.length) console.log('page errors', errors.slice(0, 3));
    } finally {
      await browser.close();
      await worker.stop();
    }
  },
  // tools-service with the gateway serves the Call a tool operations and the app picker the sheet lists.
  { platform: true, tools: { gateway: true } },
);
finish();
