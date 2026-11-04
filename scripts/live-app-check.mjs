#!/usr/bin/env node
// Checks a real GitHub app against a running stack, end to end, from an env file:
//   1. the client id and secret are accepted by GitHub (a token request with a made-up code must fail only on the code)
//   2. the team's app credential holds them (made, or its secret replaced, through the Apps API)
//   3. the team account signs in through that credential (a browser window; GitHub remembers the person afterwards)
//   4. the account's test call answers, and the read tool lists a repository's issues
//   5. a test run of the write tool never reaches GitHub
//
// Usage: node scripts/live-app-check.mjs [--env ~/.config/ops-ai/github.env] [--repo owner/name] [--team team_ops]
// The env file holds GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET (a GitHub App's client id and one of its client
// secrets). The secret is sent only to GitHub and to the stack's credential API, and never printed.
// Ports follow OPS_PORT_OFFSET as the stack's do (ISOLATED=1 stacks pass theirs), and the admin signs in with the
// stack's own .run/<stack>/dev-admin.env.
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const { chromium } = createRequire(join(ROOT, 'packages/usecase-runner/package.json'))('playwright');

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const envFile = arg('env', join(homedir(), '.config/ops-ai/github.env')).replace(/^~/, homedir());
const [owner, repo] = arg('repo', 'chanl-ai/ops-ai').split('/');
const team = arg('team', 'team_ops');
const offset = Number(process.env.OPS_PORT_OFFSET ?? 0);
const PLATFORM = `http://127.0.0.1:${8710 + offset}`;
const TOOLS = `http://127.0.0.1:${8720 + offset}`;
const APP = 'plugin:opsai.github';
const CREDENTIAL_NAME = 'GitHub · live check';

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
  console.error(`live-app-check: ${envFile} is missing; put GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in it`);
  process.exit(2);
}
const { GITHUB_CLIENT_ID: clientId, GITHUB_CLIENT_SECRET: clientSecret } = readEnv(envFile);
if (!clientId || !clientSecret) {
  console.error(`live-app-check: ${envFile} needs both GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET`);
  process.exit(2);
}

// 1. GitHub answers a made-up code with bad_verification_code when the client is right, and with
//    incorrect_client_credentials when the id or secret is wrong.
const probe = await fetch('https://github.com/login/oauth/access_token', {
  method: 'POST',
  headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ client_id: clientId, client_secret: clientSecret, code: 'live-check-not-a-code' }),
}).then((r) => r.json());
if (!step('GitHub accepts the client id and secret', probe.error === 'bad_verification_code', `GitHub said ${probe.error}`)) stop();

// The stack's admin.
const stackDir = existsSync(join(ROOT, '.run/isolated/dev-admin.env')) && offset ? '.run/isolated' : '.run';
const admin = readEnv(join(ROOT, stackDir, 'dev-admin.env'));
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
let credential = (listed.data ?? []).find((c) => c.type === 'own' && c.clientId === clientId);
if (!credential) {
  const made = await api('POST', '/v1/app-credentials', { app: APP, name: CREDENTIAL_NAME, clientId, clientSecret });
  credential = made.data;
  step('The team credential is made with the client id and secret', made.status === 201, made.error?.message);
} else {
  const set = await api('PUT', `/v1/app-credentials/${credential.id}/secret`, { clientSecret });
  step(`The team credential "${credential.name}" takes the secret`, set.status === 200, set.error?.message);
}
if (!credential) stop();

// The team turns GitHub on with that credential, at GitHub's real addresses, signed in as the team.
const turnedOn = await api('PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, {
  enabled: true,
  sandbox: false,
  credentialId: credential.id,
  settings: { api_url: 'https://api.github.com', web_url: 'https://github.com' },
});
if (!step('GitHub is on for the team with this credential', turnedOn.status === 200, turnedOn.error?.message)) stop();
const page = await api('GET', `/v1/apps/${encodeURIComponent(APP)}`);
const account = (page.data?.accounts ?? []).find((a) => a.default) ?? page.data?.accounts?.[0];
if (!step('The team has a GitHub account', Boolean(account), page.error?.message) || !account) stop();
const accountPath = `/v1/apps/${encodeURIComponent(APP)}/accounts/${account.id}`;
const detail = await api('GET', accountPath);
if (detail.data?.signIn !== 'team') await api('PATCH', accountPath, { revision: detail.data.revision, signIn: 'team', teamBackup: false });

// 3. The sign-in: GitHub's page in a browser that keeps its session in ~/.config/ops-ai/browser, so a person signs
//    in to GitHub there once. The return to Ops AI is caught here and finished through the API.
const started = await api('POST', `${accountPath}/sign-in`, {});
if (!step('A sign-in starts', Boolean(started.data?.authorizeUrl), started.error?.message)) stop();
// --handoff <dir>: another browser (a person's own, already signed in to GitHub) opens the address written to
// <dir>/authorize.txt and writes the address GitHub sent it back to into <dir>/return.txt.
const handoff = arg('handoff', '');
let back = null;
if (handoff) {
  const { mkdirSync, writeFileSync, rmSync } = await import('node:fs');
  mkdirSync(handoff, { recursive: true });
  rmSync(join(handoff, 'return.txt'), { force: true });
  writeFileSync(join(handoff, 'authorize.txt'), started.data.authorizeUrl);
  console.log(`      Open the address in ${handoff}/authorize.txt in a browser signed in to GitHub, then write the address it lands on to ${handoff}/return.txt. Waiting up to 10 minutes…`);
  for (let i = 0; i < 600 && !back; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (existsSync(join(handoff, 'return.txt'))) back = new URL(readFileSync(join(handoff, 'return.txt'), 'utf8').trim());
  }
} else {
  const context = await chromium.launchPersistentContext(join(homedir(), '.config/ops-ai/browser'), { headless: false });
  const tab = context.pages()[0] ?? (await context.newPage());
  const returned = new Promise((resolve) => {
    context.route('**/connections/sign-in/return**', async (route) => {
      resolve(new URL(route.request().url()));
      await route.fulfill({ contentType: 'text/html', body: '<p>Back in the live check; this window closes.</p>' });
    });
  });
  await tab.goto(started.data.authorizeUrl);
  console.log('      A browser window opened on GitHub. The first time, sign in to GitHub there and approve the app; it stays signed in for the next runs. Waiting up to 10 minutes…');
  await tab.bringToFront();
  back = await Promise.race([returned, new Promise((r) => setTimeout(() => r(null), 600_000))]);
  await context.close();
}
if (!step('GitHub sends the sign-in back', Boolean(back?.searchParams.get('code')), back ? back.searchParams.get('error') ?? '' : 'no answer in 10 minutes')) stop();
const done = await api('POST', `${accountPath}/sign-in/complete`, { state: back.searchParams.get('state'), code: back.searchParams.get('code') });
if (!step('Ops AI finishes the sign-in', done.status === 200, done.error?.message)) stop();

// 4. The account's test call and a real read.
const tested = await api('POST', `${accountPath}/test`, { account: 'team' });
step('The account test reaches GitHub', tested.data?.health?.status === 'ok', tested.data?.health?.message ?? tested.error?.message);
const read = await api('POST', '/v1/tool-modules/mod_plugin_github/operations/github_list_issues/run', {
  mode: 'real',
  environment: 'production',
  input: { owner, repo, state: 'all' },
});
const issues = read.data?.output?.issues;
step(`The read tool lists ${owner}/${repo}'s issues`, Array.isArray(issues), Array.isArray(issues) ? `${issues.length} issues` : JSON.stringify(read.data?.output ?? read.error).slice(0, 200));

// 5. A test run of the write tool answers from its mock and never posts.
const write = await api('POST', '/v1/tool-modules/mod_plugin_github/operations/github_add_comment/run', {
  mode: 'real',
  environment: 'test',
  input: { owner, repo, number: issues?.[0]?.number ?? 1, body: 'Live check: this comment must never be posted.' },
});
step('A test run of the write tool never reaches GitHub', write.data?.mocked === true || write.data?.wouldPause === true, JSON.stringify(write.data ?? write.error).slice(0, 200));
stop();
