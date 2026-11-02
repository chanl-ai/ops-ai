// uc-605 A team runs its agents on its own Azure OpenAI resource, ui layer: steps 9-14 of
// docs/usecases/models-service/a-team-connects-azure-openai.md. The run's own demo stack: platform sign-in,
// models-service and the fake OpenAI, whose Azure paths answer only FAKE_OPENAI_KEY in `api-key` and say they run in
// Sweden Central. Sam is the account admin (an admin on the Security team); James is a builder of Operations.
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { FAKE_OPENAI_KEY, MODELS_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const models = `http://127.0.0.1:${MODELS_PORT}`;
const PASSWORD = 'northfield-demo';
const SAM = 's.adeyemi@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
const KEY = 'AZURE_UC605';
const NAME = 'uc605-ui';
const SHOTS = evidenceDir('605', 'uc-605');
mkdirSync(SHOTS, { recursive: true });
const signIn = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// agents-service's token for models-service's admin routes (dev key, dev only), as the install scripts call them.
const serviceToken = (tenant) =>
  execFileSync('uv', ['run', 'python', '-c', `from ops_identity import dev_service_signer, mint_service_token; print(mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="${tenant}", ttl_s=600))`], { cwd: join(ROOT, 'services/models-service'), encoding: 'utf8' }).trim();

/** Waits for `text` on `page`; on a timeout, saves the page and fails with what it showed instead. */
async function see(page, text, name) {
  try {
    await page.getByText(text).first().waitFor({ timeout: 60_000 });
  } catch (e) {
    await page.screenshot({ path: join(SHOTS, `failed-${name}.png`), fullPage: true }).catch(() => undefined);
    const shown = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400);
    throw new Error(`${name}: "${text}" not shown; the page showed: ${shown}`, { cause: e });
  }
}

await withUiStack(
  async (consoleUrl) => {
    const sam = await signIn(SAM);
    const tenant = sam.principal.tenantId;
    const N = { Authorization: `Bearer ${sam.token}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
    const J = { Authorization: `Bearer ${(await signIn(JAMES)).token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const S = { Authorization: `Bearer ${serviceToken(tenant)}`, 'Content-Type': 'application/json' };
    // The fake's root is the Azure resource's endpoint; its /v1 is OpenAI's path.
    const endpoint = (await data(await fetch(`${models}/v1/models/providers`, { headers: S }))).find((p) => p.id === 'openai-local').baseUrl.replace(/\/v1$/, '');
    await data(await fetch(`${models}/v1/provider-keys/${KEY}`, { method: 'PUT', headers: N, body: JSON.stringify({ value: FAKE_OPENAI_KEY }) }));
    const aliasOn = async (alias, providerId) => data(await fetch(`${models}/v1/models/aliases`, { method: 'POST', headers: S, body: JSON.stringify({ name: alias, kind: 'chat', providerId, modelId: 'claims-gpt4o', clearedSensitivity: 'confidential' }) }));
    const chat = (alias) =>
      fetch(`${models}/v1/models/chat/completions`, {
        method: 'POST',
        headers: { Authorization: 'Bearer mk_dev_agents', 'X-Tenant-Id': tenant, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: alias, messages: [{ role: 'user', content: 'Summarise claim CLM-77 for the adjuster.' }] }),
      });
    const providerId = async (name) => (await data(await fetch(`${models}/v1/models/providers`, { headers: S }))).find((p) => p.name === name)?.id;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      await page.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('provider-connections').waitFor({ timeout: 60_000 });
      await page.getByTestId('provider-connect').click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Endpoint').waitFor({ timeout: 30_000 });
      const azureFields = (await dialog.getByLabel('API version').count()) === 1 && (await dialog.getByLabel('Region').count()) === 1;
      await page.getByTestId('provider-type').click();
      await page.getByRole('option', { name: 'OpenAI-compatible' }).click();
      const plainFields = (await dialog.getByLabel('API version').count()) === 0 && (await dialog.getByLabel('Region').count()) === 0;
      await page.getByTestId('provider-type').click();
      await page.getByRole('option', { name: 'Azure OpenAI' }).click();
      check('9 picking Azure OpenAI asks endpoint, API version, region and key; OpenAI-compatible asks no version or region', azureFields && plainFields, { azureFields, plainFields });

      await dialog.getByLabel('Name').fill(NAME);
      await dialog.getByLabel('Endpoint').fill(endpoint);
      await dialog.getByLabel('API version').fill('2024-06-01');
      await dialog.getByLabel('Region').fill('swedencentral');
      await page.getByTestId('provider-key-ref').click();
      await page.getByRole('option', { name: KEY }).click();
      await page.getByTestId('provider-connect-save').click();
      await see(page, 'older than 2024-10-21', 'old-version');
      await page.screenshot({ path: join(SHOTS, 'refused-version-1280.png'), fullPage: true });
      check('10 an API version too old to stream usage is refused under the field, and nothing is saved', !(await providerId(NAME)), 'a connection was saved');

      await dialog.getByLabel('API version').fill('2024-10-21');
      await page.getByTestId('provider-connect-save').click();
      await dialog.waitFor({ state: 'detached', timeout: 30_000 });
      const row = page.getByTestId('provider-connections').locator('tr', { hasText: NAME });
      await row.waitFor({ timeout: 30_000 });
      const shown = (await row.innerText()).replace(/\s+/g, ' ');
      check('11 the list shows the connection as Azure OpenAI with its endpoint, region, Not called yet and key name', ['Azure OpenAI', '2024-10-21', endpoint, 'swedencentral', 'Not called yet', KEY].every((t) => shown.includes(t)), shown);

      const id = await providerId(NAME);
      await aliasOn('uc605-ui-claims', id);
      const answered = await chat('uc605-ui-claims');
      await page.reload({ waitUntil: 'domcontentloaded' });
      await see(page, 'Answered from Sweden Central', 'answered');
      await page.screenshot({ path: join(SHOTS, 'connected-1280.png'), fullPage: true });
      check('12 an alias on it answers, and the list shows the region Azure answered from', answered.status === 200, answered.status);

      const west = await data(await fetch(`${models}/v1/models/providers`, { method: 'POST', headers: S, body: JSON.stringify({ name: 'uc605-west', type: 'azure-openai', baseUrl: endpoint, keyRef: KEY, apiVersion: 'v1', region: 'westeurope' }) }));
      await aliasOn('uc605-west-claims', west.id);
      const flagged = await chat('uc605-west-claims');
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('region-mismatch').first().waitFor({ timeout: 60_000 });
      await page.screenshot({ path: join(SHOTS, 'region-mismatch-1280.png'), fullPage: true });
      const mismatchRow = (await page.getByTestId('provider-connections').locator('tr', { hasText: 'uc605-west' }).innerText()).replace(/\s+/g, ' ');
      check('13 a connection answered from another region still answers, and its row says where Azure answered from and where it was expected', flagged.status === 200 && mismatchRow.includes('Answered from Sweden Central, expected westeurope'), { status: flagged.status, mismatchRow });

      const builder = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await builder.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await see(builder, 'Only an account admin', 'builder');
      const theirs = await fetch(`${models}/v1/models/providers`, { headers: J });
      const add = await fetch(`${models}/v1/models/providers`, { method: 'POST', headers: J, body: JSON.stringify({ name: 'uc605-james', type: 'azure-openai', baseUrl: endpoint, keyRef: KEY, apiVersion: 'v1', region: 'eastus' }) });
      const page2 = await builder.content();
      check('14 a builder sees no connection on the page and cannot list or add one', theirs.status === 403 && add.status === 403 && !page2.includes(NAME), { list: theirs.status, add: add.status });
      check('no page shows the key', !(await page.content()).includes(FAKE_OPENAI_KEY) && !page2.includes(FAKE_OPENAI_KEY));
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
