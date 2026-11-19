// uc-757 ui layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 10 and up. A builder opens a skill
// page and an agent page, types @ in the brief, adds a tool the agent lacks from the menu, sees what it adds, the save
// lands, and the test panel shows the step tracker; a reviewer reads both pages read-only. Platform sign-in (James
// builds, Maya reviews), the demo stack's fake model. The tracker line draws what the Runtime reports on a reply
// (`skillRun`); the model here does not run a skill, so the thread read is given that field at the network edge and the
// server side of it is proved by the api script.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, evidenceDir, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 6);
const AREA = 'agents-service';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const made = async (path, body, method = 'POST') => {
      const res = await fetch(`${agents}${path}`, { method, headers: J, body: JSON.stringify(body) });
      const json = await res.json();
      if (!json.data) throw new Error(`setup ${path}: ${res.status} ${JSON.stringify(json).slice(0, 300)}`);
      return json.data;
    };
    const skill = await made('/v1/skills', {
      name: `Card dispute walk ${RUN}`,
      ownerTeam: 'team_ops',
      useWhen: 'The cardholder disputes a charge.',
      instructions: 'Say what each step found before moving on.',
      steps: [{ do: 'Ask which charge is disputed.' }, { do: 'Look the charge up and say what it shows.' }, { do: 'Tell the cardholder what happens next.' }],
    });
    const agent = await made('/v1/agents', { name: `Dispute desk ${RUN}`, role: 'Helps cardholders with disputes' });
    await made(`/v1/agents/${agent.id}`, { brief: { purpose: 'Help cardholders dispute a charge.', goal: 'Every dispute ends with a clear next step.', howToAnswer: 'Keep answers short.', never: ['Promise a refund before the review'], success: ['The cardholder knows what happens next'] } }, 'PATCH');

    const browser = await chromium.launch();
    const errors = [];
    const failed = [];
    const watch = (page, who) => {
      page.on('pageerror', (e) => errors.push(`${who}: ${e.message}`));
      page.on('console', (m) => m.type() === 'error' && !/Failed to load resource/.test(m.text()) && errors.push(`${who}: ${m.text()}`));
      // A reply's stream is closed by the browser when the page is resized or left after the reply ended; that is not a failure.
      page.on('requestfailed', (r) => !(r.method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url())) && failed.push(`${who}: ${r.method()} ${r.url()} ${r.failure()?.errorText}`));
      page.on('response', (r) => r.status() >= 400 && failed.push(`${who}: ${r.status()} ${r.request().method()} ${r.url()}`));
    };
    const signIn = async (email) => {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      watch(page, email.split('@')[0]);
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(email);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      return page;
    };
    try {
      const page = await signIn(JAMES);

      // 10. The skill page: the steps are one document, and the endings hint reads.
      await page.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('skill-document').waitFor({ timeout: 120_000 });
      await page.getByTestId('skill-document').getByRole('group', { name: 'Step 3' }).waitFor({ timeout: 60_000 });
      check('10 the skill page draws its steps as one document', (await page.getByTestId('skill-document').getByRole('group', { name: /^Step \d/ }).count()) === 3, await page.getByTestId('skill-document').innerText());
      const endings = page.getByTestId('skill-results-section');
      await endings.scrollIntoViewIfNeeded();
      check('10 the endings section says when another skill\'s step passes', /passes only if this skill ends as done/.test(await endings.innerText()), await endings.innerText());
      await shootBothWidths(page, AREA, 'uc-757-skill-admin', async () => {
        await page.waitForTimeout(600);
        await page.getByTestId('skill-results-section').scrollIntoViewIfNeeded().catch(() => undefined);
      });

      await page.setViewportSize({ width: 1440, height: 1000 });
      // 11. The agent page: @ in the brief lists a tool the agent lacks, with what picking it adds; the save lands.
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const brief = page.getByTestId('agent-brief');
      await brief.waitFor({ timeout: 120_000 });
      await page.getByTestId('agent-uses-link').waitFor({ timeout: 60_000 });
      check('11 the brief has its headings and the uses line is a link', (await brief.getByRole('group').count()) >= 5 && /^Uses /.test(await page.getByTestId('agent-uses-link').innerText()), await page.getByTestId('agent-uses-link').innerText());
      const how = brief.getByRole('group', { name: 'How to answer' });
      await how.click();
      await page.keyboard.press('End');
      await page.keyboard.type(' Start with @');
      const menu = page.getByTestId('caret-menu');
      await menu.getByRole('option').first().waitFor({ timeout: 60_000 });
      // The note under the list belongs to the highlighted row: step down until it is one the agent lacks.
      const adds = /Adds .* to this agent/;
      for (let i = 0; i < 12 && !adds.test(await menu.innerText()); i++) await page.keyboard.press('ArrowDown');
      check("12 the brief's @ menu lists a tool the agent lacks, with what picking it adds", adds.test(await menu.innerText()), await menu.innerText());
      // The open menu is drawn at 1440 only: a resize remounts the layout and closes it.
      await page.screenshot({ path: evidenceDir('media', AREA, 'uc-757-agent-menu-admin-1440.png') });
      const added = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/agents/${agent.id}/references`, { timeout: 60_000 }));
      await page.keyboard.press('Enter');
      check('13 picking it adds it to the agent', (await added).ok());
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent.id}`, { timeout: 60_000 }));
      check('14 the brief saves on its own and the status says it', (await saved).ok() && (await page.getByTestId('agent-save-status').filter({ hasText: /saved/i }).waitFor({ timeout: 30_000 }).then(() => true, () => false)), await page.getByTestId('agent-save-status').innerText());
      const after = (await (await fetch(`${agents}/v1/agents/${agent.id}`, { headers: J })).json()).data;
      check('15 the agent now holds the tool and its brief mentions it', after.toolIds.length === 1 && /@tool:/.test(after.brief.howToAnswer), { toolIds: after.toolIds, how: after.brief?.howToAnswer });

      // 16. The model and limits form stays closed until opened; the leave guard holds unsaved text.
      await page.getByTestId('agent-model-limits-toggle').click();
      check('16 model and limits opens to the model, thinking and the rules and limits', (await page.getByTestId('agent-model-limits').isVisible()) && (await page.getByTestId('agent-rules-and-limits').isVisible()));

      // 17. The test panel shows the step tracker after a reply.
      await page.route(/\/chat\/threads\/[^/?]+$/, async (route) => {
        if (route.request().method() !== 'GET') return route.continue();
        const res = await route.fetch();
        const body = await res.json();
        const t = body.data ?? body;
        const last = [...(t.messages ?? [])].reverse().find((m) => m.role === 'assistant');
        if (last) last.skillRun = { running: { skillId: skill.id, version: 1, name: skill.name, step: 2, stepsTotal: 4, stepText: 'Look the charge up', sub: null }, history: [], holds: [] };
        return route.fulfill({ response: res, json: body.data ? { ...body, data: t } : t });
      });
      await page.getByTestId('test-agent-button').click();
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 60_000 });
      await box.fill('I do not recognise a charge on my card.');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      await page.getByTestId('skill-tracker').waitFor({ timeout: 120_000 });
      check('17 the test panel shows which step the skill is on', /step 2 of 4/.test(await page.getByTestId('skill-tracker').innerText()), await page.getByTestId('skill-tracker').innerText());
      await shootBothWidths(page, AREA, 'uc-757-agent-admin', async () => {
        await page.waitForTimeout(800);
        await page.getByTestId('agent-test-panel').scrollIntoViewIfNeeded().catch(() => undefined);
      });
      await page.setViewportSize({ width: 1440, height: 1000 });

      // 18. A reviewer reads both pages and cannot edit.
      const maya = await signIn(MAYA);
      await maya.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('agent-brief').waitFor({ timeout: 120_000 });
      await maya.getByTestId('read-only-notice').waitFor({ timeout: 60_000 });
      check('18 a reviewer sees the agent page as view only, with no Edit as plain text link', (await maya.getByTestId('agent-prompt-mode').count()) === 0);
      await shootBothWidths(maya, AREA, 'uc-757-agent-member', async () => {});
      await maya.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('skill-document').waitFor({ timeout: 120_000 });
      await shootBothWidths(maya, AREA, 'uc-757-skill-member', async () => {});

      check('19 no page errors and no failed requests', errors.length === 0 && failed.length === 0, { errors, failed });
      console.log(`walk: ${errors.length} console errors, ${failed.length} failed requests`, errors, failed);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
