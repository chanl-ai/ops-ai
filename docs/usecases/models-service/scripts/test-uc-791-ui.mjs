// uc-791 A provider type added as a file shows in the add list, ui layer: steps 4-5 of
// docs/usecases/models-service/a-provider-type-added-as-a.md. The run's models-service reads one extra registry JSON
// entry ("Acme LLM") from a folder; the console is the unchanged production build, so the type can only show because
// the add list is drawn from GET /v1/models/provider-types and the form from the entry's JSON Schema.
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { FAKE_OPENAI_KEY, MODELS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SAM = 's.adeyemi@harborpine.example';
const PASSWORD = 'northfield-demo';
const NAME = `acme-${Math.random().toString(36).slice(2, 6)}`;
const SHOTS = evidenceDir('791', 'uc-791');
mkdirSync(SHOTS, { recursive: true });

const folder = mkdtempSync(join(tmpdir(), 'uc791-ui-registry-'));
writeFileSync(
  join(folder, 'acme-llm.json'),
  JSON.stringify({
    id: 'acme-llm',
    label: 'Acme LLM',
    icon: 'acme',
    adapter: 'openai-compatible',
    connection: {
      type: 'object',
      properties: {
        baseUrl: { type: 'string', title: 'Acme endpoint', format: 'uri', 'x-column': 'base_url' },
        apiKey: { type: 'string', title: 'Acme token', 'x-secret': true },
      },
      required: ['baseUrl', 'apiKey'],
    },
    modelList: { path: '/models', auth: 'bearer' },
  }),
);
// The models service the stack starts inherits this environment.
process.env.OPS_MODELS_PROVIDER_REGISTRY_EXTRA = folder;

await withUiStack(
  async (consoleUrl, stack) => {
    void stack;
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      page.setDefaultTimeout(30_000);
      await page.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('provider-connections').waitFor({ timeout: 60_000 });
      await page.getByTestId('provider-connect').click();
      await page.getByTestId('provider-search').click();
      await page.getByPlaceholder('Search providers…').last().fill('acme');
      await page.getByTestId('provider-search-option-acme-llm').click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Acme endpoint').waitFor();
      const masked = (await dialog.getByLabel('Acme token').getAttribute('type')) === 'password';
      await page.screenshot({ path: join(SHOTS, 'acme-form.png') });
      check('4 the file-added type shows in the console\'s searched list and draws its own fields, its token masked', masked, { masked });

      await dialog.getByTestId('provider-connect-name').fill(NAME);
      await dialog.getByLabel('Acme endpoint').fill(`http://127.0.0.1:${MODELS_PORT}/v1`);
      await dialog.getByLabel('Acme token').fill(FAKE_OPENAI_KEY);
      await dialog.getByTestId('provider-connect-save').click();
      // A key is only ever tested against a public address, so a loopback endpoint is refused and the dialog says so.
      await dialog.getByTestId('provider-connect-refused').waitFor();
      await dialog.getByTestId('provider-connect-done').click();
      const row = page.getByTestId('provider-connections').locator('tr', { hasText: NAME });
      await row.waitFor();
      const shown = (await row.innerText()).replace(/\s+/g, ' ');
      check('5 the connection is saved and listed as Acme LLM, and its loopback key test is refused', shown.includes('Acme LLM') && !(await page.content()).includes(FAKE_OPENAI_KEY), shown);
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
