// uc-104 a guardrail has its own page and an agent pins one of its versions, ui layer:
// docs/usecases/console/guardrail-record-page.md. Headless Chromium against the console signed in through
// platform-service. James opens a guardrail from the list, saves and publishes v2 on its page (Maya, the team's
// approver, approves each publish: a requester does not decide their own), sees both versions, then pins v1 on an agent
// from the agent's Guardrails section and the agent saves itself.
import { AGENTS_PORT, approvePublishRequest, asRole, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `No tips ${TAG}`;
const armed = (p) => (p.catch(() => undefined), p);
let J = {};
const api = async (path, init = {}) => {
  const r = await fetch(`${agents}${path}`, { ...init, headers: J });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`setup: ${init.method ?? 'GET'} ${path} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

await withUiStack(async (consoleUrl) => {
  J = await asRole('builder', 'team_ops');
  const maya = await asRole('approver', 'team_ops');
  const g = await api('/v1/guardrails', { method: 'POST', body: JSON.stringify({ name: NAME, topics: ['stock tips'], message: 'I cannot give stock tips.' }) });
  await approvePublishRequest(await api(`/v1/guardrails/${g.id}/publish-requests`, { method: 'POST', body: JSON.stringify({ version: 1, note: 'first' }) }), maya);
  const agent = await api('/v1/agents', { method: 'POST', body: JSON.stringify({ name: `Tips desk ${TAG}`, role: 'Answers account questions' }) });

  const browser = await chromium.launch();
  try {
    const errors = [];
    const page = await consoleSignIn(browser, consoleUrl, 'j.richardson@harborpine.example', 'northfield-demo', errors);

    // The list row opens the guardrail's own page.
    await page.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('row', { name: new RegExp(NAME) }).first().click({ timeout: 120_000 });
    await page.waitForURL((u) => u.pathname === `/build/guardrails/${g.id}`, { timeout: 60_000 });
    await page.getByTestId('save-guardrail').waitFor({ timeout: 60_000 });
    check('a guardrail row opens its own page', new URL(page.url()).pathname === `/build/guardrails/${g.id}`, page.url());

    // Save v2 on the page, then publish it.
    await page.getByLabel('Message instead of an answer').fill('I cannot give stock tips. An adviser can.');
    await page.getByLabel('What changed').fill('Points to an adviser');
    const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/guardrails/${g.id}`), { timeout: 30_000 }));
    await page.getByTestId('save-guardrail').click();
    const savedStatus = (await saved)?.status();
    await page.getByTestId('publish-guardrail').waitFor({ timeout: 30_000 });
    const published = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/guardrails/${g.id}/publish-requests`), { timeout: 30_000 }));
    await page.getByTestId('publish-guardrail').click();
    const publishedRes = await published;
    const publishedStatus = publishedRes?.status();
    // Maya approves v2's publish request as Reviews would; the page then shows v2 live.
    if (publishedRes?.ok()) await approvePublishRequest((await publishedRes.json()).data, maya);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByTestId('guardrail-versions-tab').click({ timeout: 60_000 });
    const table = page.getByTestId('guardrail-versions');
    await table.getByTestId('guardrail-version-2').waitFor({ timeout: 30_000 });
    const rows = {
      saved: savedStatus,
      published: publishedStatus,
      v2: await table.getByTestId('guardrail-version-2').innerText(),
      v1: await table.getByTestId('guardrail-version-1').innerText(),
    };
    check('saving and publishing on the page makes v2 live; Versions lists v2 live and v1 published, with the note', rows.saved === 200 && rows.published === 201 && /Live for new pins/.test(rows.v2) && /Points to an adviser/.test(rows.v2) && /Published/.test(rows.v1), rows);

    // The agent pins v1 from its Guardrails section; the pin links to the guardrail's page.
    await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    // The guardrail picker (EntityPicker) pins it; the pinned row then offers its version.
    await page.getByTestId('guardrail-picker').getByRole('button', { name: 'Pin guardrails' }).click({ timeout: 120_000 });
    await page.getByPlaceholder('Search guardrails…').fill(NAME);
    await page.getByRole('option', { name: new RegExp(NAME) }).click({ timeout: 30_000 });
    await page.keyboard.press('Escape');
    const pin = page.getByTestId('guardrail-pin').filter({ hasText: NAME });
    const link = await pin.getByTestId('guardrail-pin-link').getAttribute('href');
    await pin.getByRole('combobox', { name: `${NAME} version` }).click();
    // The agent page saves each edit into its draft by itself; the version pick is the last edit, so its save holds v1.
    const patched = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`) && (r.request().postData() ?? '').includes(`"guardrailId":"${g.id}","version":1`), { timeout: 60_000 }));
    await page.getByRole('option', { name: 'v1', exact: true }).click();
    const res = await patched;
    const after = await api(`/v1/agents/${agent.id}`);
    const pins = (after.guardrailPins ?? []).map((p) => `${p.guardrailId}@${p.version}`);
    check('the agent pins v1 of the guardrail, chosen from its published versions, and the pin links to its page', res?.status() === 200 && pins.includes(`${g.id}@1`) && link === `/build/guardrails/${g.id}`, { status: res?.status(), pins, link });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, { platform: true });

finish();
