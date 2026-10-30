// uc-254 a builder copies a task type and an API caller opens typed Human Tasks, ui layer:
// docs/usecases/agents-service/typed-human-tasks.md. James copies write_approval with its own question and publishes
// it (the console has no task-type editor, so through the API as the api script does); an API caller opens a task on
// it, and the type moves on to v2. Priya, the team's admin, opens the task in Human Tasks: it asks v1's question with
// its facts, offers the type's actions in order with their consequences, and she declines it with a reason the caller
// reads back. Platform sign-in, no model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, agents, as, until } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const TYPE = `vendor_bank_change_${TAG}`;
const FACTS = [{ label: 'Vendor', value: 'Acme Supplies' }, { label: 'New account', value: '****4410' }];
const V1_QUESTION = 'Change the bank account for Acme Supplies to ****4410?';
const REASON = `Call the vendor first ${TAG}`;

const call = async (method, path, headers, body) => {
  const r = await fetch(`${agents}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    await stack.startWorker();
    const seed = (await call('GET', '/v1/task-types/write_approval', J)).data?.versions?.[0]?.record;
    const made = await call('POST', '/v1/task-types', J, {
      id: TYPE,
      copyOf: { id: 'write_approval' },
      name: `Vendor bank change ${TAG}`,
      params: { ...seed.params, properties: { ...seed.params.properties, vendor: { type: 'string' }, account: { type: 'string' } }, required: ['vendor', 'account', 'call'] },
      regions: [{ region: 'header', bind: { title: 'Change the bank account for {vendor} to {account}?' } }, ...seed.regions.slice(1)],
    });
    const published = await call('POST', `/v1/task-types/${TYPE}/publish`, J, { version: 1 });
    const posted = await call('POST', '/v1/tasks', J, { type: TYPE, params: { vendor: 'Acme Supplies', account: '****4410', facts: FACTS } });
    const task = posted.data ?? {};
    const v2 = (await call('GET', `/v1/task-types/${TYPE}`, J)).data?.versions?.[0]?.record ?? {};
    await call('PUT', `/v1/task-types/${TYPE}/draft`, J, { ...v2, regions: [{ region: 'header', bind: { title: 'New bank details for {vendor}' } }, ...(v2.regions ?? []).slice(1)] });
    const moved = await call('POST', `/v1/task-types/${TYPE}/publish`, J, { version: 2 });
    check(
      '1 James copies and publishes the type, a task opens on v1, and the type moves on to v2',
      made.status === 201 && published.status === 200 && posted.status === 201 && task.version === 1 && moved.status === 200,
      { made: made.status, published: published.status, posted: posted.status, version: task.version, moved: moved.status },
    );

    const browser = await chromium.launch();
    const errors = [];
    try {
      // A reviewer or admin of the team decides a task; Priya is the team's admin.
      const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(task.id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const panel = page.getByTestId('decision-panel');
      await panel.waitFor({ timeout: 60_000 });
      await panel.getByTestId('task-decide').waitFor({ timeout: 30_000 });
      const shown = (await panel.innerText()).replace(/\s+/g, ' ');
      check(
        "2 Human Tasks asks v1's question with the task's facts, not v2's",
        shown.includes(V1_QUESTION) && !shown.includes('New bank details') && shown.includes('Acme Supplies') && shown.includes('****4410'),
        shown.slice(0, 400),
      );

      const options = await panel.locator('label[data-testid^="option-"]').evaluateAll((els) =>
        els.map((e) => ({ name: e.getAttribute('data-testid').slice('option-'.length), text: e.textContent?.replace(/\s+/g, ' ').trim() })),
      );
      check(
        "3 it offers the type's actions in order, each with its consequence",
        options.length === 2 && options[0].text.includes('Make the change') && options[0].text.includes('The change is made now.') && options[1].text.includes('Decline') && options[1].text.includes('Nothing changes.'),
        options,
      );

      const decline = options[1]?.name ?? 'reject';
      const sent = page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 60_000 }).then((r) => r.status(), () => 0);
      await panel.getByTestId(`option-${decline}`).click();
      await panel.getByTestId('option-reason').fill(REASON);
      await panel.getByTestId('decide').click();
      const status = await sent;
      const state = await until(async () => {
        const r = await call('GET', `/v1/tasks/${task.id}`, J);
        return r.status === 200 && r.data?.action ? r.data : undefined;
      }, 30);
      check(
        '4 Priya declines it with a reason, and the caller reads the action, reason and decider',
        status === 200 && state?.action === 'reject' && state?.reason === REASON && state?.decidedBy === PRIYA,
        { status, action: state?.action, reason: state?.reason, decidedBy: state?.decidedBy },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
