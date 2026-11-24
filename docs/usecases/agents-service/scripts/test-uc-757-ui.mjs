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
// The skill page saves itself a second after a change; Save in the header sends it now when the change still waits.
const saveSkill = (p) => p.getByTestId('save-skill-draft').click({ timeout: 2_000 }).catch(() => undefined);

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
      // The walk's policy change ends the pages' tokens, so a page's next call answers 401 and the console renews the
      // token and sends it again (request-identity.ts). Such a 401 fails the walk only if that resend never succeeds.
      page.on('response', (r) => {
        const call = `${who}: ${r.request().method()} ${r.url()}`;
        if (r.status() === 401) renewed.set(call, (renewed.get(call) ?? 0) + 1);
        else if (r.status() < 300 && renewed.get(call)) renewed.set(call, renewed.get(call) - 1);
        else if (r.status() >= 400 && !stale(r)) failed.push(`${who}: ${r.status()} ${r.request().method()} ${r.url()}`);
      });
    };
    const renewed = new Map();
    const unrenewed = () => [...renewed].filter(([, n]) => n > 0).map(([call]) => `401 never resent with success: ${call}`);
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
      // Endings and results sit on the Settings tab.
      await page.getByTestId('skill-settings-tab-trigger').click();
      const endings = page.getByTestId('skill-results-section');
      await endings.waitFor({ timeout: 30_000 });
      check('10 the endings section says when another skill\'s step passes', /passes only if this skill ends as done/.test(await endings.innerText()), await endings.innerText());
      await page.getByRole('tab', { name: /^Instructions/ }).click();
      await lineOf('Look the charge up').waitFor({ timeout: 30_000 });
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
      const rows = page.getByTestId('skill-tools-rows').locator(':scope > *');
      const toolRow = rows.filter({ hasText: 'In the steps' });
      await toolRow.first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const toolRows = await rows.allInnerTexts();
      check('10 the Tools list shows the tool the text mentions, with no Remove', (await toolRow.count()) === 1 && (await toolRow.getByRole('button').count()) === 0, { picked, toolRows });
      const stored = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url() === `${agents}/v1/skills/${skill.id}/draft`, { timeout: 60_000 }));
      await saveSkill(page);
      const keptSteps = (await (await stored).json()).data?.content?.steps ?? [];
      const kept = keptSteps.find((s) => (s.do ?? '').includes('Look the charge up')) ?? {};
      check(
        '10 a tool picked mid-sentence is saved as the step\'s tool and drawn once',
        drawn === 1 && ['tool', 'agent', 'workflow'].includes(kept.use?.kind) && kept.do?.includes(`@${kept.use.kind}:${kept.use.id}`),
        { drawn, kept, keptSteps },
      );
      // Someone else saves first: James's save is refused. Reload shows their text and keeps his as a read-only copy,
      // and nothing saves over their text unless he chooses to.
      await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 60_000 });
      // Their save lands before his next change, so the save of his change is the one refused.
      await made(`/v1/skills/${skill.id}/publish-requests`, { note: 'use case' });
      const open = (await (await fetch(`${agents}/v1/skills/${skill.id}`, { headers: J })).json()).data;
      const THEIRS = 'Ask whether there is anything else.';
      await made(`/v1/skills/${skill.id}/draft`, { name: `Card dispute renamed ${RUN}`, source: `${open.text}\n${THEIRS}`, baseVersion: open.version, baseDigest: open.digest }, 'PUT');
      await lineOf('Tell the cardholder what happens next').click();
      await page.keyboard.press('End');
      // One insert, as a paste is: the check is about what Reload keeps, not about key-by-key typing.
      await page.keyboard.insertText(' Then thank them.');
      // A resize to phone width and back draws the page's columns again; the unsaved text and its save stay.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(800);
      await page.setViewportSize({ width: 1440, height: 1000 });
      await lineOf('Then thank them.').waitFor({ timeout: 10_000 }).catch(() => undefined);
      check('10 his text survives a resize to 390 and back', /Then thank them\./.test(await doc.innerText()), await doc.innerText());
      await saveSkill(page);
      const staleAlert = page.getByTestId('skill-stale-base');
      const refusedStale = await staleAlert.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await page.getByTestId('skill-stale-reload').click();
      await staleAlert.waitFor({ state: 'detached', timeout: 60_000 }).catch(() => undefined);
      await lineOf(THEIRS).waitFor({ timeout: 60_000 }).catch(() => undefined);
      const afterReload = await doc.innerText();
      const fields = await page.locator('input').evaluateAll((els) => els.map((el) => el.value));
      check(
        '10 after someone else saves first, Reload shows their text and name, not his',
        refusedStale && afterReload.includes(THEIRS) && !/Then thank them\./.test(afterReload) && fields.includes(`Card dispute renamed ${RUN}`),
        { refusedStale, afterReload, fields },
      );
      const notice = page.getByTestId('skill-kept-copy');
      await page.getByTestId('skill-kept-copy-open').click();
      const copy = page.getByTestId('skill-kept-copy-text');
      await copy.waitFor({ timeout: 10_000 }).catch(() => undefined);
      const copyText = (await copy.innerText().catch(() => '')) ?? '';
      const copyLocked = await copy.locator('[contenteditable="true"]').count();
      check('10 his text is kept as a read-only copy he can open', (await notice.count()) === 1 && /Then thank them\./.test(copyText) && copyLocked === 0, { copyText, copyLocked });
      await shootBothWidths(page, AREA, 'uc-757-skill-kept-copy', async () => {
        await page.waitForTimeout(600);
        await notice.scrollIntoViewIfNeeded().catch(() => undefined);
      });
      // He copies his sentence across by hand; the save keeps their text with it, and their name.
      await lineOf(THEIRS).click();
      await page.keyboard.press('End');
      await page.keyboard.insertText(' Then thank them.');
      const onTop = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url() === `${agents}/v1/skills/${skill.id}/draft`, { timeout: 60_000 }));
      await saveSkill(page);
      const top = (await (await onTop).json()).data ?? {};
      const topSteps = top.content?.steps ?? [];
      const said = topSteps.map((s) => s.do ?? '').join('\n');
      check('10 the save after Reload keeps their text and what he copied in', top.name === `Card dispute renamed ${RUN}` && said.includes(THEIRS) && /Then thank them\./.test(said) && topSteps.some((s) => s.use?.id === kept.use?.id), { name: top.name, topSteps });
      await page.getByTestId('skill-kept-copy-drop').click();
      check('10 dropping the copy closes the notice', (await notice.count()) === 0, await notice.count());
      // The race: Reload refetches the skill, and the editor must open on that copy, not on the one read before it.
      // Five rounds in a row on a page whose timers run late, so the cache tells the page a moment after the read lands.
      const raced = await made('/v1/skills', { name: `Reload race ${RUN}`, ownerTeam: 'team_ops', useWhen: 'The cardholder asks what happens next.', instructions: '', source: 'Say hello to the cardholder.\nTell them what happens next.' });
      const slow = await page.context().newPage();
      watch(slow, 'james-slow');
      await slow.addInitScript(() => {
        const real = window.setTimeout.bind(window);
        window.setTimeout = (fn, ms, ...rest) => real(fn, ms === undefined || ms === 0 ? 60 : ms, ...rest);
      });
      const slowLine = (text) => slow.getByTestId('sop-editor').locator('.cm-line', { hasText: text });
      const rounds = [];
      for (let n = 1; n <= 5; n += 1) {
        await slow.goto(`${consoleUrl}/build/skills/${raced.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await slowLine('Tell them what happens next').waitFor({ timeout: 120_000 });
        await slowLine('Tell them what happens next').click();
        await slow.keyboard.press('End');
        await slow.keyboard.insertText(` mine${n}.`);
        const read = (await (await fetch(`${agents}/v1/skills/${raced.id}`, { headers: J })).json()).data;
        const put = await fetch(`${agents}/v1/skills/${raced.id}/draft`, { method: 'PUT', headers: J, body: JSON.stringify({ source: `${read.text}\nSay theirs${n}.`, baseVersion: read.version, baseDigest: read.digest }) });
        await saveSkill(slow);
        await slow.getByTestId('skill-stale-base').waitFor({ timeout: 30_000 });
        await slow.getByTestId('skill-stale-reload').click();
        await slow.getByTestId('skill-stale-base').waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
        await slowLine(`theirs${n}`).waitFor({ timeout: 30_000 }).catch(() => undefined);
        const shown = await slow.getByTestId('sop-editor-content').innerText();
        await slow.getByTestId('skill-kept-copy-open').click().catch(() => undefined);
        const copied = await slow.getByTestId('skill-kept-copy-text').innerText().catch(() => '');
        // Long enough for a save to land, were one going to.
        await slow.waitForTimeout(1500);
        const stored = (await (await fetch(`${agents}/v1/skills/${raced.id}`, { headers: J })).json()).data?.text ?? '';
        rounds.push({ n, put: put.status, shown: shown.includes(`theirs${n}`) && !shown.includes(`mine${n}`), copy: copied.includes(`mine${n}`), kept: stored.includes(`theirs${n}`) && !stored.includes(`mine${n}`) });
        await slow.getByTestId('skill-kept-copy-drop').click().catch(() => undefined);
      }
      check('10 Reload shows the newest saved text and keeps his as a copy, five times in a row', rounds.every((r) => r.put === 200 && r.shown && r.copy && r.kept), rounds);
      await slow.close();
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
      // A condition in words is judged by a model; only a condition on a value reads as checked.
      check('10 an if line shows that the agent decides', (await legend.count()) >= 1 && /^judged$/.test(await legend.first().innerText()), await legend.allInnerTexts());
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
      check('14 the brief saves on its own and the status says it', (await saved).ok() && (await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 30_000 }).then(() => true, () => false)), await page.getByTestId('save-state').innerText());
      const after = (await (await fetch(`${agents}/v1/agents/${agent.id}`, { headers: J })).json()).data;
      check('15 the agent now holds the tool and its brief mentions it', after.toolIds.length === 1 && /@tool:/.test(after.brief.howToAnswer), { toolIds: after.toolIds, how: after.brief?.howToAnswer });

      // 16. The model and limits form stays closed until opened; the leave guard holds unsaved text.
      await page.getByRole('tab', { name: 'Limits' }).click();
      await page.getByTestId('agent-model-limits').waitFor({ timeout: 60_000 });
      check('16 the Limits tab opens to the model, thinking and the rules and limits', (await page.getByTestId('agent-model-limits').isVisible()) && (await page.getByTestId('agent-rules-and-limits').isVisible()));
      // This agent has no model chosen, as every agent made from the SDK or the command line: how it thinks still saves.
      const thought = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`), { timeout: 60_000 });
      await page.locator('#ag-thinking').click();
      await page.getByRole('option', { name: 'High' }).click();
      const saidHigh = (await (await thought).json()).data?.patterns?.thinking;
      check('16 with no model chosen, a change to Thinking still saves', saidHigh === 'high', saidHigh);

      // 20. Priya saves the agent while James has it open: his next change is not saved over hers, and the page says so.
      const agentSave = (r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`);
      // She changes the brief's Goal; he then changes its Job. The brief is saved whole, so his save must carry her Goal.
      const opened = (await (await fetch(`${agents}/v1/agents/${agent.id}`, { headers: J })).json()).data;
      const herGoal = 'Every dispute ends with a dated next step.';
      const hers = await saveAgent(agents, as(await tokenFor(PRIYA)), agent.id, { skillMenu: 'attached', brief: { ...opened.brief, goal: herGoal }, patterns: { ...opened.patterns, parallelReads: false } });
      const refused = page.waitForResponse(agentSave, { timeout: 60_000 });
      // Thinking's save from step 16 lands first; the brief is read-only while a save is in flight.
      await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 30_000 });
      await page.getByRole('tab', { name: 'Settings' }).click();
      // The brief's editor draws after the tab opens; text typed before it is ready goes nowhere.
      await brief.locator('[contenteditable="true"]').first().waitFor({ timeout: 30_000 });
      // The Job text itself: the group's middle can fall on its locked heading, which takes no cursor.
      await brief.getByRole('group', { name: 'Job' }).locator('[data-node-view-content]').first().click();
      await page.keyboard.press('End');
      await page.keyboard.insertText(' By phone or chat.');
      const typed = await brief.getByText('By phone or chat.').first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
      // Thinking sits in the same group of settings as the parallel reads she switched off, on the Limits tab; the
      // draft is kept across tabs.
      await page.getByRole('tab', { name: 'Limits' }).click();
      await page.locator('#ag-thinking').click();
      await page.getByRole('option', { name: 'Low' }).click();
      const refusedWith = (await refused).status();
      // The notice sits above the brief, on Settings.
      await page.getByRole('tab', { name: 'Settings' }).click();
      const told = await page.getByTestId('agent-stale-base').waitFor({ timeout: 30_000 }).then(() => page.getByTestId('agent-stale-base').innerText(), () => '');
      check('20 a change made after another person saved is refused, and the page says who saved', hers.ok && refusedWith === 409 && /p\.shah@harborpine\.example saved a newer draft/.test(told), { hers: hers.status, refusedWith, told });
      const resent = page.waitForResponse((r) => agentSave(r) && r.ok(), { timeout: 60_000 });
      await page.getByTestId('agent-stale-reload').click();
      const both = (await (await resent).json()).data;
      check('20 reloading keeps his unsaved change and hers, in the brief and in a group of settings', / By phone or chat\.$/.test(both?.brief?.purpose ?? '') && both?.brief?.goal === herGoal && both?.patterns?.thinking === 'low' && both?.patterns?.parallelReads === false && both?.skillMenu === 'attached' && (await page.getByTestId('agent-stale-base').count()) === 0, { typed, purpose: both?.brief?.purpose, goal: both?.brief?.goal, patterns: both?.patterns, skillMenu: both?.skillMenu });

      // 21. His own save from elsewhere is no clash to tell him about: the page reads the agent again and saves.
      await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 30_000 });
      await saveAgent(agents, J, agent.id, { skillMenu: 'team' });
      const answers = [];
      const note = (r) => agentSave(r) && answers.push(r.status());
      page.on('response', note);
      const landed = page.waitForResponse((r) => agentSave(r) && r.ok(), { timeout: 60_000 });
      await page.getByRole('tab', { name: 'Limits' }).click();
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
      // What the agent uses is a line of links under the brief; model and limits are on the Limits tab.
      const sheet = await maya.getByTestId('agent-uses-link').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      await maya.getByRole('tab', { name: 'Limits' }).click();
      const limits = await maya.getByTestId('agent-model-limits').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      check('18 a reviewer can open what the agent uses and its model and limits, with the fields off', sheet && limits && (await maya.locator('#ag-thinking').isDisabled()), { sheet, limits });
      await shootBothWidths(maya, AREA, 'uc-757-agent-member', async () => {});
      await maya.goto(`${consoleUrl}/build/skills/${skill.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('sop-editor-content').waitFor({ timeout: 120_000 });
      await shootBothWidths(maya, AREA, 'uc-757-skill-member', async () => {});

      // 28. An agent whose brief was saved before sections opens as it was: no added section, and View prompt reads
      // what the service writes. James then adds Tone from the Add section menu and a section of his own,
      // and View prompt shows both in their places with Never last. Maya, who cannot edit, reads the
      // sections with no control to add or remove one. What the page is asked for beyond the design's words: each added
      // section is a group named by its title, as the fixed fields are; Add custom section is a button in the brief or
      // an item of the Add section menu; its name field is labelled Section name and Enter confirms it; each remove
      // control's name starts with Remove.
      const tried = (p) => p.then(() => true, () => false);
      const MENU = ['Personality', 'Tone', 'Environment', 'Context', 'Tool use', 'Error handling', 'Escalation wording'];
      const briefOf = (p) => p.getByTestId('agent-brief');
      const sectionOf = (p, name) => briefOf(p).getByRole('group', { name, exact: true });
      const addSection = (p) => briefOf(p).getByRole('button', { name: 'Add section' });
      const removes = (p) => briefOf(p).getByRole('button', { name: /^Remove\b/ });
      const promptShown = async (p) => {
        await p.getByTestId('agent-view-prompt').click({ timeout: 10_000 }).catch(() => undefined);
        // The dialog draws a skeleton until the prompt is read.
        await p.getByTestId('agent-prompt-text').filter({ hasText: '# Who you are' }).waitFor({ timeout: 15_000 }).catch(() => undefined);
        const text = await p.getByTestId('agent-prompt-text').innerText({ timeout: 5_000 }).catch(() => '');
        await p.keyboard.press('Escape');
        return text.trim();
      };
      const NEVER_RULE = 'Promise a refund before the review';
      const sectioned = await made('/v1/agents', { name: `Sections desk ${RUN}`, role: 'Helps cardholders with disputes' });
      await made(`/v1/agents/${sectioned.id}`, { brief: { purpose: 'Help cardholders dispute a charge.', howToAnswer: 'Keep answers short.', handOff: ['The cardholder asks for a person.'], never: [NEVER_RULE] }, ...(await agentBase(agents, J, sectioned.id)) }, 'PATCH');
      const servedPrompt = async () => ((await (await fetch(`${agents}/v1/agents/${sectioned.id}/prompt`, { headers: J })).json()).data?.text ?? '').trim();
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${consoleUrl}/build/agents/${sectioned.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await brief.waitFor({ timeout: 120_000 });
      await page.getByTestId('agent-uses-link').waitFor({ timeout: 60_000 });
      await sectionOf(page, 'How to answer').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const before = { added: (await Promise.all(MENU.map((n) => sectionOf(page, n).count()))).reduce((a, b) => a + b, 0), prompt: await promptShown(page), served: await servedPrompt() };
      check('28 a brief saved before sections opens with none added, and View prompt reads as the service writes it', before.added === 0 && before.prompt.length > 0 && before.prompt === before.served && !/^# Tone$/m.test(before.prompt), before);

      const sectionsSaved = armed(page.waitForResponse(async (r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${sectioned.id}` && r.ok() && ((await r.json().catch(() => ({}))).data?.brief?.sections ?? []).filter((x) => x.text).length === 2, { timeout: 30_000 }));
      const write = async (name, text) => {
        const group = sectionOf(page, name);
        if (!(await tried(group.waitFor({ timeout: 10_000 })))) return false;
        // The section's text itself: the group's middle can fall on its locked heading, which takes no cursor.
        await group.locator('[data-node-view-content]').first().click({ timeout: 5_000 }).catch(() => group.click({ timeout: 5_000 }).catch(() => undefined));
        await page.keyboard.insertText(text);
        return true;
      };
      await addSection(page).click({ timeout: 10_000 }).catch(() => undefined);
      await page.getByRole('menuitem', { name: 'Tone', exact: true }).click({ timeout: 10_000 }).catch(() => undefined);
      const toneDrawn = await write('Tone', 'Calm and plain.');
      // The brief is read-only while a save is in flight.
      if (toneDrawn) await page.locator('[data-testid="save-state"][data-state="saved"]').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const ownButton = briefOf(page).getByRole('button', { name: 'Add custom section' });
      if (await ownButton.count()) await ownButton.click({ timeout: 10_000 }).catch(() => undefined);
      else {
        await addSection(page).click({ timeout: 10_000 }).catch(() => undefined);
        await page.getByRole('menuitem', { name: 'Add custom section' }).click({ timeout: 10_000 }).catch(() => undefined);
      }
      const named = await tried(page.getByLabel('Section name').fill('Refund wording', { timeout: 10_000 }));
      if (named) await page.keyboard.press('Enter');
      const ownDrawn = named && (await write('Refund wording', 'Say refund, never reimbursement.'));
      const storedSections = (await (await sectionsSaved.catch(() => null))?.json().catch(() => ({})))?.data?.brief?.sections ?? null;
      const controls = { add: await addSection(page).count(), remove: await removes(page).count() };
      check(
        '28 a builder adds Tone and a section of his own, and both save with their kind and title',
        toneDrawn && ownDrawn && (storedSections ?? []).map((x) => [x.kind, x.name, x.text].join('|')).join(';') === 'tone|Tone|Calm and plain.;custom|Refund wording|Say refund, never reimbursement.' && controls.add === 1 && controls.remove >= 2,
        { toneDrawn, named, ownDrawn, storedSections, controls },
      );
      const withSections = await promptShown(page);
      const places = ['# Tone', '# How to answer', '# Refund wording', '# Hand off when', '# Never'].map((h) => withSections.split('\n').indexOf(h));
      check('28 View prompt shows Tone before How to answer, his section after it, and Never last', places.every((at, i) => at >= 0 && (i === 0 || at > places[i - 1])) && withSections.endsWith(NEVER_RULE), { places, tail: withSections.slice(-120) });
      await page.setViewportSize({ width: 390, height: 844 });
      const narrow = { tone: await tried(sectionOf(page, 'Tone').waitFor({ timeout: 10_000 })), add: await addSection(page).isVisible().catch(() => false), wide: await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) };
      check('28 at 390 wide the added sections and Add section are drawn and the page does not scroll sideways', narrow.tone && narrow.add && narrow.wide <= 1, narrow);
      await shootBothWidths(page, AREA, 'uc-757-agent-sections-admin', async () => {
        await sectionOf(page, 'Tone').scrollIntoViewIfNeeded({ timeout: 2_000 }).catch(() => undefined);
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await maya.setViewportSize({ width: 1440, height: 1000 });
      await maya.goto(`${consoleUrl}/build/agents/${sectioned.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('agent-brief').waitFor({ timeout: 120_000 });
      await maya.getByTestId('read-only-notice').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const read = { tone: await sectionOf(maya, 'Tone').innerText({ timeout: 10_000 }).catch(() => ''), own: await sectionOf(maya, 'Refund wording').innerText({ timeout: 10_000 }).catch(() => ''), add: await addSection(maya).count(), remove: await removes(maya).count() };
      check('28 a person who cannot edit reads the sections with no control to add or remove one', /Calm and plain\./.test(read.tone) && /Say refund/.test(read.own) && read.add === 0 && read.remove === 0, read);
      await shootBothWidths(maya, AREA, 'uc-757-agent-sections-member', async () => {
        await sectionOf(maya, 'Tone').scrollIntoViewIfNeeded({ timeout: 2_000 }).catch(() => undefined);
      });
      await maya.setViewportSize({ width: 1440, height: 1000 });

      // 32. The list of sections is the workspace's. Priya (admin) adds Compliance notes on Settings > Agent
      // instructions; the list then places it before Tone and renames Tone to Voice; James adds it to an agent from
      // Add section and View prompt shows it in that place with Never last; the agent of step 28, saved before the
      // change, shows the prompt it had; a viewer reads the settings page with no control to change it; Reset to
      // default brings the first list back. What the page is asked for beyond the design's words: it is served at
      // /settings/agent-instructions under a heading named Agent instructions; its Add section button opens a field
      // labelled Section name that Enter confirms (a Save button, if the page has one, sends it); Reset to default is
      // a button, and a dialog that asks first has a button whose name starts with Reset.
      // TODO manual: moving a section with the page's own control. The move is saved through the list's route here,
      // which is the save that control sends.
      const LIST = `${agents}/v1/agent-instruction-sections`;
      const VIEWER = 'r.menon@harborpine.example';
      const P = as(await tokenFor(PRIYA));
      const listNow = async () => (await (await fetch(LIST, { headers: P })).json().catch(() => ({}))).data ?? {};
      const inOrder = (list) => [...(list.sections ?? [])].sort((a, b) => a.order - b.order);
      const complianceIn = (list) => (list.sections ?? []).find((x) => x.label === 'Compliance notes');
      const firstList = await listNow();
      const settingsLog = [];
      // These pages keep their own log, so a fault on the settings page fails this step and not step 19.
      const signInApart = async (email) => {
        const p = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
        p.on('pageerror', (e) => settingsLog.push(`${email.split('@')[0]}: ${e.message}`));
        p.on('response', (r) => r.status() >= 400 && r.status() !== 401 && settingsLog.push(`${email.split('@')[0]}: ${r.status()} ${r.request().method()} ${r.url()}`));
        await p.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await p.getByLabel('Email').fill(email);
        await p.getByLabel('Password').fill(PASSWORD);
        await p.getByRole('button', { name: /^Sign in/ }).first().click();
        await p.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return p;
      };
      const openSettings = async (p) => {
        await p.goto(`${consoleUrl}/settings/agent-instructions`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        return tried(p.getByRole('heading', { name: 'Agent instructions' }).first().waitFor({ timeout: 60_000 }));
      };
      const listControls = async (p) => ({ add: await p.getByRole('button', { name: 'Add section' }).count(), reset: await p.getByRole('button', { name: 'Reset to default' }).count() });
      const sideways = (p) => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const oldPrompt = await servedPrompt();
      try {
        const priya = await signInApart(PRIYA);
        const opened = await openSettings(priya);
        const listSaved = armed(priya.waitForResponse((r) => r.request().method() === 'PUT' && r.url() === LIST && r.ok(), { timeout: 30_000 }));
        await priya.getByRole('button', { name: 'Add section' }).click({ timeout: 10_000 }).catch(() => undefined);
        const typed = await tried(priya.getByLabel('Section name').fill('Compliance notes', { timeout: 10_000 }));
        if (typed) await priya.keyboard.press('Enter');
        await priya.getByRole('button', { name: 'Save', exact: true }).click({ timeout: 2_000 }).catch(() => undefined);
        await listSaved.catch(() => undefined);
        const added = complianceIn(await listNow()) ?? {};
        check('32 an admin adds Compliance notes on Settings > Agent instructions, and the workspace list holds it as a menu section', opened && typed && Boolean(added.id) && added.kind === 'menu', { opened, typed, added });

        // The list now puts Compliance notes before Tone and names Tone Voice; a list that only appends fails the order below.
        const others = inOrder(await listNow()).filter((x) => x.label !== 'Compliance notes').map((x) => (x.id === 'tone' ? { ...x, label: 'Voice' } : x));
        const at = Math.max(0, others.findIndex((x) => x.id === 'tone'));
        const placed = [...others.slice(0, at), added, ...others.slice(at)].map((x, n) => ({ ...x, order: n }));
        const moved = await fetch(LIST, { method: 'PUT', headers: P, body: JSON.stringify({ ...firstList, sections: placed }) });
        const noted = await made('/v1/agents', { name: `Compliance desk ${RUN}`, role: 'Helps cardholders with disputes' });
        const notedSave = await fetch(`${agents}/v1/agents/${noted.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ brief: { purpose: 'Help cardholders dispute a charge.', howToAnswer: 'Keep answers short.', handOff: ['The cardholder asks for a person.'], never: [NEVER_RULE], sections: [{ kind: 'tone', text: 'Calm and plain.' }] }, ...(await agentBase(agents, J, noted.id)) }) });
        await page.goto(`${consoleUrl}/build/agents/${noted.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await brief.waitFor({ timeout: 120_000 });
        await sectionOf(page, 'How to answer').waitFor({ timeout: 60_000 }).catch(() => undefined);
        const notedSaved = armed(page.waitForResponse(async (r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${noted.id}` && r.ok() && ((await r.json().catch(() => ({}))).data?.brief?.sections ?? []).some((x) => x.name === 'Compliance notes' && x.text), { timeout: 30_000 }));
        await addSection(page).click({ timeout: 10_000 }).catch(() => undefined);
        await page.getByRole('menuitem', { name: 'Compliance notes', exact: true }).click({ timeout: 10_000 }).catch(() => undefined);
        const drawn = await write('Compliance notes', 'Say the call is recorded.');
        const stored = Boolean(await notedSaved.catch(() => null));
        const notedPrompt = await promptShown(page);
        const order = ['# Compliance notes', '# Voice', '# How to answer', '# Hand off when', '# Never'].map((h) => notedPrompt.split('\n').indexOf(h));
        check(
          '32 a builder adds Compliance notes from Add section, and View prompt shows it where the list puts it, before the renamed Tone, with Never last',
          moved.status === 200 && notedSave.ok && drawn && stored && order.every((n, i) => n >= 0 && (i === 0 || n > order[i - 1])) && notedPrompt.endsWith(NEVER_RULE),
          { moved: moved.status, notedSave: notedSave.status, drawn, stored, order, tail: notedPrompt.slice(-120) },
        );
        await page.goto(`${consoleUrl}/build/agents/${sectioned.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await brief.waitFor({ timeout: 120_000 });
        await sectionOf(page, 'How to answer').waitFor({ timeout: 60_000 }).catch(() => undefined);
        const oldShown = await promptShown(page);
        check('32 the agent saved before the list changed shows the prompt it had, Tone under its first name', moved.status === 200 && oldShown.length > 0 && oldShown === oldPrompt && /^# Tone$/m.test(oldShown) && !/^# Voice$/m.test(oldShown), { same: oldShown === oldPrompt, head: oldShown.slice(0, 160) });

        const viewer = await signInApart(VIEWER);
        const viewerOpened = await openSettings(viewer);
        const reads = { row: await tried(viewer.getByText('Compliance notes', { exact: true }).first().waitFor({ timeout: 30_000 })), ...(await listControls(viewer)) };
        const admin = await listControls(priya);
        check('32 a viewer reads the list on the settings page with no Add section and no Reset to default, which the admin has', viewerOpened && reads.row && reads.add === 0 && reads.reset === 0 && admin.add === 1 && admin.reset === 1, { viewerOpened, reads, admin });
        const wide = {};
        for (const [who, p] of [['admin', priya], ['member', viewer]]) {
          await p.setViewportSize({ width: 390, height: 844 });
          wide[who] = { row: await p.getByText('Compliance notes', { exact: true }).first().isVisible().catch(() => false), sideways: await sideways(p) };
          await shootBothWidths(p, AREA, `uc-757-agent-instruction-sections-${who}`, async () => undefined);
          await p.setViewportSize({ width: 1440, height: 1000 });
        }
        check('32 at 390 wide the settings page draws the list for both people and does not scroll sideways', Object.values(wide).every((w) => w.row && w.sideways <= 1), wide);

        const listReset = armed(priya.waitForResponse((r) => r.request().method() === 'DELETE' && r.url() === LIST && r.ok(), { timeout: 30_000 }));
        await priya.getByRole('button', { name: 'Reset to default' }).click({ timeout: 10_000 }).catch(() => undefined);
        await priya.getByRole('alertdialog').getByRole('button', { name: /^Reset/ }).click({ timeout: 3_000 }).catch(() => undefined);
        const resetSent = Boolean(await listReset.catch(() => null));
        const lastList = await listNow();
        check('32 Reset to default on the settings page brings the first list back', resetSent && (firstList.sections ?? []).length > 0 && JSON.stringify(inOrder(lastList)) === JSON.stringify(inOrder(firstList)), { resetSent, compliance: complianceIn(lastList) ?? null, sections: (lastList.sections ?? []).length });
        check('32 the settings pages log no page errors and no refused requests', settingsLog.length === 0, settingsLog);
      } finally {
        // The later steps read the default list whatever this one did.
        await fetch(LIST, { method: 'DELETE', headers: P }).catch(() => undefined);
      }

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
      failed.push(...unrenewed());
      check('19 no page errors and no failed requests', errors.length === 0 && failed.length === 0, { errors, failed });
      console.log(`walk: ${errors.length} console errors, ${failed.length} failed requests`, errors, failed);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
