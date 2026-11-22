// uc-762 ui layer: docs/usecases/agents-service/a-builder-tries-one-skill-path.md. James opens a skill that reads an
// account and freezes it if open, presses Try, runs the open path: the read answers from the bank, the freeze shows as a
// plan naming the live account and is not sent; Show steps lists the gateway's steps; Send sends it once. Screenshots
// at 1440 and 390 wide. Platform sign-in, the fake bank on https, no model call.
import { AGENTS_PORT, TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, as, until } from '../../lib/workflow_ui.mjs';

const NADIA = 'n.petrov@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 7);
const READ = `get_account_${RUN}`;
const WRITE = `freeze_account_${RUN}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const call = async (method, url, headers, body) => {
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

await withUiStack(
  async (consoleUrl, stack) => {
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-762' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-762' });
    const J = await as(JAMES);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Accounts ${RUN}`, name: `accounts-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    const url = `https://${stack.bank.host}/v1/accounts/{accountId}`;
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: READ, description: 'Read an account', access: 'read', method: 'GET', url });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: WRITE, description: 'Freeze an account', access: 'write', method: 'POST', url: `${url}/holds` });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-762' });
    await approveToolReview(moduleId, await as(NADIA, 'team_security'), J);
    await until(async () => ((await call('GET', `${agents}/v1/tools/options?search=${WRITE}`, J)).data?.data ?? []).some((o) => o.id === WRITE), 60);
    const skill = await call('POST', `${agents}/v1/skills`, J, {
      name: `Freeze an open account ${RUN}`,
      ownerTeam: 'team_ops',
      useWhen: 'A customer reports a lost card.',
      instructions: '',
      exit: { closed: 'The account is already closed' },
      steps: [
        { do: `Look up the account with @tool:${READ}.`, use: { kind: 'tool', id: READ }, branch: { test: { text: 'result.status == "open"' }, otherwise: { exit: 'closed' } } },
        { do: `Freeze it with @tool:${WRITE}.`, use: { kind: 'tool', id: WRITE }, check: { text: 'result.ok == true' } },
      ],
    });
    check('setup: James saves the skill (201)', skill.status === 201, JSON.stringify(skill.data ?? {}).slice(0, 200));
    const sent = async () => ((await call('GET', `${tools}/v1/executions?tool=${WRITE}`, J)).data?.data ?? []).filter((c) => c.outcome === 'ok').length;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const dir = evidenceDir('uc-762');
      await page.goto(`${consoleUrl}/build/skills/${skill.data?.id}`, { waitUntil: 'domcontentloaded' });
      await page.getByTestId('skill-open-try').click();
      await page.getByTestId('try-panel').waitFor({ timeout: 60_000 });
      check('1 Try opens the side panel with the skill\'s paths and an account picker', await page.getByTestId('try-path').isVisible() && (await page.getByTestId('try-account-app').count()) === 1);
      await page.screenshot({ path: `${dir}/try-open-1440.png`, fullPage: false });
      await page.getByTestId('try-path').click();
      await page.getByRole('option', { name: /result.status == "open": yes/ }).click();
      // A builder types the values each step sends, as a person would.
      for (const box of await page.locator('textarea[id^="try-values-"]').all()) await box.fill('{"accountId": "CHQ-2219"}');
      await page.getByTestId('try-run').click();
      // Both tool steps answer (a result or an error) before the plan is read, so a failure prints what the panel says.
      await page.waitForFunction(() => document.querySelectorAll('[data-testid^="try-result-"], [data-testid="try-error"]').length >= 2, null, { timeout: 60_000 }).catch(() => undefined);
      if (!(await page.getByTestId('try-plan').count())) {
        await page.screenshot({ path: `${dir}/try-failed-1440.png`, fullPage: true });
        throw new Error(`no plan; the panel says: ${(await page.getByTestId('try-panel').innerText()).replace(/\s+/g, ' ').slice(0, 1200)}`);
      }
      const plan = (await page.getByTestId('try-plan').innerText()).replace(/\s+/g, ' ');
      check('2 the read ran for real and the freeze is a plan on the live account, not sent', (await page.getByTestId('try-result-ran').count()) === 1 && /Would send POST .*\/holds/.test(plan) && /live account/.test(plan) && (await sent()) === 0, plan.slice(0, 300));
      await page.getByTestId('try-show-steps').last().click();
      await page.screenshot({ path: `${dir}/try-planned-1440.png`, fullPage: true });
      await page.getByTestId('try-confirm').click();
      await page.getByTestId('try-result-sent').waitFor({ timeout: 60_000 });
      check('3 Send live sends the freeze once', (await sent()) === 1, await sent());
      await page.screenshot({ path: `${dir}/try-sent-1440.png`, fullPage: true });
      await page.setViewportSize({ width: 390, height: 900 });
      await page.screenshot({ path: `${dir}/try-sent-390.png`, fullPage: true });
      const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      check('4 at 390 wide the page does not scroll sideways', !wide);
    } finally {
      await browser.close();
    }
    check('5 no page errors', errors.length === 0, errors.slice(0, 3).join('\n'));
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
