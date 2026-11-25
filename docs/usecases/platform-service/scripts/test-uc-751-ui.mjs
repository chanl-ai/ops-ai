// uc-751, ui layer: docs/usecases/platform-service/a-new-workspace-chats-and-writes.md, steps 3, 4 and 11. The run's own
// demo stack (platform sign-in, models-service, the fake OpenAI). The account admin (Sam Adeyemi, admin of the Security
// team) connects a model provider on Settings > Models > Connections in three steps (provider, its fields, the key test)
// at 1440 and at 390 wide, then Approvals shows the makers' ask-first switch off.
import { mkdirSync } from 'node:fs';

import { FAKE_OPENAI_KEY, MODELS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHOTS = evidenceDir('751', 'screens');
const EMAIL = 's.adeyemi@harborpine.example';
const PASSWORD = 'northfield-demo';
const TAG = Math.random().toString(36).slice(2, 6);
mkdirSync(SHOTS, { recursive: true });

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      for (const [w, h] of [
        [1440, 900],
        [390, 844],
      ]) {
        const name = `acme-${w}-${TAG}`;
        const page = await consoleSignIn(browser, consoleUrl, EMAIL, PASSWORD, errors);
        page.setDefaultTimeout(30_000);
        await page.setViewportSize({ width: w, height: h });
        await page.goto(`${consoleUrl}/settings/workspace/model-providers`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('provider-connections').waitFor({ timeout: 60_000 });
        await page.screenshot({ path: `${SHOTS}/0-connections-${w}.png` });
        await page.getByTestId('provider-connect').click();
        await page.getByTestId('provider-search').click();
        await page.getByPlaceholder('Search providers…').last().fill('compatible');
        await page.getByTestId('provider-search-option-openai-compatible').click();
        const dialog = page.getByRole('dialog');
        await dialog.getByTestId('provider-connect-name').fill(name);
        await dialog.getByTestId('provider-connect-baseUrl').fill(`http://127.0.0.1:${MODELS_PORT}/v1`);
        await dialog.getByTestId('provider-connect-apiKey').fill(FAKE_OPENAI_KEY);
        await page.screenshot({ path: `${SHOTS}/1-fields-${w}.png` });
        await dialog.getByTestId('provider-connect-save').click();
        // A key is only tested against a public address, so the loopback endpoint is refused and the dialog says so.
        const refused = await dialog.getByTestId('provider-connect-refused').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        await page.screenshot({ path: `${SHOTS}/2-test-${w}.png` });
        check(`${w}: the admin connects a provider in three steps and sees the key test's answer`, refused);
        await dialog.getByTestId('provider-connect-done').click();
        const row = page.getByTestId('provider-connections').locator('tr', { hasText: name });
        const listed = await row.waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.screenshot({ path: `${SHOTS}/3-listed-${w}.png` });
        check(`${w}: the connection is listed with the key name it signs in with, and no page shows the key`, listed && (await row.innerText()).includes(name.toUpperCase()) && !(await page.content()).includes(FAKE_OPENAI_KEY));
        await page.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const sw = page.getByTestId('approvals-makers-switch');
        const there = await sw.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check(`${w}: Approvals shows the makers' ask-first switch, off in a new workspace`, there && (await sw.getAttribute('aria-checked')) === 'false');
        await sw.scrollIntoViewIfNeeded();
        await page.screenshot({ path: `${SHOTS}/5-approvals-switch-${w}.png` });
        await page.context().close();
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
