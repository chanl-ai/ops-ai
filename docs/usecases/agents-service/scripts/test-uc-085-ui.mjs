// uc-085 an agent keeps its guardrails, ui layer: docs/usecases/agents-service/agent-guardrails-blocked-topics.md.
// withUiStack's `demo` stack, whose agents seed beside services/agents-service/seed/guardrails.json, so ag_advisor
// starts with "No investment advice" v1 pinned. Signed in through platform-service as James.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const GUARDRAIL = 'gr_no_investment_advice';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const message = (await (await fetch(`${agents}/v1/guardrails/${GUARDRAIL}`, { headers: J })).json()).data?.config?.message;
    const created = await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: 'ag_advisor', kbIds: [] }) })).json();
    if (!created.data || !message) throw new Error(`setup: ${JSON.stringify(created).slice(0, 300)} message=${message}`);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // Step 2 in the chat: the refusal reads as the guardrail's message, and the turn says which guardrail refused.
      await page.goto(`${consoleUrl}/chat/${created.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      await box.fill('Should my client buy Harbor & Pine shares?');
      const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const res = await sent;
      await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      const refused = await page.getByText(message.slice(0, 60)).last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const note = await page.getByTestId('guardrail-refusal').last().innerText({ timeout: 15_000 }).catch(() => '');
      check('the blocked question shows the guardrail message and names the guardrail that refused it', refused && /No investment advice v1/.test(note) && /investment advice/.test(note), { refused, note });

      // Step 4 in the chat: a hardship question loads the pinned skill, and the turn says so.
      await box.fill("My client lost her job and cannot make this month's mortgage payment. What can we do?");
      const sentSkill = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const resSkill = await sentSkill;
      await Promise.race([resSkill?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      const skillLine = await page.getByTestId('loaded-skills').last().innerText({ timeout: 60_000 }).catch(() => '');
      const skillAnswer = await page.getByText(/hardship request form/).last().isVisible().catch(() => false);
      check('a hardship question shows "Loaded skill Hardship request triage v1" on the turn', /Loaded skill Hardship request triage v1/.test(skillLine) && skillAnswer, { skillLine, skillAnswer });

      // Step 1 on the agent page: blocked topics are the pinned guardrail, marked enforced; the settings the runtime
      // does not act on say so.
      // The mock console has a skill of the same name, so the check reads the page's own request to agents-service.
      const skillsRead = armed(page.waitForResponse((r) => r.url().startsWith(agents) && /\/v1\/agents\/ag_advisor\/skills$/.test(r.url()), { timeout: 60_000 }));
      await page.goto(`${consoleUrl}/agents/ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Pinned guardrails are listed under the guardrail picker (c-136), each as a row.
      const pin = page.getByTestId('guardrail-pin').filter({ hasText: 'No investment advice' });
      const pinned = await pin.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const enforced = await page.getByText('Enforced', { exact: true }).count();
      // Redaction and when-unsure are not acted on by any turn, so the page does not offer them (c-068).
      const unenforced = (await page.locator('#g-pii').count()) + (await page.locator('#g-unsure').count());
      check('the agent page shows the pin as enforced and offers no setting the runtime ignores', pinned && enforced === 1 && unenforced === 0, { pinned, enforced, unenforced });

      const pins = await page.getByTestId('agent-skill-pins').innerText({ timeout: 30_000 }).catch(() => '');
      const served = await (await skillsRead.catch(() => null))?.json().catch(() => null);
      const servedPins = (served?.data?.pins ?? []).map((p) => `${p.skillId} v${p.pinnedVersion}`);
      check('the agent page lists the attached skill, read from agents-service', /Hardship request triage/.test(pins) && servedPins.join() === 'sk_hardship_triage v1', { pins: pins.slice(0, 200), servedPins });

      // Switched off on the page (c-085): saved on a version, published, then not checked at all.
      // The change saves itself into the draft a second later (c-172), so the wait is armed before it.
      const savedOff = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/v1\/agents\/ag_advisor$/.test(r.url()), { timeout: 60_000 }));
      await page.getByRole('switch', { name: 'Check No investment advice' }).click();
      const offShown = await page.getByTestId('guardrail-off').isVisible();
      const offAgent = (await (await savedOff)?.json().catch(() => null))?.data;
      const offPin = offAgent?.guardrailPins?.find((p) => p.guardrailId === GUARDRAIL);
      check('switching the guardrail off shows "Off" and saves a version with it off', offShown && offPin?.enabled === false, { offShown, offPin });
      await fetch(`${agents}/v1/agents/ag_advisor/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: offAgent?.version, note: 'guardrail off for a test' }) });
      const offThread = (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: 'ag_advisor', kbIds: [] }) })).json()).data;
      const stream = await (await fetch(`${agents}/chat/threads/${offThread.id}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: 'Should my client buy Harbor & Pine shares?' }) })).text();
      const offReply = (await (await fetch(`${agents}/chat/threads/${offThread.id}`, { headers: J })).json()).data?.messages?.at(-1);
      check('with it off, the shares question gets a real answer, not the guardrail\'s message', offReply?.role === 'assistant' && !!offReply.content?.trim() && !offReply.guardrail && offReply.content !== message && !stream.includes('"guardrail_unavailable"'), { reply: offReply?.content?.slice(0, 160), guardrail: offReply?.guardrail });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByRole('switch', { name: 'Check No investment advice' }).waitFor({ timeout: 60_000 });
      check('the agent page still shows it Off after a reload', await page.getByTestId('guardrail-off').isVisible());
      await page.getByRole('switch', { name: 'Check No investment advice' }).click();

      // Unpinning from the page saves a version without the pin: the picker's chip has Remove (c-136).
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/v1\/agents\/ag_advisor$/.test(r.url()), { timeout: 60_000 }));
      await page.getByTestId('guardrail-picker').getByRole('button', { name: 'Remove No investment advice' }).click();
      const patch = await (await saved)?.json().catch(() => null);
      check('unpinning from the page saves a draft with no guardrail pin', Array.isArray(patch?.data?.guardrailPins) && patch.data.guardrailPins.length === 0, patch?.data?.guardrailPins);

      // The whole guardrail loop in the console: create, publish, and it is offered to pin on the agent page.
      await page.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('new-guardrail-button').click();
      await page.getByLabel('Name').fill('No tax advice');
      const topicBox = page.locator('#guardrail-topics');
      await topicBox.fill('tax advice');
      await topicBox.press('Enter');
      await page.getByLabel('Message instead of an answer').fill('I cannot give tax advice. A tax professional can help with that.');
      await page.getByTestId('guardrail-submit').click();
      // Creating opens the guardrail's own page; it is published from there.
      await page.waitForURL(/\/guardrails\/[^/]+$/, { timeout: 30_000 });
      const gid = new URL(page.url()).pathname.split('/').pop();
      const drafted = await page.getByText('never published').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      await page.getByRole('button', { name: 'Publish v1' }).click();
      let published = false;
      for (const until = Date.now() + 30_000; !published && Date.now() < until; await page.waitForTimeout(500)) {
        published = (await (await fetch(`${agents}/v1/guardrails/${gid}`, { headers: J })).json()).data?.publishedVersion === 1;
      }
      await page.goto(`${consoleUrl}/agents/ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('guardrail-picker').getByRole('button', { name: 'Pin guardrails' }).click({ timeout: 60_000 });
      await page.getByPlaceholder('Search guardrails…').fill('No tax advice');
      const offered = await page.getByRole('option', { name: /No tax advice/ }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      await page.keyboard.press('Escape');
      check('a guardrail created and published from the console is offered to pin on the agent page', drafted && published && offered, { drafted, published, offered });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
