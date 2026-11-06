#!/usr/bin/env node
// Checks a real app (GitHub or Salesforce) against a running stack, end to end, from an env file:
//   1. the provider accepts the client (GitHub: id and secret; Salesforce: the id, which is all it confirms unsigned)
//   2. the team's app credential holds them (made, or its secret replaced, through the Apps API)
//   3. the team account signs in through that credential (a browser that remembers the person, or a hand-off)
//   4. the account's test call answers, and a read tool returns real records
//   5. a test run of a write tool never reaches the provider
//
// Usage: node scripts/live-app-check.mjs [--app github|salesforce] [--env <file>] [--team team_ops]
//          [--repo owner/name] [--handoff <dir>] [--wait minutes]
// GitHub reads GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET from ~/.config/ops-ai/github.env; Salesforce reads SF_LOGIN
// (the org's sign-in address, ending /services/oauth2), SF_CLIENT_ID and SF_CLIENT_SECRET from
// ~/.config/ops-ai/salesforce.env. Secrets go only to the provider and the stack's credential API, never to output.
// Ports are the stack's (OPS_PLATFORM_PORT, OPS_TOOLS_PORT), and the admin signs in with the stack's own dev-admin.env.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const readEnv = (path) =>
  Object.fromEntries(
    readFileSync(path, 'utf8')
      .split('\n')
      .filter((l) => /^\s*[A-Z_]+=/.test(l))
      .map((l) => {
        const i = l.indexOf('=');
        return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')];
      }),
  );

const form = (fields) => ({
  method: 'POST',
  headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams(fields),
});

// What differs between apps: where the client lives, how the provider confirms it, the team's settings, and which
// read and write tools prove calls.
const PROFILES = {
  github: {
    title: 'GitHub',
    env: '~/.config/ops-ai/github.env',
    keys: ['GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET'],
    client: (e) => ({ id: e.GITHUB_CLIENT_ID, secret: e.GITHUB_CLIENT_SECRET }),
    // A made-up code fails on the code (bad_verification_code) only when the id and secret are right.
    probe: async ({ id, secret }) => {
      const said = await fetch('https://github.com/login/oauth/access_token', form({ client_id: id, client_secret: secret, code: 'live-check' })).then((r) => r.json());
      return { ok: said.error === 'bad_verification_code', said: `GitHub said ${said.error}`, what: 'GitHub accepts the client id and secret' };
    },
    settings: () => ({ api_url: 'https://api.github.com', web_url: 'https://github.com' }),
    module: 'mod_plugin_github',
    read: (repo) => ({ tool: 'github_list_issues', input: { owner: repo[0], repo: repo[1], state: 'all' }, rows: (o) => o?.issues, what: `lists ${repo.join('/')}'s issues` }),
    write: (repo, rows) => ({ tool: 'github_add_comment', input: { owner: repo[0], repo: repo[1], number: rows?.[0]?.number ?? 1, body: 'Live check: this comment must never be posted.' } }),
  },
  salesforce: {
    title: 'Salesforce',
    env: '~/.config/ops-ai/salesforce.env',
    keys: ['SF_LOGIN', 'SF_CLIENT_ID', 'SF_CLIENT_SECRET'],
    client: (e) => ({ id: e.SF_CLIENT_ID, secret: e.SF_CLIENT_SECRET, login: e.SF_LOGIN.replace(/\/$/, '') }),
    // Salesforce answers an unknown client id with invalid_client_id and gives the same vague answer for a right or a
    // wrong secret before a sign-in, so only the id is confirmed here; the sign-in confirms the secret.
    probe: async ({ id, login }) => {
      const said = await fetch(`${new URL(login).origin}/services/oauth2/token`, form({ grant_type: 'authorization_code', code: 'live-check', client_id: id, client_secret: 'live-check' })).then((r) => r.json());
      return { ok: said.error !== 'invalid_client_id', said: `Salesforce said ${said.error}`, what: 'Salesforce knows the client id' };
    },
    settings: ({ login }) => ({ login_url: login.endsWith('/services/oauth2') ? login : `${login}/services/oauth2` }),
    module: 'mod_plugin_salesforce',
    read: () => ({ tool: 'salesforce_query', input: { q: 'SELECT Id, Name FROM Account ORDER BY CreatedDate DESC LIMIT 5' }, rows: (o) => o?.records ?? (Array.isArray(o) ? o : undefined), what: 'reads accounts' }),
    write: () => ({ tool: 'salesforce_create_record', input: { object: 'Account', fields: { Name: 'Live check: this account must never be created' } } }),
  },
};

const appName = arg('app', 'github');
const P = PROFILES[appName];
if (!P) {
  console.error(`live-app-check: --app is one of ${Object.keys(PROFILES).join(', ')}`);
  process.exit(2);
}
const APP = `plugin:opsai.${appName}`;
const envFile = arg('env', P.env).replace(/^~/, homedir());
const repo = arg('repo', 'chanl-ai/ops-ai').split('/');
const team = arg('team', 'team_ops');
const PLATFORM = `http://127.0.0.1:${process.env.OPS_PLATFORM_PORT ?? 8710}`;
const TOOLS = `http://127.0.0.1:${process.env.OPS_TOOLS_PORT ?? 8720}`;

const results = [];
const step = (name, ok, said) => {
  results.push({ name, ok, said });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${said ? ` — ${said}` : ''}`);
  return ok;
};
const stop = () => {
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed} of ${results.length} passed`);
  process.exit(failed ? 1 : 0);
};

if (!existsSync(envFile)) {
  console.error(`live-app-check: ${envFile} is missing; it needs ${P.keys.join(', ')}`);
  process.exit(2);
}
const env = readEnv(envFile);
const missing = P.keys.filter((k) => !env[k]);
if (missing.length) {
  console.error(`live-app-check: ${envFile} needs ${missing.join(', ')}`);
  process.exit(2);
}
const client = P.client(env);

// 1. The provider confirms the client before anything else runs.
const probe = await P.probe(client);
if (!step(probe.what, probe.ok, probe.said)) stop();

// The stack's admin.
const admin = readEnv(join(process.env.OPS_RUN_DIR ?? join(ROOT, '.run'), 'dev-admin.env'));
const signedIn = await fetch(`${PLATFORM}/v1/auth/sign-in`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: admin.OPS_BOOTSTRAP_ADMIN_EMAIL, password: admin.OPS_BOOTSTRAP_ADMIN_PASSWORD }),
}).then((r) => r.json());
const token = signedIn?.data?.token;
if (!step('The stack signs its admin in', Boolean(token), token ? '' : JSON.stringify(signedIn?.error ?? signedIn))) stop();
const H = { Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' };
const api = async (method, path, body) => {
  const r = await fetch(`${TOOLS}${path}`, { method, headers: H, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  return { status: r.status, data: j.data, error: j.error };
};

// 2. The team's credential for this client: made once, its secret replaced on every run.
const listed = await api('GET', `/v1/app-credentials?app=${encodeURIComponent(APP)}`);
let credential = (listed.data ?? []).find((c) => c.type === 'own' && c.clientId === client.id);
if (!credential) {
  const made = await api('POST', '/v1/app-credentials', { app: APP, name: `${P.title} · live check`, clientId: client.id, clientSecret: client.secret });
  credential = made.data;
  step('The team credential is made with the client id and secret', made.status === 201, made.error?.message);
} else {
  const set = await api('PUT', `/v1/app-credentials/${credential.id}/secret`, { clientSecret: client.secret });
  step(`The team credential "${credential.name}" takes the secret`, set.status === 200, set.error?.message);
}
if (!credential) stop();

// The team turns the app on with that credential and its real addresses, signed in as the team.
const turnedOn = await api('PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, { enabled: true, sandbox: false, credentialId: credential.id, settings: P.settings(client) });
if (!step(`${P.title} is on for the team with this credential`, turnedOn.status === 200, turnedOn.error?.message)) stop();
const page = await api('GET', `/v1/apps/${encodeURIComponent(APP)}`);
const accounts = (page.data?.authConfigs ?? []).flatMap((c) => c.accounts);
const account = accounts.find((a) => a.default) ?? accounts[0];
if (!step(`The team has a ${P.title} account`, Boolean(account), page.error?.message) || !account) stop();
const accountPath = `/v1/apps/${encodeURIComponent(APP)}/accounts/${account.id}`;
const detail = await api('GET', accountPath);
if (detail.data?.signIn !== 'team') await api('PATCH', accountPath, { revision: detail.data.revision, signIn: 'team', teamBackup: false });

// 3. The sign-in. --handoff <dir>: a person's own browser (already signed in to the provider) opens the address in
//    <dir>/authorize.txt and writes the address it is sent back to into <dir>/return.txt. Otherwise a browser that
//    keeps its session in ~/.config/ops-ai/browser opens, so a person signs in to the provider there once.
const started = await api('POST', `${accountPath}/sign-in`, {});
if (!step('A sign-in starts', Boolean(started.data?.authorizeUrl), started.error?.message)) stop();
const handoff = arg('handoff', '');
const waitMinutes = Number(arg('wait', 10));
let back = null;
if (handoff) {
  mkdirSync(handoff, { recursive: true });
  rmSync(join(handoff, 'return.txt'), { force: true });
  writeFileSync(join(handoff, 'authorize.txt'), started.data.authorizeUrl);
  console.log(`      Open ${handoff}/authorize.txt's address in a browser signed in to ${P.title}; write the address it lands on to ${handoff}/return.txt. Waiting up to ${waitMinutes} minutes…`);
  for (let i = 0; i < waitMinutes * 60 && !back; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (existsSync(join(handoff, 'return.txt'))) back = new URL(readFileSync(join(handoff, 'return.txt'), 'utf8').trim());
  }
} else {
  const { chromium } = createRequire(join(ROOT, 'packages/usecase-runner/package.json'))('playwright');
  const context = await chromium.launchPersistentContext(join(homedir(), '.config/ops-ai/browser'), { headless: false });
  const tab = context.pages()[0] ?? (await context.newPage());
  const returned = new Promise((resolve) => {
    context.route('**/connections/sign-in/return**', async (route) => {
      resolve(new URL(route.request().url()));
      await route.fulfill({ contentType: 'text/html', body: '<p>Back in the live check; this window closes.</p>' });
    });
  });
  await tab.goto(started.data.authorizeUrl);
  console.log(`      A browser window opened on ${P.title}. The first time, sign in there and allow access; it stays signed in for the next runs. Waiting up to ${waitMinutes} minutes…`);
  await tab.bringToFront();
  back = await Promise.race([returned, new Promise((r) => setTimeout(() => r(null), waitMinutes * 60_000))]);
  await context.close();
}
if (!step(`${P.title} sends the sign-in back`, Boolean(back?.searchParams.get('code')), back ? [back.searchParams.get('error'), back.searchParams.get('error_description')].filter(Boolean).join(': ') : `no answer in ${waitMinutes} minutes`)) stop();
const done = await api('POST', '/v1/sign-ins/complete', { state: back.searchParams.get('state'), code: back.searchParams.get('code') });
if (!step('Ops AI finishes the sign-in', done.status === 200, done.error?.message)) stop();

// 4. The account's test call and a real read.
const tested = await api('POST', `${accountPath}/test`, { account: 'team' });
step(`The account test reaches ${P.title}`, tested.data?.health?.status === 'ok', tested.data?.health?.message ?? tested.error?.message);
const r = P.read(repo);
const read = await api('POST', `/v1/tool-modules/${P.module}/operations/${r.tool}/run`, { mode: 'real', environment: 'production', input: r.input });
const rows = r.rows(read.data?.output);
step(`The read tool ${r.what}`, Array.isArray(rows), Array.isArray(rows) ? `${rows.length} rows` : JSON.stringify(read.data?.output ?? read.error).slice(0, 240));

// 5. A test run of a write tool answers from its mock or waits for a person, and never reaches the provider.
const w = P.write(repo, rows);
const write = await api('POST', `/v1/tool-modules/${P.module}/operations/${w.tool}/run`, { mode: 'real', environment: 'test', input: w.input });
step(`A test run of the write tool never reaches ${P.title}`, write.data?.mocked === true || write.data?.wouldPause === true, JSON.stringify(write.data ?? write.error).slice(0, 200));
stop();
