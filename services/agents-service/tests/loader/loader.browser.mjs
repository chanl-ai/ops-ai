// The embedded chat loader's rules (c-131 T006), run in a real browser with the host page, the embed app and a hostile
// frame on three origins. By failure mode: a message from another window or origin acting on the chat, the iframe's
// ready going unanswered once a session exists, a session not refreshed before it ends or after a 401, a refresh loop
// on a session that keeps ending, message text reaching the host page, and an unlisted page drawing the chat.
// Run: node --test services/agents-service/tests/loader/loader.browser.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { after, before, test } from 'node:test';

import { chromium } from '@ops-ai/usecase-runner/harness';

const LOADER = readFileSync(new URL('../../src/ops_agents/static/ops-chat-loader.js', import.meta.url), 'utf8');

function serve(handler) {
  return new Promise((resolve) => {
    const server = createServer(handler);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}
const html = (res, body) => (res.writeHead(200, { 'Content-Type': 'text/html' }), res.end(body));

let browser;
const servers = [];
let HOST, EMBED, EVIL, UNLISTED;

const hostPage = (embed, evil) => `<!doctype html><body>
<script>
  const q = new URLSearchParams(location.search);
  window.log = []; window.sessions = 0; window.signIns = 0;
  addEventListener('ops-chat:load', () => {
    for (const e of ['ready', 'open', 'close', 'message', 'signed-out', 'error']) OpsChat.on(e, (p) => log.push([e, p ?? null]));
    OpsChat.init({
      deployment: 'wd_1',
      tenant: 'acme',
      getSession: async () => (++sessions, q.get('mode') === 'out' ? null : { session: 's' + sessions, expiresIn: Number(q.get('ttl') || 900) }),
      onSignIn: () => signIns++,
    });
  });
</script>
<script src="${embed}/embed/v1.js" async></script>
<iframe id="evil" src="${evil}/evil.html"></iframe>
</body>`;

// The embed app's page, reduced to the protocol: ready every 100 ms until identified, and a record of what arrived.
const framePage = (parentOrigin) => `<!doctype html><script>
  window.got = []; let identified = false;
  addEventListener('message', (e) => {
    if (e.source !== parent) return;
    got.push({ origin: e.origin, data: e.data });
    if (e.data.type === 'ops-chat:identify') {
      identified = !!e.data.session;
      if (identified) parent.postMessage({ type: 'ops-chat:identified' }, ${JSON.stringify(parentOrigin)});
    }
  });
  setInterval(() => identified || parent.postMessage({ type: 'ops-chat:ready' }, ${JSON.stringify(parentOrigin)}), 100);
  window.say = (m) => parent.postMessage(m, ${JSON.stringify(parentOrigin)});
</script>`;

before(async () => {
  const host = await serve((req, res) => html(res, hostPage(EMBED, EVIL)));
  const unlisted = await serve((req, res) => html(res, hostPage(EMBED, EVIL)));
  const evil = await serve((req, res) =>
    html(res, `<!doctype html><script>window.forge = () => { for (const m of [
      { type: 'ops-chat:message', role: 'assistant', at: 'x', text: 'forged' },
      { type: 'ops-chat:sign-in' }, { type: 'ops-chat:identified' }, { type: 'ops-chat:closed' }, { type: 'ops-chat:session-ended' },
    ]) parent.postMessage(m, '*'); };</script>`),
  );
  const embed = await serve((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/embed/v1.js') return res.writeHead(200, { 'Content-Type': 'text/javascript' }), res.end(LOADER);
    if (url.pathname === '/v1/widget/wd_1/config') {
      // As agents-service answers it: the listed page origin gets the CORS header, any other page does not.
      if (req.headers.origin === HOST) {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': HOST });
        return res.end(JSON.stringify({ success: true, data: { agentName: 'Helper', allowedOrigins: [HOST], paused: false } }));
      }
      return res.writeHead(403, { 'Content-Type': 'application/json' }), res.end('{"success":false}');
    }
    if (url.pathname === '/embed/wd_1') return html(res, framePage(HOST));
    res.writeHead(404).end();
  });
  servers.push(host, unlisted, evil, embed);
  // Four origins: two hosts by port, the embed app on localhost, so no two share an origin.
  HOST = `http://127.0.0.1:${host.address().port}`;
  UNLISTED = `http://127.0.0.1:${unlisted.address().port}`;
  EVIL = `http://127.0.0.1:${evil.address().port}`;
  EMBED = `http://localhost:${embed.address().port}`;
  browser = await chromium.launch();
});

after(async () => {
  await browser?.close();
  for (const s of servers) s.close();
});

async function opened(query = '', origin = HOST) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${origin}/${query}`);
  await page.waitForFunction(() => window.OpsChat && document.querySelector('[data-ops-chat]'), null, { timeout: 10_000 });
  await page.evaluate(() => OpsChat.open());
  const frame = async () => {
    for (let i = 0; i < 100; i++) {
      const f = page.frames().find((x) => x.url().startsWith(`${EMBED}/embed/wd_1`));
      if (f) return f;
      await page.waitForTimeout(50);
    }
    throw new Error('the chat frame never loaded');
  };
  return { page, frame: await frame(), errors };
}
const logOf = (page) => page.evaluate(() => window.log);
const until = (page, fn, arg) => page.waitForFunction(fn, arg, { timeout: 10_000 });

test('the iframe ready is answered with the session, once, to the embed origin only', async () => {
  const { page, frame, errors } = await opened();
  await until(page, () => window.log.some(([e]) => e === 'ready'));
  await page.waitForTimeout(400);
  const got = await frame.evaluate(() => window.got);
  const identifies = got.filter((m) => m.data.type === 'ops-chat:identify');
  assert.equal(await page.evaluate(() => window.sessions), 1, 'getSession asked once for repeated readies');
  assert.equal(identifies[0].data.session, 's1');
  assert.ok(got.every((m) => m.origin === HOST), 'every message to the frame comes from the host page');
  assert.equal((await logOf(page)).filter(([e]) => e === 'ready').length, 1);
  assert.equal(await page.evaluate(() => document.querySelector('[data-ops-chat]').shadowRoot), null, 'the launcher root is closed');
  assert.deepEqual(errors, []);
  await page.close();
});

test('messages from another frame or the page itself do nothing', async () => {
  const { page } = await opened();
  await until(page, () => window.log.some(([e]) => e === 'ready'));
  const evil = page.frames().find((f) => f.url().startsWith(EVIL));
  await evil.evaluate(() => window.forge());
  await page.evaluate(() => window.postMessage({ type: 'ops-chat:sign-in' }, '*'));
  await page.waitForTimeout(400);
  const log = await logOf(page);
  assert.equal(await page.evaluate(() => window.signIns), 0, 'a forged sign-in ran the page login');
  assert.ok(!log.some(([e]) => e === 'message' || e === 'close'), JSON.stringify(log));
  assert.equal(await page.evaluate(() => window.sessions), 1, 'a forged session-ended asked for a session');
  await page.close();
});

test('host events carry the role and time of a message, never its text', async () => {
  const { page, frame } = await opened();
  await until(page, () => window.log.some(([e]) => e === 'ready'));
  await frame.evaluate(() => window.say({ type: 'ops-chat:message', role: 'assistant', at: '2026-10-17T10:00:00Z', text: 'Balance 1,520.33' }));
  await until(page, () => window.log.some(([e]) => e === 'message'));
  const [, payload] = (await logOf(page)).find(([e]) => e === 'message');
  assert.deepEqual(payload, { role: 'assistant', at: '2026-10-17T10:00:00Z' });
  assert.ok(!JSON.stringify(await logOf(page)).includes('1,520.33'));
  await page.close();
});

test('a session is refreshed before it ends', async () => {
  const { page, frame } = await opened('?ttl=2');
  await until(page, () => window.sessions >= 2);
  await frame.waitForFunction(() => window.got.some((m) => m.data.type === 'ops-chat:identify' && m.data.session === 's2'), null, { timeout: 5_000 });
  await page.close();
});

test('an ended session is replaced once, and one that keeps ending signs the chat out', async () => {
  const { page, frame } = await opened();
  await until(page, () => window.log.some(([e]) => e === 'ready'));
  await frame.evaluate(() => window.say({ type: 'ops-chat:session-ended' }));
  await frame.waitForFunction(() => window.got.some((m) => m.data.type === 'ops-chat:identify' && m.data.session === 's2'), null, { timeout: 5_000 });
  await frame.evaluate(() => window.say({ type: 'ops-chat:session-ended' }));
  await until(page, () => window.log.some(([e]) => e === 'signed-out'));
  const last = (await frame.evaluate(() => window.got)).filter((m) => m.data.type === 'ops-chat:identify').at(-1);
  assert.equal(last.data.session, null);
  assert.equal(await page.evaluate(() => window.sessions), 2, 'a second end in a row did not ask again');
  await page.close();
});

test('with no session the chat is signed out and its Sign in runs the page login', async () => {
  const { page, frame } = await opened('?mode=out');
  await until(page, () => window.log.some(([e]) => e === 'signed-out'));
  const first = await frame.evaluate(() => window.got.find((m) => m.data.type === 'ops-chat:identify'));
  assert.deepEqual([first.data.session, first.data.signIn], [null, true]);
  await frame.evaluate(() => window.say({ type: 'ops-chat:sign-in' }));
  await until(page, () => window.signIns === 1);
  await page.close();
});

test('a page whose origin the deployment does not list draws nothing', async () => {
  const page = await browser.newPage();
  await page.goto(`${UNLISTED}/`);
  await until(page, () => window.log.some(([e]) => e === 'error'));
  assert.deepEqual((await logOf(page)).find(([e]) => e === 'error')[1], { code: 'origin_not_allowed' });
  await page.evaluate(() => OpsChat.open());
  assert.equal(await page.evaluate(() => !!document.querySelector('[data-ops-chat]')), false);
  assert.ok(!page.frames().some((f) => f.url().startsWith(EMBED)), 'the chat frame loaded on an unlisted page');
  await page.close();
});
