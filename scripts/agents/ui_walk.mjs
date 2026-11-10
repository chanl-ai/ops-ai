#!/usr/bin/env node
// Walks routes of the running console in a headless browser as each role at each width and writes the evidence a
// browser test or a UX review starts from: a screenshot per route, role and width, and a report of page errors,
// console errors, failed requests, sideways overflow, error text on the page, and the loading, error and empty
// states when asked. The profile's "Console" section owns the origin, the sign-in page, the roles and the widths;
// flags override a row. Read-only on the stack: it signs in and opens pages, nothing else.
//
//   node scripts/agents/ui_walk.mjs --routes /knowledge /tools [--as admin,member] [--widths 1440,390]
//        [--states] [--origin http://localhost:3016] [--out .logs/agents/ui-walk]
//   node scripts/agents/ui_walk.mjs --self-test     a local page with a known error, a failed request and overflow
//
// Output: <out>/<route>-<role>-<width>[-<state>].png and <out>/report.md (plus report.json); one line per page on
// stdout: OK or FAIL with what was found. Exit 1 when any page failed, 2 on a usage error.
import { createServer } from 'node:http';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { loadProfile, plain } from './project_profile.mjs';

const args = process.argv.slice(2);
const flag = (name) => {
  const i = args.indexOf(`--${name}`);
  return i < 0 ? undefined : args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : true;
};
/** Every value after `--name` up to the next flag, split on commas and spaces. */
const list = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  if (i < 0) return fallback;
  const values = [];
  for (let j = i + 1; j < args.length && !args[j].startsWith('--'); j++) values.push(...args[j].split(/[,\s]+/));
  return values.filter(Boolean);
};

/** Facts the walk needs, read from the profile with the flags on top. */
function settings(profile) {
  const console_ = profile.table('Console', 'Setting');
  const value = (key) => plain(console_.find((r) => plain(r.Setting).toLowerCase() === key)?.Value ?? '');
  const roles = profile.table('Console', 'Role for walks').map((r) => ({ role: plain(r['Role for walks']), email: plain(r.Email), password: plain(r.Password) }));
  const signIn = value('sign-in page');
  const states = value('loading, error and empty states');
  return {
    origin: flag('origin') ?? process.env.OPS_CONSOLE_ORIGIN ?? value('console origin').split(/\s/)[0],
    loginPath: (signIn.match(/^(\/\S*)/) ?? [, '/login'])[1],
    emailLabel: (signIn.match(/labelled (\w+) and (\w+)/) ?? [, 'Email', 'Password'])[1],
    passwordLabel: (signIn.match(/labelled (\w+) and (\w+)/) ?? [, 'Email', 'Password'])[2],
    signInButton: (signIn.match(/starts with ([^;.]+)/) ?? [, 'Sign in'])[1].trim(),
    widths: list('widths', value('widths').split(/\D+/).filter(Boolean)).map(Number),
    states: [...states.matchAll(/\?mock=(\w+)/g)].map((m) => m[1]).filter((s) => s !== 'off'),
    roles: list('as', ['admin', 'member']).map((name) => {
      const r = roles.find((x) => x.role === name);
      if (!r) throw new Error(`no role "${name}" in the profile's "Role for walks" table (${roles.map((x) => x.role).join(', ')})`);
      return r;
    }),
  };
}

/** Opens one route on `page` and returns what a reviewer needs to know about it. */
export async function inspect(page, url, { settleMs = 800 } = {}) {
  const errors = [];
  const consoleErrors = [];
  const failed = [];
  const onErr = (e) => errors.push(e.message.slice(0, 160));
  const onConsole = (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160));
  };
  const seen = []; // every response, so a 401 that the console renews and retries is not a finding
  const onResp = (r) => {
    const path = new URL(r.url()).pathname;
    seen.push({ path, status: r.status() });
    if (r.status() >= 400) failed.push(`${r.status()} ${path}`);
  };
  // A navigation the page itself cancels (a redirect after sign-in) is not a failed request.
  const onReqFailed = (r) => {
    const why = r.failure()?.errorText ?? '';
    if (why !== 'net::ERR_ABORTED') failed.push(`failed ${new URL(r.url()).pathname} ${why}`.trim());
  };
  page.on('pageerror', onErr);
  page.on('console', onConsole);
  page.on('response', onResp);
  page.on('requestfailed', onReqFailed);
  let status = 0;
  try {
    const res = await page.goto(url, { waitUntil: 'load', timeout: 60_000 });
    status = res?.status() ?? 0;
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(settleMs);
  } catch (e) {
    errors.push(`goto: ${String(e.message).slice(0, 120)}`);
  }
  const facts = await page
    .evaluate(() => {
      const root = document.scrollingElement ?? document.documentElement;
      const overflowing = [...document.querySelectorAll('body *')]
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > innerWidth + 1 && getComputedStyle(el).position !== 'fixed';
        })
        .slice(0, 5)
        .map((el) => `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.split(/\s+/).slice(0, 2).join('.') : ''}`);
      const text = (document.querySelector('main') ?? document.body).innerText.replace(/\s+/g, ' ');
      const errorText = text.match(/(something went wrong|failed to load|could not load|try again|unexpected error|not found)/i)?.[0] ?? '';
      const unnamed = [...document.querySelectorAll('button, a[href], input, select, textarea, [role=button]')].filter((el) => {
        const name = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title') || (el.labels && el.labels.length) || el.textContent.trim() || el.getAttribute('placeholder');
        return !name && el.getClientRects().length;
      }).length;
      return { scrollsSideways: root.scrollWidth > innerWidth + 1, overflowing, errorText, headings: document.querySelectorAll('h1').length, unnamedControls: unnamed, title: document.title };
    })
    .catch((e) => ({ scrollsSideways: false, overflowing: [], errorText: `evaluate: ${e.message}`, headings: 0, unnamedControls: 0, title: '' }));
  page.off('pageerror', onErr);
  page.off('console', onConsole);
  page.off('response', onResp);
  page.off('requestfailed', onReqFailed);
  const renewed = (entry) => {
    const m = /^401 (.+)$/.exec(entry);
    return m && seen.some((s) => s.path === m[1] && s.status < 400);
  };
  const real = [...new Set(failed)].filter((f) => !renewed(f));
  const consoleReal = consoleErrors.filter((e) => !(/status of 401/.test(e) && real.every((f) => !f.startsWith('401'))));
  const ok = status < 400 && !errors.length && !consoleReal.length && !real.length && !facts.scrollsSideways && !facts.errorText;
  return { url, status, ok, errors, consoleErrors: consoleReal, failed: real, ...facts };
}

async function signIn(page, s, role) {
  await page.goto(`${s.origin}${s.loginPath}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.getByLabel(s.emailLabel).fill(role.email);
  await page.getByLabel(s.passwordLabel).fill(role.password);
  await page.getByRole('button', { name: new RegExp(`^${s.signInButton}`) }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith(s.loginPath), { timeout: 60_000 });
}

function line(r, label) {
  const why = [
    ...(r.status >= 400 ? [`http ${r.status}`] : []),
    ...r.errors.map((e) => `page error: ${e}`),
    ...r.consoleErrors.map((e) => `console: ${e}`),
    ...(r.failed.length ? [`requests: ${r.failed.join(', ')}`] : []),
    ...(r.scrollsSideways ? [`scrolls sideways: ${r.overflowing.join(', ')}`] : []),
    ...(r.errorText ? [`text: ${r.errorText}`] : []),
  ];
  return `${r.ok ? 'OK  ' : 'FAIL'} ${label}${why.length ? ' | ' + why.join(' | ') : ''}`;
}

async function walk() {
  const routes = list('routes', []);
  if (!routes.length) {
    console.error('ui_walk: name the routes, e.g. --routes /knowledge /tools');
    return 2;
  }
  const profile = loadProfile(flag('profile'));
  const s = settings(profile);
  const out = flag('out') ?? join(profile.root, '.logs', 'agents', 'ui-walk');
  mkdirSync(out, { recursive: true });
  const { chromium } = await import('@ops-ai/usecase-runner/harness');
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const role of s.roles) {
      for (const width of s.widths) {
        const ctx = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce', deviceScaleFactor: 1 });
        const page = await ctx.newPage();
        try {
          await signIn(page, s, role);
        } catch (e) {
          const r = { url: `${s.origin}${s.loginPath}`, status: 0, ok: false, errors: [`sign in as ${role.role}: ${String(e.message).slice(0, 120)}`], consoleErrors: [], failed: [], scrollsSideways: false, overflowing: [], errorText: '', role: role.role, width, route: s.loginPath, state: '' };
          results.push(r);
          console.log(line(r, `${s.loginPath} ${role.role} ${width}`));
          await ctx.close();
          continue;
        }
        for (const route of routes) {
          const variants = [''].concat(flag('states') ? s.states : []);
          for (const state of variants) {
            const join_ = route.includes('?') ? '&' : '?';
            const url = `${s.origin}${route}${state ? `${join_}mock=${state}` : ''}`;
            const r = await inspect(page, url, { settleMs: state === 'slow' ? 300 : 800 });
            const name = `${route.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-') || 'home'}-${role.role.replace(/\s+/g, '-')}-${width}${state ? `-${state}` : ''}`;
            await page.screenshot({ path: join(out, `${name}.png`), fullPage: true }).catch(() => {});
            Object.assign(r, { role: role.role, width, route, state, screenshot: `${name}.png` });
            results.push(r);
            console.log(line(r, `${route} ${role.role} ${width}${state ? ` ?mock=${state}` : ''}`));
          }
        }
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  const md = [
    `# UI walk: ${routes.join(' ')}`,
    '',
    `Origin ${s.origin}; roles ${s.roles.map((r) => r.role).join(', ')}; widths ${s.widths.join(', ')}${flag('states') ? `; states ${s.states.join(', ')}` : ''}.`,
    `${results.length} pages, ${failed.length} with findings.`,
    '',
    '| Route | Role | Width | State | Result | Screenshot |',
    '|---|---|---|---|---|---|',
    ...results.map((r) => `| ${r.route} | ${r.role} | ${r.width} | ${r.state || '-'} | ${line(r, '').replace(/^(OK|FAIL)\s*\|?\s*/, '$1 ')} | ${r.screenshot ?? ''} |`),
    '',
  ].join('\n');
  writeFileSync(join(out, 'report.md'), md);
  writeFileSync(join(out, 'report.json'), JSON.stringify(results, null, 1));
  console.log(`report: ${join(out, 'report.md')}`);
  return failed.length ? 1 : 0;
}

/** A local page with a thrown error, a request that 404s and an element wider than the viewport; the walk must name all three. */
async function selfTest() {
  const html = `<!doctype html><html><head><title>probe</title></head><body><main><h1>Probe</h1>
  <div id="wide" style="width:3000px;height:10px;background:#ddd"></div>
  <button aria-label="Close">x</button><button></button>
  <script>fetch('/missing');setTimeout(()=>{throw new Error('probe error')},10);</script></main></body></html>`;
  const server = createServer((req, res) => {
    if (req.url === '/missing') {
      res.writeHead(404);
      res.end('no');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(req.url === '/clean' ? '<!doctype html><title>clean</title><main><h1>Clean</h1><button>Save</button></main>' : html);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const { chromium } = await import('@ops-ai/usecase-runner/harness');
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 800 } })).newPage();
  const bad = await inspect(page, `${origin}/`, { settleMs: 300 });
  const good = await inspect(page, `${origin}/clean`, { settleMs: 100 });
  await browser.close();
  server.close();
  const cases = [
    ['a thrown error on the page is reported', bad.errors.some((e) => e.includes('probe error'))],
    ['a request that fails is reported with its status and path', bad.failed.includes('404 /missing')],
    ['an element wider than the viewport is reported as sideways scroll', bad.scrollsSideways && bad.overflowing.some((o) => o.includes('#wide'))],
    ['a control with no accessible name is counted', bad.unnamedControls === 1],
    ['a clean page is OK with nothing listed', good.ok && !good.errors.length && !good.failed.length && !good.scrollsSideways],
  ];
  for (const [name, ok] of cases) console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  return cases.every(([, ok]) => ok) ? 0 : 1;
}

if (args.includes('--help') || args.includes('-h')) {
  console.log('usage: node scripts/agents/ui_walk.mjs --routes /a /b [--as admin,member] [--widths 1440,390] [--states] [--origin URL] [--out DIR] | --self-test');
  process.exit(0);
}
process.exit(args.includes('--self-test') ? await selfTest() : await walk());
