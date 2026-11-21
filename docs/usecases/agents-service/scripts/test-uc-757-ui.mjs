// uc-757 ui layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 10 and up. A builder opens a skill
// page and an agent page, types @ in the brief, adds a tool the agent lacks from the menu, sees what it adds, the save
// lands, and the test panel shows the step tracker; a reviewer reads both pages read-only. Platform sign-in (James
// builds, Maya reviews), the demo stack's fake model. A tool picked in the middle of a step's sentence is saved as the
// step's tool, and the chat view shows a skill a reviewer's rejection ended. The tracker line draws what the Runtime reports on a reply
// (`skillRun`); the model here does not run a skill, so the thread read is given that field at the network edge and the
// server side of it is proved by the api script.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, evidenceDir, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { agentBase, saveAgent } from '../../lib/agent_save.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const PRIYA = 'p.shah@harborpine.example';
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
    await made(`/v1/agents/${agent.id}`, { brief: { purpose: 'Help cardholders dispute a charge.', goal: 'Every dispute ends with a clear next step.', howToAnswer: 'Keep answers short.', never: ['Promise a refund before the review'], success: ['The cardholder knows what happens next'] }, ...(await agentBase(agents, J, agent.id)) }, 'PATCH');

    const browser = await chromium.launch();
    const errors = [];
    const failed = [];
    const watch = (page, who) => {
      page.on('pageerror', (e) => errors.push(`${who}: ${e.message} ${(e.stack ?? '').split('\n').slice(1, 4).join(' ')}`));
      // React's warnings arrive as a format string with `%s`; the arguments name the components.
      page.on('console', (m) => {
        if (m.type() !== 'error' || /Failed to load resource/.test(m.text())) return;
        const at = errors.push(`${who}: ${m.text()}`) - 1;
        void Promise.all(m.args().map((a) => a.jsonValue().catch(() => '?'))).then((args) => (errors[at] = `${who}: ${args.map(String).join(' | ').slice(0, 600)}`));
      });
      // A reply's stream is closed by the browser when the page is resized or left after the reply ended; that is not a failure.
      // So is a link's prefetch (`_rsc`) the browser drops when the page is left before it answers.
      const dropped = (r) => (r.method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url())) || (/[?&]_rsc=/.test(r.url()) && r.failure()?.errorText === 'net::ERR_ABORTED');
      page.on('requestfailed', (r) => !dropped(r) && failed.push(`${who}: ${r.method()} ${r.url()} ${r.failure()?.errorText}`));
      // A save refused because someone else saved first (409) is the step under test, for the agent and the skill draft.
      const stale = (r) => r.status() === 409 && ((r.request().method() === 'PATCH' && /\/v1\/agents\/[^/]+$/.test(r.url())) || (r.request().method() === 'PUT' && /\/v1\/skills\/[^/]+\/draft$/.test(r.url())));
      page.on('response', (r) => r.status() >= 400 && !stale(r) && failed.push(`${who}: ${r.status()} ${r.request().method()} ${r.url()}`));
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

      // 10. The skill page: the notes and steps are one text, and the endings hint reads.
      const doc = page.getByTestId('sop-editor-content');
      const lineOf = (text) => page.getByTestId('sop-editor').locator('.cm-line', { hasText: text });
      await page.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await doc.waitFor({ timeout: 120_000 });
      await lineOf('Tell the cardholder what happens next').waitFor({ timeout: 60_000 });
      const notes = await doc.innerText();
      check('10 the skill page draws its notes and three steps as one text', ['Say what each step found', 'Ask which charge is disputed', 'Look the charge up', 'Tell the cardholder what happens next'].every((t) => notes.includes(t)), notes);
      // A skill made by the New skill dialog holds only section headings; the text shows those as empty.
      const blank = await made('/v1/skills', { name: `Blank walk ${RUN}`, ownerTeam: 'team_ops', useWhen: 'Never, it is blank.', instructions: '## Steps\n1.\n\n## Rules\n-\n\n## Examples\n\n\n## Output format\n' });
      await page.goto(`${consoleUrl}/build/skills/${blank.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await doc.waitFor({ timeout: 120_000 });
      const empty = await doc.innerText();
      check('10 a blank skill\'s text starts empty', !/## Steps|## Rules/.test(empty), { empty });
      await page.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await lineOf('Look the charge up').waitFor({ timeout: 60_000 });
      const endings = page.getByTestId('skill-results-section');
      await endings.scrollIntoViewIfNeeded();
      check('10 the endings section says when another skill\'s step passes', /passes only if this skill ends as done/.test(await endings.innerText()), await endings.innerText());
      // A tool picked in the middle of a step's sentence becomes the tool the step runs, drawn once as a mention.
      await lineOf('Look the charge up').click();
      await page.keyboard.press('End');
      await page.keyboard.type(' with @');
      const picker = page.getByTestId('caret-menu');
      await picker.getByRole('option').first().waitFor({ timeout: 60_000 });
      await page.keyboard.press('Enter');
      await lineOf('Look the charge up').getByTestId('sop-mention').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const drawn = await page.getByTestId('sop-editor').getByTestId('sop-mention').count();
      // The Tools field lists what the text mentions, read-only, once the text holds the mention.
      const picked = (await lineOf('Look the charge up').getByTestId('sop-mention').innerText()).trim();
      const toolRow = page.getByTestId('skill-tool-row').filter({ hasText: 'in the text' });
      await toolRow.first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const toolRows = await page.getByTestId('skill-tool-row').allInnerTexts();
      check('10 the Tools field lists the tool the text mentions, read-only', (await toolRow.count()) === 1 && (await toolRow.getByRole('button').count()) === 0 && (await page.getByTestId('skill-tools-from-text').count()) === 1, { picked, toolRows });
      const stored = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url() === `${agents}/v1/skills/${skill.id}/draft`, { timeout: 60_000 }));
      await page.getByTestId('save-skill-draft').click();
      await page.getByTestId('save-skill-draft-confirm').click();
      const keptSteps = (await (await stored).json()).data?.content?.steps ?? [];
      const kept = keptSteps.find((s) => (s.do ?? '').includes('Look the charge up')) ?? {};
      check(
        '10 a tool picked mid-sentence is saved as the step\'s tool and drawn once',
        drawn === 1 && ['tool', 'agent', 'workflow'].includes(kept.use?.kind) && kept.do?.includes(`@${kept.use.kind}:${kept.use.id}`),
        { drawn, kept, keptSteps },
      );
      // Someone else saves first: James's save is refused, and Reload keeps what he typed on top of their version.
      // The button is off while the save is in flight, so the saved toast is waited for first.
      await page.getByText(/Saved draft v1/).first().waitFor({ timeout: 60_000 });
      await page.waitForFunction(() => document.querySelector('[data-testid="save-skill-draft"]')?.disabled === true, null, { timeout: 60_000 });
      await page.waitForTimeout(800);
      await lineOf('Tell the cardholder what happens next').click();
      await page.keyboard.press('End');
      // One insert, as a paste is: the check is about what Reload keeps, not about key-by-key typing.
      await page.keyboard.insertText(' Then thank them.');
      // A resize to phone width and back draws the page's columns again; the unsaved text and its save stay.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(800);
      await page.setViewportSize({ width: 1440, height: 1000 });
      await lineOf('Then thank them.').waitFor({ timeout: 10_000 }).catch(() => undefined);
      check('10 unsaved text survives a resize to 390 and back, still unsaved', /Then thank them\./.test(await doc.innerText()) && (await page.getByTestId('save-skill-draft').isEnabled()), await doc.innerText());
      await made(`/v1/skills/${skill.id}/publish-requests`, { note: 'use case' });
      const open = (await (await fetch(`${agents}/v1/skills/${skill.id}`, { headers: J })).json()).data;
      await made(`/v1/skills/${skill.id}/draft`, { name: `Card dispute renamed ${RUN}`, baseVersion: open.version, baseDigest: open.digest }, 'PUT');
      await page.getByTestId('save-skill-draft').click();
      await page.getByTestId('save-skill-draft-confirm').click();
      const staleAlert = page.getByTestId('skill-stale-base');
      const refusedStale = await staleAlert.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await page.getByTestId('skill-stale-reload').click();
      await staleAlert.waitFor({ state: 'detached', timeout: 60_000 }).catch(() => undefined);
      await lineOf('Then thank them.').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const afterReload = await doc.innerText();
      const fields = await page.locator('input').evaluateAll((els) => els.map((el) => el.value));
      check(
        '10 after someone else saves first, Reload shows their version and keeps the unsaved text',
        refusedStale && /Then thank them\./.test(afterReload) && fields.includes(`Card dispute renamed ${RUN}`),
        { refusedStale, afterReload, fields },
      );
      const onTop = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url() === `${agents}/v1/skills/${skill.id}/draft`, { timeout: 60_000 }));
      await page.getByTestId('save-skill-draft').click();
      await page.getByTestId('save-skill-draft-confirm').click();
      const top = (await (await onTop).json()).data ?? {};
      const topSteps = top.content?.steps ?? [];
      check('10 the kept text then saves on top of their version', top.name === `Card dispute renamed ${RUN}` && topSteps.some((s) => /Then thank them\./.test(s.do ?? '')) && topSteps.some((s) => s.use?.id === kept.use?.id), { name: top.name, topSteps });
      await shootBothWidths(page, AREA, 'uc-757-skill-admin', async () => {
        await page.waitForTimeout(600);
        await page.getByTestId('skill-results-section').scrollIntoViewIfNeeded().catch(() => undefined);
      });

      // 10. A skill written as text with an if line: each condition is marked, "checked" when the tool above returns what it
      // tests and "agent decides" when it is the agent's own words.
      const guarded = await made('/v1/skills', {
        name: `Guarded walk ${RUN}`,
        ownerTeam: 'team_ops',
        useWhen: 'The cardholder disputes a charge.',
        instructions: '',
        source: `Look the charge up with @${kept.use.kind}:${kept.use.id}\nif the cardholder sounds unsure:\n    Offer to explain the review.\nTell the cardholder what happens next`,
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${consoleUrl}/build/skills/${guarded.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await lineOf('Offer to explain the review').waitFor({ timeout: 60_000 });
      const legend = page.getByTestId('sop-condition-how');
      await legend.first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('10 an if line shows whether it is checked or the agent decides', (await legend.count()) >= 1 && /^(checked|agent decides)$/.test(await legend.first().innerText()), await legend.allInnerTexts());
      await shootBothWidths(page, AREA, 'uc-757-skill-text-admin', async () => {});

      await page.setViewportSize({ width: 1440, height: 1000 });
      // 11. The agent page: @ in the brief lists a tool the agent lacks, with what picking it adds; the save lands.
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const brief = page.getByTestId('agent-brief');
      await brief.waitFor({ timeout: 120_000 });
      await page.getByTestId('agent-uses-link').waitFor({ timeout: 60_000 });
      // The document editor draws after the page's own fields, so its headings are waited for before they are counted.
      await brief.getByRole('group').nth(4).waitFor({ timeout: 60_000 }).catch(() => undefined);
      check('11 the brief has its headings and the uses line is a link', (await brief.getByRole('group').count()) >= 5 && /^Uses /.test(await page.getByTestId('agent-uses-link').innerText()), await page.getByTestId('agent-uses-link').innerText());
      // An empty block's hint takes its own height at phone width, so a wrapped hint never runs under the next line.
      const bare = await made('/v1/agents', { name: `Bare desk ${RUN}`, role: 'Has an empty brief' });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${consoleUrl}/build/agents/${bare.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await brief.locator('.is-empty').first().waitFor({ timeout: 120_000 });
      const hints = await brief.locator('.is-empty').evaluateAll((els) => els.map((el) => ({ hint: parseFloat(getComputedStyle(el, '::before').height), box: el.getBoundingClientRect().height })));
      check('11 at 390 wide an empty block is as tall as its hint', hints.length > 0 && hints.every((h) => h.box >= h.hint - 1) && hints.some((h) => h.hint > 30), hints);
      await page.screenshot({ path: evidenceDir('media', AREA, 'uc-757-empty-brief-admin-390.png'), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('agent-uses-link').waitFor({ timeout: 60_000 });
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
      // This agent has no model chosen, as every agent made from the SDK or the command line: how it thinks still saves.
      const thought = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`), { timeout: 60_000 });
      await page.locator('#ag-thinking').click();
      await page.getByRole('option', { name: 'High' }).click();
      const saidHigh = (await (await thought).json()).data?.patterns?.thinking;
      check('16 with no model chosen, a change to Thinking still saves', saidHigh === 'high', saidHigh);

      // 20. Priya saves the agent while James has it open: his next change is not saved over hers, and the page says so.
      const agentSave = (r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`);
      // She changes the brief's Goal; he then changes its Purpose. The brief is saved whole, so his save must carry her Goal.
      const opened = (await (await fetch(`${agents}/v1/agents/${agent.id}`, { headers: J })).json()).data;
      const herGoal = 'Every dispute ends with a dated next step.';
      const hers = await saveAgent(agents, as(await tokenFor(PRIYA)), agent.id, { skillMenu: 'attached', brief: { ...opened.brief, goal: herGoal }, patterns: { ...opened.patterns, parallelReads: false } });
      const refused = page.waitForResponse(agentSave, { timeout: 60_000 });
      await brief.getByRole('group', { name: 'Purpose' }).click();
      await page.keyboard.press('End');
      await page.keyboard.insertText(' By phone or chat.');
      // Thinking sits in the same group of settings as the parallel reads she switched off.
      await page.locator('#ag-thinking').click();
      await page.getByRole('option', { name: 'Low' }).click();
      const refusedWith = (await refused).status();
      const told = await page.getByTestId('agent-stale-base').waitFor({ timeout: 30_000 }).then(() => page.getByTestId('agent-stale-base').innerText(), () => '');
      check('20 a change made after another person saved is refused, and the page says who saved', hers.ok && refusedWith === 409 && /p\.shah@harborpine\.example saved a newer draft/.test(told), { hers: hers.status, refusedWith, told });
      const resent = page.waitForResponse((r) => agentSave(r) && r.ok(), { timeout: 60_000 });
      await page.getByTestId('agent-stale-reload').click();
      const both = (await (await resent).json()).data;
      check('20 reloading keeps his unsaved change and hers, in the brief and in a group of settings', / By phone or chat\.$/.test(both?.brief?.purpose ?? '') && both?.brief?.goal === herGoal && both?.patterns?.thinking === 'low' && both?.patterns?.parallelReads === false && both?.skillMenu === 'attached' && (await page.getByTestId('agent-stale-base').count()) === 0, { purpose: both?.brief?.purpose, goal: both?.brief?.goal, patterns: both?.patterns, skillMenu: both?.skillMenu });

      // 21. His own save from elsewhere is no clash to tell him about: the page reads the agent again and saves.
      await page.getByTestId('agent-save-status').filter({ hasText: /saved/i }).waitFor({ timeout: 30_000 });
      await saveAgent(agents, J, agent.id, { skillMenu: 'team' });
      const answers = [];
      const note = (r) => agentSave(r) && answers.push(r.status());
      page.on('response', note);
      const landed = page.waitForResponse((r) => agentSave(r) && r.ok(), { timeout: 60_000 });
      await page.locator('#ag-thinking').click();
      await page.getByRole('option', { name: 'High' }).click();
      const mine = (await (await landed).json()).data;
      page.off('response', note);
      check('21 after his own save elsewhere the change saves with no message', answers.join() === '409,200' && mine?.patterns?.thinking === 'high' && mine?.skillMenu === 'team' && (await page.getByTestId('agent-stale-base').count()) === 0, { answers, thinking: mine?.patterns?.thinking, skillMenu: mine?.skillMenu });

      // 17. The test panel shows the step tracker after a reply.
      // A live agent of the demo: the agent written above is a draft, and only a test chat reaches a draft.
      const plain = await made('/chat/threads', { agentId: 'ag_advisor', kbIds: [] });
      await (await fetch(`${agents}/chat/threads/${plain.id}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: 'Freeze my account.' }) })).text();
      await page.route(/\/chat\/threads\/[^/?]+$/, async (route) => {
        if (route.request().method() !== 'GET') return route.continue();
        const res = await route.fetch();
        const body = await res.json();
        const t = body.data ?? body;
        const last = [...(t.messages ?? [])].reverse().find((m) => m.role === 'assistant');
        // An ordinary chat's reply carries a skill a reviewer's rejection ended in that reply, as the api script reads it.
        const rejected = { skillId: 'sk_freeze', version: 1, name: 'Freeze an account', ended: 'failed', atStep: 3, returns: {}, inReply: true, why: 'denied', check: null, meaning: null };
        const running = { skillId: skill.id, version: 1, name: skill.name, step: 2, stepsTotal: 4, stepText: 'Look the charge up', sub: null };
        if (last) last.skillRun = route.request().url().endsWith(`/${plain.id}`) ? { running: null, history: [rejected], holds: [] } : { running, history: [], holds: [] };
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
      // The chat view draws the same record: under the reply, the skill a reviewer's rejection ended reads as stopped.
      await page.goto(`${consoleUrl}/chat/${plain.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const ended = page.getByTestId('skill-ended');
      await ended.first().waitFor({ timeout: 120_000 }).catch(() => undefined);
      const line = (await ended.count()) ? await ended.first().innerText() : '';
      check(
        '17 the chat view shows a rejected write as the skill stopping, once',
        (await ended.count()) === 1 && (await ended.first().getAttribute('data-ended')) === 'failed' && /stopped at step 3: a reviewer rejected the action/.test(line) && (await page.getByTestId('skill-tracker').count()) === 0,
        line,
      );
      await shootBothWidths(page, AREA, 'uc-757-chat-ended-admin', async () => {});
      await page.setViewportSize({ width: 1440, height: 1000 });

      // 18. A reviewer reads both pages and cannot edit.
      const maya = await signIn(MAYA);
      await maya.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('agent-brief').waitFor({ timeout: 120_000 });
      await maya.getByTestId('read-only-notice').waitFor({ timeout: 60_000 });
      check('18 a reviewer sees the agent page as view only, with no Edit as plain text link', (await maya.getByTestId('agent-prompt-mode').count()) === 0);
      await maya.getByTestId('agent-uses-link').click();
      const sheet = await maya.getByTestId('agent-uses-sheet').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      await maya.keyboard.press('Escape');
      await maya.getByTestId('agent-model-limits-toggle').click();
      const limits = await maya.getByTestId('agent-model-limits').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      check('18 a reviewer can open what the agent uses and its model and limits, with the fields off', sheet && limits && (await maya.locator('#ag-thinking').isDisabled()), { sheet, limits });
      await shootBothWidths(maya, AREA, 'uc-757-agent-member', async () => {});
      await maya.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('sop-editor-content').waitFor({ timeout: 120_000 });
      await shootBothWidths(maya, AREA, 'uc-757-skill-member', async () => {});

      // 23. Pages reached by the sidebar's links, not by loading their URL: a client navigation keeps the shell mounted,
      // and the walks saw update loops only that way, at both widths.
      const viaSidebar = async (p, href) => {
        const link = p.locator(`[data-sidebar="sidebar"] a[href="${href}"]`).first();
        if (!(await link.isVisible())) await p.getByRole('button', { name: /toggle sidebar/i }).first().click();
        await link.click();
        // Unsaved text asks first; the walk leaves it.
        const leave = p.getByTestId('leave-guard-discard');
        await leave.waitFor({ timeout: 2_000 }).then(() => leave.click(), () => undefined);
        await p.waitForURL((u) => u.pathname === href, { timeout: 60_000 });
        await p.waitForTimeout(1500);
      };
      const seen = errors.length;
      for (const [who, p] of [['james', page], ['maya', maya]]) {
        for (const width of [1440, 390]) {
          await p.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
          await viaSidebar(p, '/build/workflows');
          const flow = p.locator('main a[href^="/build/workflows/definitions/"]').first();
          if (await flow.count()) {
            await flow.dispatchEvent('click');
            await p.waitForURL((u) => /^\/build\/workflows\/[^/]+/.test(u.pathname), { timeout: 60_000 });
            await p.waitForTimeout(2000);
          }
          await viaSidebar(p, '/build/skills');
          // The row's link lies under its label; a click event on the link is the row click a person makes.
          await p.locator(`main a[href="/build/skills/${skill.id}"]`).first().dispatchEvent('click');
          await p.getByTestId('sop-editor-content').waitFor({ timeout: 60_000 });
          if (who === 'james') {
            await p.getByTestId('sop-editor-content').click();
            await p.keyboard.press('ControlOrMeta+End');
            await p.keyboard.type(' Then say goodbye with @', { delay: 20 });
            await p.getByTestId('caret-menu').getByRole('option').first().waitFor({ timeout: 60_000 });
            await p.keyboard.press('Enter');
            // The walks typed, then resized to the other width with the text unsaved.
            await p.setViewportSize(width === 1440 ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
            await p.waitForTimeout(1000);
            await p.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
            await p.waitForTimeout(1000);
          }
          await viaSidebar(p, '/work/tasks');
        }
        await p.setViewportSize({ width: 1440, height: 1000 });
      }
      // A skill publish waiting on Maya, the way the walk made one: the team's skill publishes always need a review.
      const policy = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies/publishReview`, { method: 'PUT', headers: as(await tokenFor(PRIYA)), body: JSON.stringify({ value: { skills: 'always' } }) });
      // A policy change ends the tokens issued before it.
      const fresh = as(await tokenFor(JAMES));
      const post = async (path, body) => (await (await fetch(`${agents}${path}`, { method: 'POST', headers: fresh, body: JSON.stringify(body) })).json()).data ?? {};
      const asked = await post('/v1/skills', { name: `Reviewed walk ${RUN}`, ownerTeam: 'team_ops', useWhen: 'The cardholder asks for a statement.', instructions: 'Send the latest statement.', steps: [{ do: 'Say where the statement is.' }] });
      const request = await post(`/v1/skills/${asked.id}/publish-requests`, { note: 'uc-757 walk' });
      await viaSidebar(maya, '/build/skills');
      await viaSidebar(maya, '/work/tasks');
      // The publish is the one task waiting on Maya here; its row names the review, not the skill.
      await maya.locator('[data-testid^="queue-item-"]').first().click();
      const pane = maya.getByTestId('review-sheet');
      const shown = await pane.getByTestId('review-approve').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('23 a skill publish opened from Human Tasks shows in the review sheet with its approve button', policy.status === 200 && request.status === 'in_review' && shown, { policy: policy.status, request: request.status, shown });
      check('23 the workflows list and canvas, the skill editor while typing and Human Tasks, reached by sidebar links, log no errors', errors.length === seen, errors.slice(seen));
      check('19 no page errors and no failed requests', errors.length === 0 && failed.length === 0, { errors, failed });
      console.log(`walk: ${errors.length} console errors, ${failed.length} failed requests`, errors, failed);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
