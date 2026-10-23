// uc-086 a builder takes a bank API from import to a governed agent call, ui layer: docs/usecases/console/import-to-governed-call.md.
// Signed in through platform-service as the seeded people. tools-service reaches the core-banking fake on https, which
// checks a header key on most routes and a query key on its statement route; the agents service (scripted model, no
// provider) takes its tools from tools-service. Each step is checked on its own, so one failing step still lets the
// later ones report.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const AGENT = 'ag_branch';
const ACCOUNT = 'CHQ-2219';
// The fake bank's key (FAKE_BANK_KEY's default); both secrets hold it, so a wrong or missing one is refused with 401.
const BANK_KEY = 'dev-bank-key';
const JAMES = 'j.richardson@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
// Egress and secrets are changed only by an admin of the Security team (c-079).
const SAM = 's.adeyemi@harborpine.example';
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const headers = async (email, team = 'team_ops') => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const get = async (path, email = JAMES) => (await (await fetch(`${tools}${path}`, { headers: await headers(email) })).json()).data;

/** Runs one step; a throw fails that step's check with the error and leaves the next steps to run. */
async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 300));
    return undefined;
  }
}

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function chat(page, consoleUrl, text) {
  await page.goto(`${consoleUrl}/chat?agent=${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByLabel('Message');
  await box.waitFor({ timeout: 120_000 });
  await box.fill(text);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  await page.locator('button[aria-label="Send"]').click();
  const res = await sent;
  // The reply streams; wait for its end, but never past 60 s, so a stream that stays open cannot hang the run.
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
  return res;
}

/** Runs one operation from its workbench's test panel (c-088) against the test environment; the response and what was
 * sent. */
async function tryOperation(page, consoleUrl, moduleId, op, fields) {
  await page.goto(`${consoleUrl}/tools/${moduleId}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const panel = page.getByTestId('module-test-panel');
  await panel.waitFor({ timeout: 120_000 });
  await panel.getByRole('radio', { name: 'Test environment' }).or(panel.getByRole('button', { name: 'Test environment' })).first().click();
  for (const [k, v] of Object.entries(fields)) await panel.locator(`#t-${k}`).fill(v);
  const ran = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/test`), { timeout: 60_000 }));
  await panel.getByRole('button', { name: 'Run' }).click();
  const res = await ran;
  return { status: res?.status(), sent: JSON.parse(res?.request().postData() ?? '{}'), data: res ? ((await res.json().catch(() => ({}))).data ?? {}) : {} };
}

/** The bank's own record of the account, read through the gateway as the owner's test call does. */
async function holdsOn(moduleId, contextId) {
  const res = await fetch(`${tools}/v1/tool-modules/${moduleId}/test`, { method: 'POST', headers: await headers(JAMES), body: JSON.stringify({ operation: 'get_account', contextId, target: 'sandbox', input: { account_id: ACCOUNT } }) });
  const out = (await res.json()).data?.output;
  return Array.isArray(out?.holds) ? out.holds : undefined;
}


// Grants each operation through the agent page's tools picker (EntityPicker, c-135): open, search, pick.
async function grantTools(page, ops) {
  const picker = page.getByTestId('agent-tools-picker');
  for (const op of ops) {
    await picker.getByRole('button', { name: 'Grant tools' }).click({ timeout: 120_000 });
    await page.getByPlaceholder('Search tools by name or system…').fill(op);
    await page.getByRole('option', { name: new RegExp(`^${op}\\b`) }).first().click({ timeout: 60_000 });
    await page.keyboard.press('Escape');
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    const errors = [];
    let moduleId;
    let ownerContext;
    let thread;

    // 1. The Security admin allows the bank's host and the private range it serves on.
    await step('1 Sam allows the bank host and range', async () => {
      const P = await headers(SAM, 'team_security');
      const host = await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.host, note: 'uc-086' }) });
      const range = await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.range, note: 'uc-086' }) });
      check('1 Sam allows the bank host and range', host.status === 201 && range.status === 201, { host: host.status, range: range.status });
    });

    const james = await signIn(browser, consoleUrl, JAMES, errors);

    // 2. The bank's two keys go in as secrets; no response, list or page shows a value again (T002).
    await step('2 Sam adds the bank keys as secrets in Settings', async () => {
      const sam = await signIn(browser, consoleUrl, SAM, errors);
      const made = [];
      for (const name of ['BANK_API_KEY', 'STATEMENTS_API_KEY']) {
        await sam.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        // The page header and the empty list both offer Add secret; either opens the same dialog.
        await sam.getByRole('button', { name: 'Add secret' }).first().click({ timeout: 120_000 });
        const dialog = sam.getByRole('dialog', { name: 'Add a secret' });
        await dialog.locator('#secret-name').fill(name);
        await dialog.locator('#secret-value').fill(BANK_KEY);
        const saved = armed(sam.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/secrets'), { timeout: 60_000 }));
        await dialog.getByTestId('secret-submit').click();
        const res = await saved;
        made.push({ name, status: res?.status(), leaked: (await res?.text())?.includes(BANK_KEY) });
      }
      await sam.getByText('STATEMENTS_API_KEY').first().waitFor({ timeout: 30_000 });
      const page = await sam.locator('main').innerText();
      check('2 Sam adds the bank keys as secrets in Settings', made.every((m) => m.status === 201 && !m.leaked) && !page.includes(BANK_KEY), made);
    });

    // 3. Import (T001): reads preselected, the write opt-in, the statement left for a later version; each operation
    // carries the reference its security scheme names, the header key or the query key.
    await step('3 James imports the bank spec and saves the draft', async () => {
      await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('import-operations').click({ timeout: 120_000 });
      const dialog = james.getByRole('dialog', { name: 'Import operations' });
      await dialog.waitFor({ timeout: 30_000 });
      await dialog.getByText('OpenAPI', { exact: false }).first().click();
      await dialog.locator('#spec-url').fill(`https://${stack.bank.host}/openapi.json`);
      await dialog.getByRole('button', { name: 'Next' }).click();
      await dialog.getByLabel('Access for get_account').waitFor({ timeout: 60_000 });
      await dialog.locator('#op-place_hold').click();
      await dialog.locator('#op-get_statement').click();
      const saved = armed(james.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/tool-modules$/.test(r.url()), { timeout: 60_000 }));
      await dialog.getByRole('button', { name: 'Save draft' }).click();
      const res = await saved;
      const made = res?.ok() ? (await res.json()).data : null;
      moduleId = made?.id;
      const ops = Object.fromEntries((made?.operations ?? []).map((o) => [o.name, o]));
      check(
        '3 James imports the bank spec and saves the draft',
        res?.status() === 201 && ops.get_account?.access === 'read' && ops.place_hold?.access === 'write' && !ops.get_statement,
        { status: res?.status(), module: moduleId, access: Object.fromEntries(Object.entries(ops).map(([k, o]) => [k, o.access])) },
      );
    });

    // 4. Security review (T004): James requests it on the module page; Nadia follows its link to Human Tasks, where
    // every review is decided (c-163), and approves it there; it publishes.
    await step('4 Nadia approves the review in Human Tasks and it publishes', async () => {
      await james.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('header-request-review').click({ timeout: 120_000 });
      const asked = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/reviews`), { timeout: 60_000 }));
      await james.getByRole('dialog', { name: 'Request a security review' }).getByRole('button', { name: 'Request review' }).click();
      const requested = await asked;
      const nadia = await signIn(browser, consoleUrl, NADIA, errors);
      await nadia.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await nadia.getByRole('tab', { name: /^Approval/ }).click({ timeout: 120_000 });
      await nadia.getByRole('link', { name: 'Open in Human Tasks' }).click({ timeout: 60_000 });
      // c-204: before deciding, the review shows what it approves: its operations, the host they reach, and a link
      // to the module itself.
      const panel = nadia.getByTestId('tool-module-review');
      await panel.waitFor({ timeout: 120_000 });
      const operations = await panel.getByTestId('review-operations').innerText().catch(() => '');
      const hosts = await panel.getByTestId('review-hosts').innerText().catch(() => '');
      const link = await panel.getByTestId('review-module-link').getAttribute('href').catch(() => null);
      check(
        '4a (c-204) the review lists its operations and new host and links to the module',
        /Added/.test(operations) && hosts.includes(stack.bank.host) && link === `/tools/${moduleId}`,
        { operations: operations.slice(0, 300), hosts, link },
      );
      const decided = armed(nadia.waitForResponse((r) => r.request().method() === 'POST' && /\/reviews\/[^/]+\/decision$/.test(r.url()), { timeout: 60_000 }));
      await nadia.getByRole('button', { name: 'Approve and publish' }).click({ timeout: 120_000 });
      const res = await decided;
      const body = await get(`/v1/tool-modules/${moduleId}`);
      check('4 Nadia approves the review in Human Tasks and it publishes', requested?.status() === 200 && res?.status() === 200 && body?.status === 'published', { request: requested?.status(), decide: res?.status(), status: body?.status });
    });

    // 5. A new operation, imported into the published module, is a major version: James publishes it, Nadia approves
    // it in Human Tasks, and only then is it served (T004, c-163).
    await step('5 James imports get_statement, publishes a version and Nadia approves it', async () => {
      await james.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('ops-import').click({ timeout: 120_000 });
      const dialog = james.getByRole('dialog', { name: /^Import operations into/ });
      await dialog.getByText('OpenAPI', { exact: false }).first().click();
      await dialog.locator('#spec-url').fill(`https://${stack.bank.host}/openapi.json`);
      await dialog.getByRole('button', { name: 'Next' }).click();
      await dialog.getByLabel('Access for get_statement').waitFor({ timeout: 60_000 });
      // Operations the module already has are listed as in it, never selected or counted (c-073 T007); the new read
      // starts selected.
      const inModule = await dialog.getByTestId('op-in-module-get_account').getByText('In this module').count();
      const ownTicked = await dialog.locator('#op-get_account').getAttribute('data-state');
      const ticked = await dialog.locator('#op-get_statement').getAttribute('data-state');
      check('5a the module\'s own operations show as in it and are not selected', inModule === 1 && ownTicked !== 'checked' && ticked === 'checked', { inModule, ownTicked, ticked });
      if (ticked !== 'checked') await dialog.locator('#op-get_statement').click();
      const imported = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/operations/import`), { timeout: 60_000 }));
      await dialog.getByTestId('import-save').click();
      const imp = await imported;
      await james.getByRole('button', { name: 'Publish version' }).click({ timeout: 60_000 });
      const confirm = james.getByRole('dialog', { name: /^Publish a (minor|major) version\?/ });
      await confirm.waitFor({ timeout: 30_000 });
      const promised = /major/.test((await confirm.getByRole('heading').first().innerText().catch(() => '')) || '') ? 'major' : 'minor';
      await confirm.locator('#pub-note').fill('Statements from the legacy statements service');
      const published = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/versions`), { timeout: 60_000 }));
      await confirm.getByRole('button', { name: 'Publish' }).click();
      const pub = await published;
      const version = pub ? (await pub.json()).data : undefined;
      const nadia = await signIn(browser, consoleUrl, NADIA, errors);
      await nadia.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await nadia.getByRole('tab', { name: /^Approval/ }).click({ timeout: 120_000 });
      await nadia.getByRole('link', { name: 'Open in Human Tasks' }).click({ timeout: 60_000 });
      const decided = armed(nadia.waitForResponse((r) => r.request().method() === 'POST' && /\/reviews\/[^/]+\/decision$/.test(r.url()), { timeout: 60_000 }));
      await nadia.getByRole('button', { name: 'Approve and publish' }).click({ timeout: 120_000 });
      const approved = await decided;
      await james.reload({ waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByRole('tab', { name: /^Versions/ }).click({ timeout: 60_000 });
      const listed = await james.getByText('Statements from the legacy statements service').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const detail = await get(`/v1/tool-modules/${moduleId}`);
      const statement = detail?.operations?.find((o) => o.name === 'get_statement');
      const v2 = (detail?.versions ?? []).find((v) => v.version === '2.0.0');
      // A new operation is reviewed by Security (publish makes it major); the dialog must say so before James publishes.
      check('5b the publish dialog names the version kind publish makes', promised === 'major' && version?.version === '2.0.0', { dialog: promised, made: version?.version });
      check(
        '5 James imports get_statement, publishes a version and Nadia approves it',
        imp?.status() === 200 && pub?.status() === 200 && approved?.status() === 200 && listed && v2?.status === 'published' && statement && !statement.input.some((f) => f.name === 'api_key'),
        { import: imp?.status(), publish: pub?.status(), version: version?.version, approve: approved?.status(), listed, versions: (detail?.versions ?? []).map((v) => `${v.version} ${v.status}`), statementInputs: statement?.input?.map((f) => f.name) },
      );
    });

    // 6. The owner tries the reads against the bank with no workflow approval: the header key and the query key are
    // both resolved at call time (T003), and the key the statement route repeats back comes out scrubbed.
    await step('6 James runs get_account and get_statement against the bank from the test panel', async () => {
      const account = await tryOperation(james, consoleUrl, moduleId, 'get_account', { account_id: ACCOUNT });
      ownerContext = account.sent.contextId;
      const statement = await tryOperation(james, consoleUrl, moduleId, 'get_statement', { account_id: ACCOUNT });
      const url = String(statement.data.output?.requestedUrl ?? '');
      check(
        '6 James runs get_account and get_statement against the bank from the test panel',
        account.status === 200 && account.data.stubbed === false && account.data.output?.id === ACCOUNT && statement.status === 200 && statement.data.output?.period === '2026-09' && url.includes('api_key=[secret]') && !JSON.stringify(statement.data).includes(BANK_KEY),
        { account: { status: account.status, stubbed: account.data.stubbed, id: account.data.output?.id, error: account.data.output?.error }, statement: { status: statement.status, url, error: statement.data.output?.error } },
      );
    });

    // 7. Grant the three operations to Branch Concierge, save the draft and publish it.
    await step('7 James grants the operations to Branch Concierge and publishes it', async () => {
      await james.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await grantTools(james, ['get_account', 'get_statement', 'place_hold']);
      await james.getByTestId('unsaved-bar').getByRole('button', { name: /^Save as v/ }).click();
      const patched = armed(james.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${AGENT}`, { timeout: 60_000 }));
      await james.getByRole('dialog', { name: /^Save as v/ }).getByRole('button', { name: /^Save v/ }).click();
      const patchRes = await patched;
      const saved = patchRes ? (await patchRes.json()).data : undefined;
      await james.getByTestId('request-agent-publish').click({ timeout: 60_000 });
      const publish = james.getByRole('dialog', { name: /^(Request publish of|Publish) v/ });
      await publish.getByLabel('What changed').fill('Core banking operations');
      const requested = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${AGENT}/publish-requests`), { timeout: 60_000 }));
      await publish.getByRole('button', { name: /^(Request publish|Publish)$/ }).click();
      const pubRes = await requested;
      const review = pubRes ? (await pubRes.json()).data : undefined;
      const held = saved?.toolIds ?? [];
      check('7 James grants the operations to Branch Concierge and publishes it', patchRes?.status() === 200 && ['get_account', 'get_statement', 'place_hold'].every((t) => held.includes(t)) && pubRes?.status() === 201 && review?.status === 'approved', { patch: patchRes?.status(), toolIds: held, publish: pubRes?.status(), review: review?.status });
    });

    // 8. A chat read runs through the gateway on the agent's grant (T005).
    await step('8 a chat read runs get_account through the gateway', async () => {
      await chat(james, consoleUrl, `call get_account {"account_id": "${ACCOUNT}"}`);
      const replied = await james.getByText('Here is what I found.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const calls = ((await get(`/v1/tool-modules/${moduleId}/activity`))?.recent ?? []).filter((c) => c.target === 'get_account' && c.status === 'ok' && c.actor?.kind === 'agent');
      check('8 a chat read runs get_account through the gateway', replied && calls.length === 1, { replied, agentCalls: calls.length });
    });

    // 9. A chat write waits for an approval and sends nothing (T006).
    let before;
    await step('9 a chat write holds for approval and reaches nothing', async () => {
      before = await holdsOn(moduleId, ownerContext);
      await chat(james, consoleUrl, `call place_hold {"account_id": "${ACCOUNT}", "amount": 25, "reason": "uc-086 suspected fraud"}`);
      thread = /\/chat\/([^/?#]+)/.exec(james.url())?.[1];
      // The card waits on a reviewer; James asked for the write, so he is offered no Approve on it (c-123 canDecide).
      const card = await james.getByTestId('approval-waiting-on').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const selfApprove = await james.getByRole('button', { name: /^Approve/ }).count();
      const sent = ((await get(`/v1/tool-modules/${moduleId}/activity`))?.recent ?? []).filter((c) => c.target === 'place_hold');
      const after = await holdsOn(moduleId, ownerContext);
      check('9 a chat write holds for approval and reaches nothing', card && selfApprove === 0 && sent.length === 0 && before !== undefined && after?.length === before.length, { card, selfApprove, calls: sent.length, holdsBefore: before?.length, holdsAfter: after?.length, thread });
    });

    // 10. An approver on the module's team decides it in Reviews; the write reaches the bank once (T006).
    await step('10 Maya approves the held write in Reviews and the bank holds it once', async () => {
      const maya = await signIn(browser, consoleUrl, MAYA, errors);
      await maya.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = maya.getByRole('row').filter({ hasText: 'place_hold' }).first();
      if (!(await row.waitFor({ timeout: 60_000 }).then(() => true, () => false))) throw new Error('the held chat write is not listed in Reviews');
      await row.click();
      const form = maya.getByTestId('review-decision-form');
      await form.waitFor({ timeout: 30_000 });
      const decided = armed(maya.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 60_000 }));
      await form.getByRole('button', { name: 'Approve', exact: true }).click();
      const res = await decided;
      // The approval resumes the conversation, which then makes the call; give it a moment to land.
      let ran = [];
      for (let i = 0; i < 15 && ran.length === 0; i++) {
        ran = ((await get(`/v1/tool-modules/${moduleId}/activity`))?.recent ?? []).filter((c) => c.target === 'place_hold' && c.status === 'ok');
        if (ran.length === 0) await new Promise((r) => setTimeout(r, 2_000));
      }
      const after = await holdsOn(moduleId, ownerContext);
      const added = (after ?? []).filter((h) => !(before ?? []).some((b) => b.id === h.id));
      const refused = ((await get(`/v1/tool-modules/${moduleId}/activity`))?.recent ?? []).filter((c) => c.target === 'place_hold' && c.status === 'denied');
      check(
        '10 Maya approves the held write in Reviews and the bank holds it once',
        res?.status() === 200 && ran.length === 1 && added.length === 1 && added[0].amount === 25,
        { decision: res?.status(), runs: ran.length, holdsAdded: added, refused: refused.map((c) => c.denyReason) },
      );
    });

    // 11. The module's call log names who asked, who approved and how each call ended (T007).
    await step('11 the Activity tab shows actor, decision and outcome for each call', async () => {
      await james.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const loaded = armed(james.waitForResponse((r) => r.request().method() === 'GET' && r.url().endsWith(`/v1/tool-modules/${moduleId}/activity`), { timeout: 60_000 }));
      await james.getByRole('tab', { name: /^Activity/ }).click({ timeout: 60_000 });
      const res = await loaded;
      const recent = res ? ((await res.json()).data?.recent ?? []) : [];
      const write = recent.find((c) => c.target === 'place_hold' && c.status === 'ok');
      const writeRow = james.getByTestId(`execution-row-${write?.id}`);
      await writeRow.waitFor({ timeout: 30_000 });
      const text = await writeRow.innerText();
      const runLink = await writeRow.getByRole('link').first().getAttribute('href').catch(() => null);
      check(
        '11 the Activity tab shows actor, decision and outcome for each call',
        // The person who asked is not on the row yet: the caller is the verified agents service until the runner signs
        // a run context naming the user (the data gateway's run context, planned).
        !!write && /m\.okafor@harborpinebank\.com/.test(text) && /via ag_branch/.test(text) && /Succeeded/.test(text) && runLink === `/chat/${thread}`,
        { row: text.replace(/\s+/g, ' ').slice(0, 300), runLink, thread, approval: write?.approval, subject: write?.subject, actor: write?.actor },
      );
    });

    // 12. No page error anywhere, and the key never reached a page.
    await step('12 no page errors and no key on any page', async () => {
      check('12 no page errors and no key on any page', errors.length === 0 && !(await james.content()).includes(BANK_KEY), errors);
    });
    await browser.close();
  },
  { platform: true, tools: { bank: 'core', gateway: true } },
);

finish();
