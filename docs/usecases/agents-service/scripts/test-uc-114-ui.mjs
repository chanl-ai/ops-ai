// uc-114 an admin decides which publishes need a review, ui layer: docs/usecases/agents-service/publish-review-policy.md.
// Dev auto-approve is off, so "major changes only" differs from "never". Settings change on the page as Priya; the
// publishes go through the agent's publish route as James, the route the agent page's button calls.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PRIYA = 'p.shah@northfieldbank.com';
const JAMES = 'j.richardson@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
// Reading policies is the security team's; Sam reads what Priya saved.
const readPolicy = async () => (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies/publishReview`, { headers: { Authorization: `Bearer ${await tokenFor('s.adeyemi@northfieldbank.com')}`, 'X-Team-Id': 'team_security' } }).then((r) => r.json())).data?.value?.team_ops?.agents;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const call = async (method, path, headers, body) => {
  const r = await fetch(`${agents}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, body: await r.json().catch(() => null) };
};

async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return { page, errors };
}

async function openSettings(page, consoleUrl) {
  await page.goto(`${consoleUrl}/settings/policies/publish-reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('combobox', { name: 'Agents review' }).waitFor({ timeout: 60_000 });
}

async function setMode(page, area, label) {
  await page.getByRole('combobox', { name: `${area} review` }).click();
  await page.getByRole('option', { name: label, exact: true }).click();
}

await withUiStack(
  async (consoleUrl) => {
    const P = as(await tokenFor(PRIYA));
    const J = as(await tokenFor(JAMES));
    const listed = (await call('GET', '/v1/agents', J)).body?.data;
    const rows = Array.isArray(listed) ? listed : listed?.data ?? listed?.items ?? [];
    const agent = rows.find((a) => a.publishedVersion != null && !a.paused) ?? rows[0];
    if (!agent) throw new Error(`setup: no agent in team_ops: ${JSON.stringify(listed).slice(0, 300)}`);
    const publish = async (patch) => {
      const saved = await call('PATCH', `/v1/agents/${agent.id}`, J, patch);
      const req = await call('POST', `/v1/agents/${agent.id}/publish-requests`, J, { version: saved.body?.data?.version, note: 'uc-114' });
      const d = req.body?.data;
      return { id: d?.id, status: req.status, review: d?.status, record: d?.agentPublish && { reviewRequired: d.agentPublish.reviewRequired, policy: d.agentPublish.policy, majorChange: d.agentPublish.majorChange }, saved: saved.status };
    };

    // A new draft, published from the agent page; returns the message the page showed (c-139).
    const publishFromPage = async (page, patch) => {
      const saved = (await call('PATCH', `/v1/agents/${agent.id}`, J, patch)).body?.data;
      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('request-agent-publish').click();
      await page.locator('#agent-publish-note').fill('uc-114 from the page');
      // The dialog says what will happen before the click (agents-1): its button reads Publish or Request publish.
      const confirm = page.getByTestId('confirm-agent-publish');
      await page.waitForFunction(() => !/Checking/.test(document.querySelector('[data-testid="confirm-agent-publish"]')?.textContent ?? 'Checking'), null, { timeout: 30_000 });
      const button = (await confirm.innerText()).trim();
      const dialog = await page.getByRole('dialog').innerText();
      await confirm.click();
      const toast = page.locator('[data-sonner-toast]').filter({ hasText: `${saved?.name ?? agent.name} v${saved?.version}` }).last();
      return { version: saved?.version, button, immediately: /Publishes immediately/.test(dialog), text: await toast.innerText({ timeout: 30_000 }).catch(() => '') };
    };

    const browser = await chromium.launch();
    try {
      // Step 1: every member reads the policies (7faf3ddc), so a builder sees the modes with their controls off and no
      // Save, the default still major for the team; a save as the builder is refused (403).
      const james = await signIn(browser, consoleUrl, JAMES);
      await james.page.goto(`${consoleUrl}/settings/policies/publish-reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const agentsMode = james.page.getByRole('combobox', { name: 'Agents review' });
      await agentsMode.waitFor({ timeout: 60_000 });
      const shownText = (await agentsMode.innerText()).trim();
      const locked = await agentsMode.isDisabled();
      const saves = await james.page.getByRole('button', { name: 'Save', exact: true }).count();
      const plat = `http://127.0.0.1:${PLATFORM_PORT}`;
      const refused = await fetch(`${plat}/v1/policies/publishReview`, { method: 'PUT', headers: J, body: JSON.stringify({ value: { agents: 'never' } }) }).then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }));
      check('a builder sees publish reviews locked with no Save, the default still major for the team, and a save as the builder is refused (403)', /Review major changes/.test(shownText) && locked && saves === 0 && refused.status === 403, { shownText, locked, saves, status: refused.status });

      // Step 2: under the default, a minor change publishes at once.
      const minor = await publish({ role: 'Answers questions for the operations team (uc-114 a)' });
      check('under "major changes only" a role change publishes at once and records policy major, not major', minor.status === 201 && minor.review === 'approved' && minor.record?.policy === 'major' && minor.record?.majorChange === false && minor.record?.reviewRequired === false, minor);

      // Step 3: the admin sets Agents to Never from the page.
      const priya = await signIn(browser, consoleUrl, PRIYA);
      await openSettings(priya.page, consoleUrl);
      await setMode(priya.page, 'Agents', 'Publish at once');
      await priya.page.getByRole('button', { name: 'Save', exact: true }).click();
      const toast1 = await priya.page.getByText('Saved publish reviews').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      // A team admin cannot read policies (settings.view is the security team's), so the page shows what her save returned.
      const afterReload = await priya.page.getByRole('combobox', { name: 'Agents review' }).innerText();
      const policyNow = await readPolicy();
      const audit = policyNow === 'never';
      check('the admin saves Agents as Publish at once with Save; the page shows what the save returned and the server holds never for the team', toast1 && /Publish at once/.test(afterReload) && audit, { toast1, afterReload, audit });

      // Step 4: under Never, a major change publishes at once.
      const never = await publish({ instructions: 'Answer briefly. (uc-114 b)' });
      check('under "never" an instructions change publishes at once and records policy never, major', never.status === 201 && never.review === 'approved' && never.record?.policy === 'never' && never.record?.majorChange === true, never);

      // The agent page says what happened (c-139): published at once under Never.
      const livePage = await publishFromPage(james.page, { role: 'Answers questions for the operations team (uc-114 page)' });
      check('under "never" the dialog says Publishes immediately with a Publish button (agents-1)', livePage.button === 'Publish' && livePage.immediately, livePage);
      check('publishing from the agent page under "never" says Published, with no review link', livePage.text.startsWith(`Published ${agent.name} v${livePage.version}`) && !/Open review/.test(livePage.text), livePage);

      // Steps 5 and 6: under Always, even a minor change opens a review.
      await setMode(priya.page, 'Agents', 'Review every change');
      await priya.page.getByRole('button', { name: 'Save', exact: true }).click();
      await priya.page.getByText('Saved publish reviews').nth(0).waitFor({ timeout: 30_000 }).catch(() => undefined);
      const toast2 = (await readPolicy()) === 'always';
      const always = await publish({ role: 'Answers questions for the operations team (uc-114 c)' });
      check('under "always" a role change opens a pending review that records reviewRequired', toast2 && always.status === 201 && always.review === 'pending' && always.record?.reviewRequired === true && always.record?.policy === 'always', { toast2, ...always });

      // The review claims an eval pass only from a run that had cases: this version has none run (showcase, tick 32).
      await priya.page.goto(`${consoleUrl}/reviews/${always.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const noEvals = await priya.page.getByTestId('agent-publish-no-evals').innerText({ timeout: 60_000 }).catch(() => '');
      const claimed = await priya.page.getByText(/Every eval case passes/).count();
      check('a publish review with no eval run says none ran and claims no pass', /^No eval cases run for v\d+\.$/.test(noEvals) && claimed === 0, { noEvals, claimed });

      // The agent page under Always: sent for review, with the link. The open request is rejected first: an agent has
      // one open publish request at a time.
      const cleared = await call('POST', `/v1/publish-requests/${always.id}/decision`, P, { decision: 'rejected', reason: 'uc-114 clears it' });
      if (cleared.status !== 200) throw new Error(`setup: reject ${always.id}: ${JSON.stringify(cleared.body).slice(0, 300)}`);
      const waitPage = await publishFromPage(james.page, { role: 'Answers questions for the operations team (uc-114 page 2)' });
      check('under "always" the dialog offers Request publish and promises a review', waitPage.button === 'Request publish' && !waitPage.immediately, waitPage);
      check('publishing from the agent page under "always" says Sent for review with Open review', waitPage.text.startsWith(`Sent ${agent.name} v${waitPage.version} for review`) && /Open review/.test(waitPage.text), waitPage);

      check('no page errors', james.errors.length === 0 && priya.errors.length === 0, [...james.errors, ...priya.errors]);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
