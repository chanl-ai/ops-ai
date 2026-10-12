// uc-013 a tool's credential is a secret that never comes back, ui layer: docs/usecases/tools-service/secrets.md.
// Headless Chromium on Settings > Secrets, against tools-service's /v1/secrets.
import { TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const NAME = `UC013_UI_${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
const FIRST = `sk-first-${Math.random().toString(36).slice(2, 12)}`;
const SECOND = `sk-second-${Math.random().toString(36).slice(2, 12)}`;
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      // Every answer from the secrets routes, to show no value ever comes back.
      const answers = [];
      page.on('response', async (r) => r.url().startsWith(`${tools}/v1/secrets`) && r.request().method() !== 'OPTIONS' && answers.push(await r.text().catch(() => '')));
      const secretsCall = (method, suffix = '') => armed(page.waitForResponse((r) => r.request().method() === method && r.url() === `${tools}/v1/secrets${suffix}`, { timeout: 60_000 }));

      await page.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Add secret' }).click({ timeout: 120_000 });
      let dialog = page.getByRole('dialog', { name: 'Add a secret' });
      await dialog.getByLabel('Name').fill(NAME);
      await dialog.getByLabel('Value').fill(FIRST);
      const created = secretsCall('POST');
      await dialog.getByTestId('secret-submit').click();
      const createRes = await created;
      const sentValue = createRes ? JSON.parse(createRes.request().postData() ?? '{}').value : undefined;
      const row = page.getByRole('row', { name: new RegExp(NAME) });
      const listed = await row.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      // Non-vacuous pair: the value did go out in the request, so not finding it below means it never came back.
      check('Add secret creates it (201) with the typed value in the request', createRes?.status() === 201 && sentValue === FIRST, createRes?.status());
      check('the new secret is listed at v1 and shows how a header names it', listed && (await row.innerText()).includes('v1') && (await row.innerText()).includes(`{{${NAME}}}`), listed && (await row.innerText()));
      await page.reload({ waitUntil: 'domcontentloaded' });
      await row.waitFor({ timeout: 30_000 });
      check('no answer and no page carries the value', answers.length >= 2 && answers.every((a) => !a.includes(FIRST)) && !(await page.content()).includes(FIRST), { answers: answers.length });

      // A taken name is refused (409) and the dialog points at rotate.
      await page.getByRole('button', { name: 'Add secret' }).click();
      dialog = page.getByRole('dialog', { name: 'Add a secret' });
      await dialog.getByLabel('Name').fill(NAME);
      await dialog.getByLabel('Value').fill('another');
      const dup = secretsCall('POST');
      await dialog.getByTestId('secret-submit').click();
      const dupRes = await dup;
      const said = await dialog.getByText(/Rotate it to change its value/).waitFor({ timeout: 10_000 }).then(() => true, () => false);
      check('a taken name is refused (409) and the dialog says to rotate', dupRes?.status() === 409 && said, { status: dupRes?.status(), dialog: (await dialog.innerText()).slice(0, 300) });
      await page.keyboard.press('Escape');

      await row.getByRole('button').last().click();
      await page.getByRole('menuitem', { name: 'Rotate' }).click();
      dialog = page.getByRole('dialog', { name: `Rotate ${NAME}` });
      await dialog.getByLabel('New value').fill(SECOND);
      const rotated = secretsCall('POST', `/${NAME}/rotate`);
      await dialog.getByTestId('secret-submit').click();
      const rotateRes = await rotated;
      await page.getByRole('row', { name: new RegExp(`${NAME}.*v2`) }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('Rotate makes v2 and neither value comes back', rotateRes?.status() === 200 && (await row.innerText()).includes('v2') && answers.every((a) => !a.includes(FIRST) && !a.includes(SECOND)), { status: rotateRes?.status(), row: await row.innerText() });

      await row.getByRole('button').last().click();
      await page.getByRole('menuitem', { name: 'Delete' }).click();
      const deleted = secretsCall('DELETE', `/${NAME}`);
      await page.getByRole('dialog', { name: /^Delete secret/ }).getByRole('button', { name: 'Delete secret' }).click();
      const deleteRes = await deleted;
      const gone = await row.waitFor({ state: 'detached', timeout: 30_000 }).then(() => true, () => false);
      check('Delete removes it (204) from the list', deleteRes?.status() === 204 && gone, deleteRes?.status());

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { tools: {} },
);

finish();
