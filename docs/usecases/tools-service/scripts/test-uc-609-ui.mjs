// uc-609 A team reviews a plugin update before its tools change, ui layer: docs/usecases/tools-service/plugin-updates.md,
// story S5 (steps 9-11). The demo stack with plugins and the plugin_updates flag on, the fields desk installed at 0.2.0
// (services/tools-service/tests/plugin_versions/fields_desk), and the fake system (docs/usecases/lib/fake_multi_auth.py).
// The stack cannot restart tools-service mid-walk, so after Priya turns the desk on, her team's binding is set to the
// version 0.1.0 declares (version, digest, declarations from the 0.1.0 manifest), the stored state the api layer shows
// an upgrade leaving behind. Priya opens the app's page, sees Update available, reviews the tools and who uses them, and
// takes the update; the notice goes. The agent holds post_message, a tool both versions have, since the account's
// tool row was written by 0.2.0 before the binding was set, and so holds no row for 0.1.0's transfer. Screenshots go to evidenceDir('609', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('609', 'uc');
const ID = 'test.fields';
const V1 = join(ROOT, 'services/tools-service/tests/plugin_fields/fields_desk/plugin.yaml');
const V2 = join(ROOT, 'services/tools-service/tests/plugin_versions/fields_desk');
const DB = process.env.OPS_USECASE_DB ?? 'ops_usecase';
process.env.OPS_PLUGINS = 'true';
process.env.OPS_PLUGIN_PATHS = JSON.stringify([V2]);
process.env.OPS_FLAGS = JSON.stringify(['plugin_updates']);

/** 0.1.0's declarations and digest, from the SDK that tools-service records them with. */
function declared() {
  const code = `import json,sys; from ops_plugin_sdk.manifest import read; from ops_plugin_sdk.versions import declarations, digest
d = declarations(read(__import__('pathlib').Path(sys.argv[1]))); print(json.dumps({"declarations": d, "digest": digest(d)}))`;
  return JSON.parse(execFileSync('uv', ['run', '--quiet', 'python', '-c', code, V1], { cwd: ROOT, encoding: 'utf8' }));
}

async function startFake() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_multi_auth.py')], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
  });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`fake system exited with ${code}`)));
  });
  return { child, info: JSON.parse(line) };
}

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const call = async (base, method, path, headers, body) => {
  const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // Not JSON: the text is kept for the failure message.
  }
  return { status: r.status, data: json?.data, text: text.slice(0, 400) };
};

async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
  }
}

const fake = await startFake();
try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');

      // Set-up through the API, as the api layer's step 1 does; then the team's version as 0.1.0 left it.
      for (const host of fake.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-609' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: fake.info.range, note: 'uc-609' });
      const on = await call(tools, 'PUT', `/v1/apps/plugin:${ID}/team`, priya, { enabled: true, credentials: { token: fake.info.secrets.token } });
      const old = declared();
      const sql = `UPDATE plugin_bindings SET version = '0.1.0', digest = '${old.digest}', declarations = '${JSON.stringify(old.declarations).replaceAll("'", "''")}' WHERE team_id = 'team_ops' AND plugin_id = '${ID}'`;
      execFileSync('psql', [`postgresql://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`, '-c', sql], { encoding: 'utf8' });
      // A new app hands agents its read tools only; the team's admin adds the writes, as from the app's Tools tab.
      await call(tools, 'POST', `/v1/apps/plugin:${ID}/tools`, priya, { tools: ['fields_post_message'] });
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Message desk', role: 'Posts updates to the desk' })).data ?? {};
      let granted = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['fields_post_message'] });
      for (let i = 0; i < 40 && granted.status === 400; i++) await new Promise((r) => setTimeout(r, 1000)), (granted = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['fields_post_message'] }));
      // The team's copy of the desk's agent template, so the review can say which version it came from.
      const copy = await call(agents, 'POST', `/v1/resources/${encodeURIComponent(`plugin:${ID}:desk-helper`)}/copies`, priya, {});
      const review = await call(tools, 'GET', `/v1/apps/plugin:${ID}/update`, priya);
      check(
        'setup: team ops runs 0.1.0 with 0.2.0 installed, and its agent holds post_message',
        on.status === 200 && review.data?.available === true && review.data?.version === '0.1.0' && granted.status === 200 && copy.status === 201,
        { on: on.text, review: review.text, granted: granted.text, copy: copy.text },
      );

      const browser = await chromium.launch();
      const errors = [];
      try {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Work email').fill('p.shah@harborpine.example');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

        await step('9 the app page shows Update available with both versions and the counts', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(`plugin:${ID}`)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const notice = page.getByTestId('app-update');
          await notice.waitFor({ timeout: 60_000 });
          const text = await notice.innerText();
          await page.screenshot({ path: join(SHOTS, 'update-notice-1280.png'), fullPage: true });
          check('9 the app page shows Update available with both versions and the counts', /Update available: 1 new tool, 2 changed, 1 removed/.test(text) && text.includes('0.1.0') && text.includes('0.2.0'), text);
        }, page);

        await step('10 the review lists each tool with what changed and names the agent that uses the changed ones', async () => {
          await page.getByTestId('app-update-review').click();
          const rows = page.getByTestId('app-update-tools');
          await rows.waitFor({ timeout: 30_000 });
          await page.getByText('Used by Message desk (agent)').first().waitFor({ timeout: 30_000 });
          const text = await rows.innerText();
          const copies = await page.getByTestId('app-update-copies').innerText();
          await page.screenshot({ path: join(SHOTS, 'update-review-1280.png'), fullPage: true });
          await page.setViewportSize({ width: 400, height: 900 });
          await page.screenshot({ path: join(SHOTS, 'update-review-400.png'), fullPage: true });
          await page.setViewportSize({ width: 1280, height: 900 });
          check(
            '10 the review lists each tool with what changed, the agent that uses the changed ones, and the version the team\'s copy came from',
            ['Close a case', 'Move money', 'Post a message', 'Find records by status'].every((t) => text.includes(t)) && text.includes('Used by Message desk (agent)') && text.includes('Changes status')
              && copies.includes('Desk helper') && copies.includes('Made from version 2'),
            { tools: text.slice(0, 600), copies },
          );
        }, page);

        await step('11 taking the update makes 0.2.0 the team\'s version and the notice goes', async () => {
          await page.getByTestId('app-update-take').click();
          await page.getByTestId('app-update').waitFor({ state: 'detached', timeout: 30_000 });
          const after = await call(tools, 'GET', `/v1/apps/plugin:${ID}/update`, priya);
          await page.screenshot({ path: join(SHOTS, 'update-taken-1280.png'), fullPage: true });
          check("11 taking the update makes 0.2.0 the team's version and the notice goes", after.data?.version === '0.2.0' && after.data?.available === false, after.text);
        }, page);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    {
      demo: true,
      tools: { env: { ...fake.info.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([V2]), OPS_FLAGS: JSON.stringify(['plugin_updates']) } },
    },
  );
} finally {
  fake.child.stdin.end();
}
finish();
