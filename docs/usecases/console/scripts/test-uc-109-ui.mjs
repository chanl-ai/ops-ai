// uc-109 an agent embedded on an intranet page answers from another origin, ui layer:
// docs/usecases/console/widget-embed-second-origin.md. Signed in through platform-service. James embeds a published
// agent from its Channels tab and copies the snippet; the demo intranet on a second origin carries that snippet, and
// Maya chats through it. The same page on an unlisted origin is refused.
import { spawn } from 'node:child_process';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const INTRANET_PORT = 4611;
const OTHER_PORT = 4612;
const intranet = `http://127.0.0.1:${INTRANET_PORT}`;
const NAME = `Branch Desk ${Math.random().toString(36).slice(2, 6)}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

// A response wait armed before the click; its rejection must not crash the script ahead of the harness cleanup.
const armedWait = (page, method) => {
  const p = page.waitForResponse((r) => r.request().method() === method && r.url().includes('/v1/channels/'), { timeout: 60_000 });
  p.catch(() => undefined);
  return p.catch(() => undefined);
};

function intranetOn(port, snippet) {
  const proc = spawn('node', [join(ROOT, 'services/agents-service/demo/intranet-page/serve.mjs'), String(port)], {
    env: { ...process.env, OPS_WIDGET_SNIPPET: snippet, PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}` },
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  return new Promise((resolve, reject) => {
    proc.stdout.on('data', (d) => String(d).includes('intranet demo on') && resolve(proc));
    proc.on('exit', (code) => reject(new Error(`intranet demo exited ${code}`)));
  });
}

await withUiStack(
  async (consoleUrl, stack) => {
    const J = as(await tokenFor('j.richardson@harborpine.example'));
    const made = await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: NAME, role: 'Answers branch questions' }) })).json();
    if (!made.data) throw new Error(`setup: create agent: ${JSON.stringify(made).slice(0, 300)}`);
    const pub = await fetch(`${agents}/v1/agents/${made.data.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: made.data.version, note: 'first' }) });
    if (!pub.ok) throw new Error(`setup: publish answered ${pub.status}: ${await pub.text()}`);

    const browser = await chromium.launch();
    const errors = [];
    const servers = [];
    try {
      // James embeds the agent from its Channels tab.
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      const james = await ctx.newPage();
      james.on('pageerror', (e) => errors.push(`console: ${e.message}`));
      await james.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByLabel('Email').fill('j.richardson@harborpine.example');
      await james.getByLabel('Password').fill('northfield-demo');
      await james.getByRole('button', { name: /^Sign in/ }).first().click();
      await james.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await james.goto(`${consoleUrl}/agents/${made.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('agent-channels-tab-trigger').click({ timeout: 120_000 });
      // A table's empty state fits a phone: the agent has no deployments yet, so the tab shows the empty state, and its
      // button must sit inside a 400 px viewport instead of at the end of a table wider than the screen.
      const phone = await (await browser.newContext({ viewport: { width: 400, height: 900 } })).newPage();
      await phone.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await phone.getByLabel('Email').fill('j.richardson@harborpine.example');
      await phone.getByLabel('Password').fill('northfield-demo');
      await phone.getByRole('button', { name: /^Sign in/ }).first().click();
      await phone.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await phone.goto(`${consoleUrl}/agents/${made.data.id}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // The Channels tab (c-130): the embeds section's empty line and its Embed on a page button.
      const emptyBox = await phone.getByText('No embeds yet.').boundingBox({ timeout: 120_000 }).catch(() => null);
      const create = await phone.getByTestId('widget-embed-open').boundingBox().catch(() => null);
      check('at 400 px the Channels tab\'s empty embeds line and its button sit inside the viewport', !!emptyBox && !!create && emptyBox.x >= 0 && emptyBox.x + emptyBox.width <= 400 && create.x >= 0 && create.x + create.width <= 400, { emptyBox, create });

      await james.getByTestId('widget-embed-open').click({ timeout: 60_000 });
      // A missing name is said under the name, and a missing origin under the origins, each field marked invalid.
      const dialog = james.getByRole('dialog', { name: 'Embed on a page' });
      await dialog.getByTestId('widget-embed-create').click();
      const nameField = dialog.locator('#widget-name');
      const fieldOf = (selector) => dialog.locator('div.flex.flex-col.gap-1\\.5').filter({ has: james.locator(selector) });
      const nameMsg = 'Name it so the team can tell embeds apart.';
      const originsMsg = 'Add the page origin, like https://intranet.bank.example.';
      await dialog.getByText(nameMsg).waitFor({ timeout: 15_000 }).catch(() => undefined);
      check('with nothing filled in, the name error sits under Name and the origin error under the origins, never one under the other', (await fieldOf('#widget-name').filter({ hasText: nameMsg }).count()) >= 1 && (await fieldOf('#widget-origins').filter({ hasText: nameMsg }).count()) === 0 && (await fieldOf('#widget-origins').filter({ hasText: originsMsg }).count()) >= 1 && (await nameField.getAttribute('aria-invalid')) === 'true');
      await james.getByLabel('Name').fill('Intranet help');
      await dialog.getByTestId('widget-embed-create').click();
      const originsField = dialog.locator('#widget-origins');
      await dialog.getByText(originsMsg).waitFor({ timeout: 15_000 }).catch(() => undefined);
      const placeholder = await originsField.getAttribute('placeholder');
      check('a missing origin is said under the origins, which are marked invalid, and the placeholder starts with e.g.', (await fieldOf('#widget-origins').filter({ hasText: originsMsg }).count()) >= 1 && (await originsField.getAttribute('aria-invalid')) === 'true' && (await nameField.getAttribute('aria-invalid')) !== 'true' && (placeholder ?? '').startsWith('e.g.'), { placeholder });
      const origins = james.getByLabel('Pages allowed to embed it');
      await origins.fill(intranet);
      await origins.press('Enter');
      const created = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/widget-deployments'), { timeout: 60_000 });
      await james.getByTestId('widget-embed-create').click();
      const status = (await created).status();
      const snippet = (await james.getByTestId('widget-snippet').innerText({ timeout: 30_000 })).trim();
      const dep = /deployment: "([^"]+)"/.exec(snippet)?.[1];
      check('the deploy dialog creates the embed and shows the page code for the embed loader with the deployment id and no key', status === 201 && !!dep && snippet.includes(`${stack.embedUrl}/embed/v1.js`) && snippet.includes('OpsChat.init') && !/ok_|api.?key|secret|getSsoToken/i.test(snippet), { status, snippet });

      // The embed table asks before it stops or moves a live chat, and the Snippet toggle says what it opens.
      const patches = [];
      james.on('request', (r) => (r.method() === 'PATCH' || r.method() === 'POST') && r.url().includes('/v1/channels/') && patches.push(r.url()));
      await james.getByRole('button', { name: 'Done' }).click();
      const row = james.getByTestId('widget-embeds').getByRole('row', { name: /Intranet help/ });
      const snippetToggle = row.getByRole('button', { name: 'Snippet' });
      await snippetToggle.click();
      const controls = await row.getByRole('button', { name: 'Hide snippet' }).getAttribute('aria-controls');
      const toggle = { expanded: await row.getByRole('button', { name: 'Hide snippet' }).getAttribute('aria-expanded'), opens: controls ? await james.locator(`#${controls}`).count() : 0 };
      await row.getByRole('button', { name: 'Hide snippet' }).click();
      await row.getByRole('button', { name: 'Pause' }).click();
      const ask = james.getByRole('dialog', { name: 'Pause Intranet help' });
      const said = await ask.getByText(intranet).waitFor({ timeout: 15_000 }).then(() => true, () => false);
      await ask.getByRole('button', { name: 'Cancel' }).click();
      await james.waitForTimeout(500);
      const untouched = patches.length === 0 && (await row.getByText('Paused').count()) === 0;
      await row.getByRole('button', { name: 'Pause' }).click();
      const paused = armedWait(james, 'PATCH');
      await james.getByRole('dialog', { name: 'Pause Intranet help' }).getByRole('button', { name: 'Pause', exact: true }).click();
      const pausedStatus = (await paused)?.status();
      const badge = await row.getByText('Paused').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      await row.getByRole('button', { name: 'Resume' }).click();
      const resumeAsk = await james.getByRole('dialog', { name: 'Resume Intranet help' }).getByText(intranet).waitFor({ timeout: 15_000 }).then(() => true, () => false);
      const resumed = armedWait(james, 'PATCH');
      await james.getByRole('dialog', { name: 'Resume Intranet help' }).getByRole('button', { name: 'Resume', exact: true }).click();
      const resumedStatus = (await resumed)?.status();
      check('Snippet says what it opens, and Pause and Resume name the pages and wait for a confirm', toggle.expanded === 'true' && toggle.opens === 1 && said && untouched && pausedStatus === 200 && badge && resumeAsk && resumedStatus === 200, { toggle, said, untouched, pausedStatus, badge, resumeAsk, resumedStatus });

      // Maya on the intranet, a second origin, chats with her SSO: the page loads /embed/v1.js and its getSession trades
      // the intranet's token for a session bound to that page (c-224 retired the first script, /widget/v1.js).
      const M = await tokenFor('m.okafor@harborpine.example');
      const tenant = JSON.parse(Buffer.from(M.split('.')[1], 'base64url').toString()).tenant_id;
      const embedTag = `<script src="${stack.embedUrl}/embed/v1.js" async></script>
<script>
  window.opsErrors = [];
  function start() {
    OpsChat.on('error', (e) => opsErrors.push(e && e.code));
    OpsChat.init({ deployment: ${JSON.stringify(dep)}, tenant: ${JSON.stringify(tenant)}, getSession: opsSessionFrom(${JSON.stringify(agents)}, ${JSON.stringify(dep)}) });
  }
  window.OpsChat ? start() : addEventListener('ops-chat:load', start);
</script>`;
      const gone = await fetch(`${agents}/widget/v1.js`);
      servers.push(await intranetOn(INTRANET_PORT, embedTag), await intranetOn(OTHER_PORT, embedTag));
      const maya = await (await browser.newContext()).newPage();
      maya.on('pageerror', (e) => errors.push(`intranet: ${e.message}`));
      const minted = maya.waitForResponse((r) => r.url().endsWith(`/v1/widget/${dep}/session`), { timeout: 60_000 });
      await maya.goto(intranet, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      await maya.waitForFunction(() => window.OpsChat && document.querySelector('[data-ops-chat]'), null, { timeout: 60_000 });
      await maya.evaluate(() => OpsChat.open());
      const session = await minted;
      let chat;
      for (let i = 0; i < 240 && !chat; i++) {
        chat = maya.frames().find((f) => f.url().startsWith(`${stack.embedUrl}/embed/${dep}`));
        if (!chat) await maya.waitForTimeout(250);
      }
      if (!chat) throw new Error('the chat frame never loaded');
      const question = 'What are your opening hours?';
      await chat.getByRole('textbox', { name: 'Message' }).fill(question);
      const streamed = maya.waitForResponse((r) => /\/v1\/widget\/[^/]+\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 });
      await chat.getByRole('button', { name: 'Send', exact: true }).click();
      const sent = await streamed;
      // The answer is whatever the frame shows after the question once the stream has ended.
      await sent.finished();
      await chat.waitForFunction((q) => { const t = document.body.innerText; return t.slice(t.lastIndexOf(q) + q.length).replace(/[…\s]/g, '').length > 0; }, question, { timeout: 120_000 }).catch(() => null);
      const body = await chat.locator('body').innerText();
      const reply = body.slice(body.lastIndexOf(question) + question.length).trim();
      check('a person on the intranet origin opens the chat, trades her SSO token for a session for that page and gets an answer; the first script answers 410', gone.status === 410 && session.status() === 201 && sent.status() === 200 && reply.length > 0 && !/unavailable/i.test(reply), { gone: gone.status, session: session.status(), sent: sent.status(), reply: reply.slice(0, 200) });

      // The same page served from an origin the deployment does not list: the config read is refused, so the loader
      // draws nothing and reports origin_not_allowed; the session exchange is refused too, with no CORS header.
      const stranger = await (await browser.newContext()).newPage();
      await stranger.goto(`http://127.0.0.1:${OTHER_PORT}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      await stranger.waitForFunction(() => window.opsErrors && window.opsErrors.length > 0, null, { timeout: 60_000 }).catch(() => null);
      const reported = await stranger.evaluate(() => window.opsErrors);
      const drawn = await stranger.locator('[data-ops-chat]').count();
      const direct = await fetch(`${agents}/v1/widget/${dep}/session`, { method: 'POST', headers: { Authorization: `Bearer ${M}`, Origin: `http://127.0.0.1:${OTHER_PORT}` } });
      const answer = await direct.json().catch(() => ({}));
      check('a page on an unlisted origin cannot start the chat', reported.includes('origin_not_allowed') && drawn === 0 && direct.status === 403 && answer?.error?.code === 'origin_not_allowed' && !direct.headers.get('access-control-allow-origin'), { reported, drawn, status: direct.status, code: answer?.error?.code });

      check('no page errors', errors.length === 0, errors);
    } finally {
      for (const s of servers) s.kill();
      await browser.close();
    }
  },
  { platform: true, embed: true },
);

finish();
