// uc-119 a bank page shows the full chat through the loader and the embed app, ui layer:
// docs/usecases/console/embedded-chat-on-a-bank-page.md (c-158). The stack runs with platform sign-in and the embed app;
// this script serves the bank's intranet page (which mints sessions on its own server with the deployment's mint key)
// and a page on an origin the deployment does not list, then drives them in a browser. Each check stands alone.
import { createServer } from 'node:http';

import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const HOST_PORT = 4621;
const OTHER_PORT = 4622;
const HOST = `http://127.0.0.1:${HOST_PORT}`;
const OTHER = `http://127.0.0.1:${OTHER_PORT}`;
const PASSWORD = 'northfield-demo';
const HOLD = 'call place_wire_hold {"wireId": "W-1", "hours": 24, "reason": "Unusual payee"}';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

/** The bank's intranet page: the loader, a server route that mints the session with the mint key, and a frame from another origin. */
function bankPage(embedUrl, dep, tenant, mintKey) {
  const html = (signedOut) => `<!doctype html><html><body><h1>Northfield intranet</h1>
<script src="${embedUrl}/embed/v1.js" async></script>
<script>
  window.events = []; window.signIns = 0;
  function start() {
    for (const e of ['ready', 'open', 'close', 'message', 'signed-out', 'error']) OpsChat.on(e, (p) => events.push([e, p ?? null]));
    OpsChat.init({
      deployment: ${JSON.stringify(dep)},
      tenant: ${JSON.stringify(tenant)},
      getSession: async () => ${signedOut ? 'null' : "(await (await fetch('/session', { method: 'POST' })).json())"},
      onSignIn: () => { window.signIns++; },
    });
  }
  window.OpsChat ? start() : addEventListener('ops-chat:load', start);
</script>
<iframe id="other" src="${OTHER}/forge.html" style="width:1px;height:1px"></iframe>
</body></html>`;
  return createServer(async (req, res) => {
    if (req.url === '/session' && req.method === 'POST') {
      const r = await fetch(`${agents}/v1/widget-deployments/${dep}/sessions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${mintKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'teller@bank.example', name: 'Tara Teller', origin: HOST }),
      });
      res.writeHead(r.ok ? 200 : 502, { 'Content-Type': 'application/json' });
      return res.end(r.ok ? JSON.stringify((await r.json()).data) : '{}');
    }
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html(req.url.includes('signedOut')));
  });
}

/** Another origin: a frame on the bank page that tries to sign the chat out, and a page of its own that frames the chat. */
function otherPage(embedUrl, dep, tenant) {
  return createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    if (req.url === '/forge.html') return res.end(`<!doctype html><script>window.forge = () => { for (let i = 0; i < parent.frames.length; i++) parent.frames[i].postMessage({ type: 'ops-chat:identify', session: null }, '*'); };</script>`);
    res.end(`<!doctype html><iframe id="chat" src="${embedUrl}/embed/${dep}?tenant=${tenant}"></iframe>`);
  });
}

const listen = (server, port) => new Promise((r) => server.listen(port, '127.0.0.1', () => r(server)));

await withUiStack(
  async (consoleUrl, stack) => {
    const embedUrl = stack.embedUrl;
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const made = await (await fetch(`${agents}/v1/widget-deployments`, { method: 'POST', headers: J, body: JSON.stringify({ name: 'Intranet desk', agentId: 'ag_fraud', origins: [HOST] }) })).json();
    if (!made.data) throw new Error(`setup: deployment: ${JSON.stringify(made).slice(0, 300)}`);
    const dep = made.data.id;
    const key = await (await fetch(`${agents}/v1/widget-deployments/${dep}/keys`, { method: 'POST', headers: J, body: JSON.stringify({ name: 'Intranet server' }) })).json();
    if (!key.data) throw new Error(`setup: mint key: ${JSON.stringify(key).slice(0, 300)}`);
    const tenant = key.data.secret.split('.')[1];
    const servers = [await listen(bankPage(embedUrl, dep, tenant, key.data.secret), HOST_PORT), await listen(otherPage(embedUrl, dep, tenant), OTHER_PORT)];

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const consoleErrors = [];
      page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text().slice(0, 300)));
      const threadPosts = [];
      const widgetCalls = [];
      page.on('response', (r) => r.url().includes('/v1/widget/') && widgetCalls.push(`${r.request().method()} ${new URL(r.url()).pathname.split('/').slice(4).join('/')} ${r.status()}`));
      page.on('request', (r) => r.method() === 'POST' && /\/v1\/widget\/[^/]+\/threads$/.test(r.url()) && threadPosts.push(r.url()));
      await page.goto(`${HOST}/`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.OpsChat && document.querySelector('[data-ops-chat]'), null, { timeout: 60_000 });
      await page.evaluate(() => OpsChat.open());
      const chatFrame = page.frameLocator('[data-ops-chat] iframe, iframe[title="Chat"]');
      const frame = async () => {
        for (let i = 0; i < 240; i++) {
          const f = page.frames().find((x) => x.url().startsWith(`${embedUrl}/embed/${dep}`));
          if (f) return f;
          await page.waitForTimeout(250);
        }
        throw new Error('the chat frame never loaded');
      };
      void chatFrame;
      const chat = await frame();

      // 1. The chat opens signed in, with the agent's greeting, and no thread exists until the first message.
      await step('1 the chat opens signed in and makes no thread until the first message', async () => {
        await chat.getByTestId('embed-welcome').waitFor({ timeout: 120_000 });
        const footer = await chat.getByTestId('embed-footer').innerText();
        const ready = await page.waitForFunction(() => window.events.some(([e]) => e === 'ready'), null, { timeout: 30_000 }).then(() => true, () => false);
        check('1 the chat opens signed in and makes no thread until the first message', ready && footer.includes('Tara Teller') && threadPosts.length === 0, { footer, threadPosts });
      });

      // 2. The first message makes the thread; the hold stops at the console's approval card, with no buttons.
      await step('2 a drafted hold shows the approval card waiting, with no buttons', async () => {
        const box = chat.getByRole('textbox', { name: 'Message' });
        await box.fill(HOLD);
        await chat.getByRole('button', { name: 'Send', exact: true }).click();
        const shown = await chat.getByTestId('approval-waiting-on').waitFor({ timeout: 120_000 }).then(() => true, () => false);
        if (!shown && process.env.UC119_DUMP) (await import('node:fs')).writeFileSync(process.env.UC119_DUMP, await chat.content());
        if (!shown) throw new Error(`no approval card; the chat reads: ${(await chat.locator('body').innerText()).slice(-600)}; console: ${consoleErrors.join(' | ').slice(0, 600)}; calls: ${widgetCalls.join(', ')}`);
        const buttons = await chat.getByRole('button', { name: /^(Approve|Reject)/ }).count();
        const attach = await chat.getByTestId('chat-attach').count();
        check('2 a drafted hold shows the approval card waiting, with no buttons', threadPosts.length === 1 && buttons === 0 && attach === 0, { threadPosts: threadPosts.length, buttons, attach });
      });

      // 3. An approver decides it in Human Tasks; the widget conversation shows the hold placed.
      await step('3 after Human Tasks approves, the widget conversation carries on', async () => {
        const tid = await chat.evaluate((d) => sessionStorage.getItem(`ops-chat:${d}:thread`), dep);
        const O = as(await tokenFor('m.okafor@northfieldbank.com'), 'team_ops');
        const up = await (await fetch(`${agents}/v1/auth/step-up`, { method: 'POST', headers: O, body: JSON.stringify({ password: PASSWORD }) })).json();
        const decided = await fetch(`${agents}/reviews/${tid}/decision`, { method: 'POST', headers: O, body: JSON.stringify({ decision: 'approved', stepUpToken: up.data?.token }) });
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => window.OpsChat && document.querySelector('[data-ops-chat]'), null, { timeout: 60_000 });
        await page.evaluate(() => OpsChat.open());
        const again = await frame();
        const placed = await again.getByText(/approved|placed|in place/i).first().waitFor({ timeout: 120_000 }).then(() => true, () => false);
        check('3 after Human Tasks approves, the widget conversation carries on', decided.status === 200 && placed, { decided: decided.status, body: decided.status === 200 ? '' : await decided.text() });
      });

      // 4. A frame from another origin posts a sign-out to every frame on the page; the chat ignores it.
      await step('4 a forged sign-out from another frame is ignored', async () => {
        const current = page.frames().find((x) => x.url().startsWith(`${embedUrl}/embed/${dep}`));
        await page.frames().find((x) => x.url().startsWith(OTHER)).evaluate(() => window.forge());
        await page.waitForTimeout(800);
        const stillIn = await current.getByRole('textbox', { name: 'Message' }).isVisible();
        check('4 a forged sign-out from another frame is ignored', stillIn && !(await page.evaluate(() => window.events.some(([e]) => e === 'signed-out'))));
      });

      // 5. The host page cannot read the transcript: the frame is another origin and the loader's root is closed.
      await step('5 the host page cannot read the transcript', async () => {
        const read = await page.evaluate(() => {
          const root = document.querySelector('[data-ops-chat]');
          let doc = null;
          try {
            doc = document.querySelector('iframe[title="Chat"]')?.contentDocument ?? null;
          } catch {
            doc = null;
          }
          return { shadow: root?.shadowRoot ?? null, doc: !!doc, text: document.body.innerText, events: JSON.stringify(window.events) };
        });
        check('5 the host page cannot read the transcript', read.shadow === null && !read.doc && !read.text.includes('W-1') && !read.events.includes('W-1'), { doc: read.doc, events: read.events.slice(0, 200) });
      });

      // 6. Signed out, the chat shows Sign in, which runs the page's own login.
      await step('6 signed out, Sign in runs the page login', async () => {
        const out = await (await browser.newContext()).newPage();
        out.on('pageerror', (e) => errors.push(`signed out: ${e.message}`));
        await out.goto(`${HOST}/?signedOut=1`, { waitUntil: 'domcontentloaded' });
        await out.waitForFunction(() => window.OpsChat && document.querySelector('[data-ops-chat]'), null, { timeout: 60_000 });
        await out.evaluate(() => OpsChat.open());
        let f;
        for (let i = 0; i < 240 && !f; i++) {
          f = out.frames().find((x) => x.url().startsWith(`${embedUrl}/embed/${dep}`));
          if (!f) await out.waitForTimeout(250);
        }
        await f.getByTestId('embed-signed-out').waitFor({ timeout: 120_000 });
        await f.getByRole('button', { name: 'Sign in' }).click();
        const ran = await out.waitForFunction(() => window.signIns === 1, null, { timeout: 15_000 }).then(() => true, () => false);
        check('6 signed out, Sign in runs the page login', ran);
      });

      // 7. Only listed pages may frame the chat: the page's CSP names the bank origin for it, and the console's own for
      // its Preview (c-232), and nobody for another.
      await step('7 the chat page allows framing only by the listed page', async () => {
        const url = `${embedUrl}/embed/${dep}?tenant=${tenant}`;
        const listed = (await fetch(url, { headers: { Referer: `${HOST}/` } })).headers.get('content-security-policy');
        const other = (await fetch(url, { headers: { Referer: `${OTHER}/` } })).headers.get('content-security-policy');
        const ancestors = `frame-ancestors ${HOST} ${new URL(consoleUrl).origin}`;
        check('7 the chat page allows framing only by the listed page', listed === ancestors && other === "frame-ancestors 'none'", { listed, other });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
      for (const s of servers) s.close();
    }
  },
  { platform: true, embed: true },
);

finish();
