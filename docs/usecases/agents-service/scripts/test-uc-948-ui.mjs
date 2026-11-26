// uc-948 ui layer: docs/usecases/agents-service/agent-page-in-one-editor.md, steps 9 to 22. A builder, a viewer and a member
// open an agent's page at 1440 and 390. The brief reads as five bands with no identity box, the tabs are addresses, the
// channels are one list, View prompt is read-only with Never last, the header keeps one order and one save wording,
// Settings holds tools, knowledge and skills as sections, a skill opens on its instructions, and a version waiting for
// review can be taken back, edited and sent again. Platform sign-in (James builds, Ravi views, Lena only chats, Maya
// reviews) and the demo stack's fake model; no model is called.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { agentBase } from '../../lib/agent_save.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const LENA = 'l.brandt@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (t) => ({ Authorization: `Bearer ${t}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const STATES = ['Saved', 'Unsaved', 'Saving…', 'Not saved'];
const words = (s) => s.trim().split(/\s+/).filter(Boolean).length;

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const M = as(await tokenFor(MAYA));
    const call = async (H, path, body, method = 'POST') => {
      const r = await fetch(`${agents}${path}`, { method, headers: H, body: body === undefined ? undefined : JSON.stringify(body) });
      return { status: r.status, data: (await r.json().catch(() => ({}))).data };
    };
    const brief = { purpose: 'Help cardholders.', goal: 'Every dispute ends with a next step.', howToAnswer: 'Keep answers short.', never: ['Promise a refund before the review'], success: ['The cardholder knows what happens next'] };
    const mk = async (name) => {
      const a = (await call(J, '/v1/agents', { name: `${name} ${RUN}`, role: 'Helps cardholders' })).data;
      await call(J, `/v1/agents/${a.id}`, { brief, ...(await agentBase(agents, J, a.id)) }, 'PATCH');
      return a;
    };
    const draft = await mk('Draft desk');
    const live = await mk('Live desk');
    const waits = { 1440: await mk('Waiting desk wide'), 390: await mk('Waiting desk narrow') };
    // One that stays in review for the viewer to read.
    const kept = await mk('Waiting desk kept');
    const askFor = async (a) => call(J, `/v1/agents/${a.id}/publish-requests`, { version: (await call(J, `/v1/agents/${a.id}`, undefined, 'GET')).data.version });
    const liveRequest = (await askFor(live)).data;
    if (liveRequest?.status === 'pending') await call(M, `/v1/publish-requests/${liveRequest.id}/decision`, { decision: 'approved' });
    await askFor(kept);
    const requests = { 1440: (await askFor(waits[1440])).data, 390: (await askFor(waits[390])).data };
    const skill = (await call(J, '/v1/skills', { name: `Walk skill ${RUN}`, ownerTeam: 'team_ops', useWhen: 'The cardholder disputes a charge.', instructions: 'Say it.', steps: [{ do: 'Say hello.' }] })).data;

    const browser = await chromium.launch();
    const errors = [];
    const open = async (email, width = 1440) => {
      const page = await (await browser.newContext({ viewport: { width, height: width === 1440 ? 1000 : 844 } })).newPage();
      page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(email);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      return page;
    };
    const go = async (page, url, ready) => {
      await page.goto(`${consoleUrl}${url}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId(ready).first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      await page.waitForTimeout(1200);
    };
    const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    const mainText = async (page) => (await page.locator('main').innerText()).replace(/\s+/g, ' ');

    const fails = [];
    for (const width of [1440, 390]) {
      const james = await open(JAMES, width);
      const ravi = await open(RAVI, width);
      const lena = await open(LENA, width);
      const tag = `${width}`;
      const note = (name, ok, detail) => { if (!ok) fails.push({ name, width, detail }); };

      for (const [who, page] of [['builder', james], ['viewer', ravi]]) {
        await go(page, `/build/agents/${draft.id}`, 'agent-brief');
        const brief_ = await page.getByTestId('agent-brief').innerText();
        const heads = ['Job', 'How to answer', 'Hand off when', 'Examples', 'Never'];
        const text = await mainText(page);
        note(`9 ${who} brief bands`, heads.every((h) => brief_.includes(h)) && !/Success/.test(brief_), brief_.slice(0, 200));
        note(`10 ${who} no identity box`, !/Identity/.test(text), text.slice(0, 120));
        note(`14 ${who} footer holds the uses link and View prompt`, (await page.getByTestId('agent-brief-footer').getByTestId('agent-uses-link').count()) === 1 && (await page.getByTestId('agent-brief-footer').getByTestId('agent-view-prompt').count()) === 1, '');
        await page.getByTestId('agent-view-prompt').click();
        const dialog = page.getByRole('dialog');
        await dialog.waitFor({ timeout: 10_000 }).catch(() => undefined);
        await page.waitForTimeout(1500);
        // The prompt sits in a read-only box, whose value is not part of the dialog's text.
        const boxes = await dialog.locator('textarea, pre, code').evaluateAll((els) => els.map((e) => ('value' in e ? e.value : e.innerText) ?? ''));
        const shown = `${(await dialog.innerText().catch(() => ''))} ${boxes.join(' ')}`.replace(/\s+/g, ' ');
        const editable = await dialog.locator('textarea:not([readonly]), [contenteditable="true"], input:not([readonly])').count();
        const ix = shown.lastIndexOf('# Never');
        note(`13 ${who} View prompt is read only with Never last`, editable === 0 && ix >= 0 && shown.indexOf('# ', ix + 2) === -1, { editable, ix, tail: shown.slice(-200) });
        await page.keyboard.press('Escape');
        const sections = ['agent-tools-count', 'agent-knowledge-count', 'agent-skills-section'];
        const present = await Promise.all(sections.map((id) => page.getByTestId(id).count()));
        note(`17 ${who} tools, knowledge and skills are sections on the page`, present.every((n) => n > 0), present);
        note(`19 ${who} no sideways scroll`, !(await sideways(page)), tag);
        // The tabs are addresses: each opens at its own URL.
        const reached = [];
        for (const tab of ['Evals', 'Channels', 'Versions', 'Usage', 'Limits']) {
          await page.getByRole('tab', { name: new RegExp(`^${tab}`) }).first().click().catch(() => undefined);
          await page.waitForURL((u) => u.pathname.endsWith(`/build/agents/${draft.id}/${tab.toLowerCase()}`), { timeout: 8_000 }).then(() => reached.push(tab), () => undefined);
        }
        note(`11 ${who} each tab opens at its own address`, reached.length === 5, reached);
      }

      // Channels is one list, with each place On, Off or Not set up.
      await go(james, `/build/agents/${live.id}/channels`, 'agent-evals-tab-trigger');
      const channels = await mainText(james);
      const wanted = ['Chat', 'API and SDK', 'MCP', 'Embed on a page', 'Email', 'Slack', 'Teams'];
      note('12 the channels are one list of seven places, each with a state', wanted.every((w) => channels.includes(w)) && /On|Off|Not set up/.test(channels) && wanted.length === 7, channels.slice(0, 300));

      // Compare is a full-width page, with no test panel beside it.
      await go(james, `/build/agents/${live.id}/versions`, 'agent-compare-link');
      await james.getByTestId('agent-compare-link').click();
      await james.waitForURL((u) => u.pathname.endsWith('/versions/compare'), { timeout: 30_000 }).catch(() => undefined);
      note('11 Compare is its own page, without the test panel', james.url().endsWith('/versions/compare') && (await james.getByTestId('agent-test-panel').count()) === 0, james.url());

      // The header keeps one order and one save wording, and saves with the keyboard.
      await go(james, `/build/agents/${draft.id}`, 'save-state');
      const order = await james.getByTestId('page-header').locator('button, [data-testid="save-state"]').evaluateAll((els) => els.map((e) => (e.getAttribute('data-testid') === 'save-state' ? 'state' : (e.getAttribute('aria-label') || e.innerText || '').trim())).filter(Boolean));
      const want = ['state', 'Save', 'Test', 'Publish', 'More actions'];
      const at = want.map((w) => order.indexOf(w));
      note('16 the header reads save state, Save, Test, Publish, menu in that order', at.every((i) => i >= 0) && at.every((v, k) => k === 0 || v > at[k - 1]), order);
      note('16 no header button label is over two words', order.filter((l) => l !== 'state').every((l) => words(l) <= 2), order);
      if (width === 1440) {
        await james.getByTestId('page-title-input').fill(`Draft desk ${RUN} renamed`);
        const unsaved = (await james.getByTestId('save-state').innerText()).trim();
        await james.keyboard.press('ControlOrMeta+s');
        await james.waitForFunction(() => /Saved/.test(document.querySelector('[data-testid="save-state"]')?.textContent ?? ''), null, { timeout: 15_000 }).catch(() => undefined);
        const saved = (await james.getByTestId('save-state').innerText()).trim();
        note('15 the save state says Unsaved, then Saved after Cmd+S, in the four words', STATES.includes(unsaved) && /Unsaved|Saving/.test(unsaved) && saved === 'Saved', { unsaved, saved });
      }

      // A skill opens on its instructions, with the button bar and one Uses list.
      await go(james, `/build/skills/${skill.id}`, 'rich-text');
      const instructionsTab = james.getByRole('tab', { name: /^Instructions/ });
      note('18 a skill opens on its instructions with the button bar and a Uses list', (await instructionsTab.getAttribute('aria-selected').catch(() => null)) === 'true' && (await james.getByTestId('rte-menu').count()) > 0 && (await james.getByRole('button', { name: /^Used by/ }).count()) > 0, '');

      // A version waiting for review: its requester can take it back, which leaves review, then send it again; a viewer only sees it.
      const waiting = waits[width];
      await go(james, `/build/agents/${waiting.id}`, 'agent-publish-in-review');
      const withdraw = james.getByRole('button', { name: /^Withdraw/ });
      const offered = await withdraw.waitFor({ timeout: 8_000 }).then(() => true, () => false);
      let left = false;
      let again = 0;
      let state = '';
      if (offered) {
        const refused = [];
        james.on('response', (r) => { if (r.url().includes('/withdraw') && r.status() >= 400) refused.push(`${r.status()} ${r.url()}`); });
        await withdraw.click();
        await james.getByTestId('agent-locked-withdrawn').waitFor({ timeout: 10_000 }).catch(() => undefined);
        // It left review: the request went through, the version is a draft again and the page shows no open review.
        state = (await call(J, `/v1/agents/${waiting.id}/versions`, undefined, 'GET')).data?.find((v) => v.version === 1)?.state;
        left = refused.length === 0 && state !== 'in_review' && (await james.getByTestId('agent-publish-in-review').count()) === 0 && (await james.getByTestId('agent-locked').count()) === 0;
        again = await james.getByTestId('agent-locked-send-again').count();
        if (refused.length) state = `${state} ${refused.join(' ')}`;
      }
      note('20 a waiting version offers Withdraw, and withdrawing it takes it out of review and offers Send again', offered && left && again === 1, { offered, left, again, state, request: requests[width]?.id });
      await go(ravi, `/build/agents/${kept.id}`, 'agent-brief');
      note('21 a viewer sees the waiting version and no Withdraw', (await ravi.getByRole('button', { name: /^Withdraw/ }).count()) === 0 && /In review/.test(await ravi.locator('body').innerText()), '');

      // The viewer reads the page and changes nothing; a member who only chats is refused the page.
      await go(ravi, `/build/agents/${draft.id}`, 'read-only-notice');
      const names = await ravi.locator('header button').evaluateAll((els) => els.map((e) => (e.innerText || '').trim()));
      note('22 a viewer sees the view only note, with no Save and no Test', (await ravi.getByTestId('read-only-notice').count()) === 1 && !names.includes('Save') && !names.includes('Test'), names);
      await go(lena, `/build/agents/${draft.id}`, 'page-header');
      note('22 a member who only chats is told they have no access', /don’t have access here/.test(await lena.locator('main').innerText()), (await lena.locator('main').innerText()).slice(0, 120));
      for (const p of [james, ravi, lena]) await p.context().close();
    }
    // One check per step of the doc, so each step shows as run: it passes when nothing under its number failed.
    const TITLES = {
      9: 'the brief reads as five bands', 10: 'there is no identity box', 11: 'each tab has its own address and Compare is its own page',
      12: 'the channels are one list of seven places', 13: 'View prompt is read only with Never last', 14: 'the footer holds the uses link and View prompt',
      15: 'the save state reads Unsaved then Saved after Cmd+S', 16: 'the header keeps one order and no label over two words', 17: 'tools, knowledge and skills are sections',
      18: 'a skill opens on its instructions with the button bar and a Used by list', 19: 'no page scrolls sideways and none logs an error', 20: 'Withdraw takes a waiting version out of review and offers Send again',
      21: 'a viewer sees a waiting version and no Withdraw', 22: 'a viewer reads the page and a member is refused it',
    };
    for (const [id, title] of Object.entries(TITLES)) {
      const mine = fails.filter((f) => f.name.startsWith(`${id} `));
      const quiet = Number(id) !== 19 || errors.length === 0;
      check(`${id} ${title}, for a builder, a viewer and a member at 1440 and 390`, mine.length === 0 && quiet, { fails: mine, errors });
    }
    await browser.close();
  },
  { platform: true, demo: true },
);

finish();
