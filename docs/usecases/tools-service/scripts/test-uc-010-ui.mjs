// uc-010 a builder manages a tool module, ui layer (c-027): docs/usecases/tools-service/manage-tool-modules.md.
// Headless Chromium against a console whose Tools pages call tools-service: edit a published operation's URL in the
// operation sheet, see the change pending and the unused-input warning, publish, see the major version.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JSONH = { 'Content-Type': 'application/json' };
const SECURITY = { ...JSONH, 'X-Dev-User': 'Nadia Petrov' };
const HOST = 'statements.bank.test';
const TAG = Math.random().toString(36).slice(2, 6);
const OP = `get_statement_${TAG}`;
const SHOTS = join(ROOT, 'evidence/027');
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const api = async (method, path, body, headers = JSONH) => {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

await withUiStack(
  async (consoleUrl) => {
    // A published module with one hand-built operation on the bank's statements API.
    await api('POST', '/v1/egress/hosts', { value: HOST, note: 'uc-010 ui' });
    const made = await api('POST', '/v1/tool-modules/blank', { displayName: `Statements ${TAG}`, name: `uc010-statements-${TAG}`, type: 'http' });
    const id = made.data?.id;
    await api('POST', `/v1/tool-modules/${id}/operations`, { name: OP, description: 'Monthly statement', access: 'read', method: 'GET', url: `https://${HOST}/v1/accounts/{accountId}/statements`, headers: [] });
    const reviewed = await api('POST', `/v1/tool-modules/${id}/reviews`, { note: 'uc-010 ui' });
    const review = reviewed.data?.reviews?.find((r) => r.decision === 'pending');
    const published = await api('POST', `/v1/tool-modules/${id}/reviews/${review?.id}/decide`, { decision: 'approved' }, SECURITY);
    // A draft's first approved review publishes 0.1.0; a major change after it makes 1.0.0.
    const start = published.data?.version;
    const nextMajor = start ? `${Number(start.split('.')[0]) + 1}.0.0` : undefined;
    check('the module starts published with the operation', published.status === 200 && published.data?.status === 'published' && !!start, { status: published.status, version: start });

    mkdirSync(SHOTS, { recursive: true });
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('row', { name: new RegExp(OP) }).click({ timeout: 120_000 });
      const http = page.getByTestId('op-http');
      await http.waitFor({ timeout: 30_000 });
      const url = http.getByLabel('Request');
      check('the sheet shows the published call in the HTTP section', (await url.inputValue()) === `https://${HOST}/v1/accounts/{accountId}/statements` && (await page.getByTestId('op-unused-inputs').count()) === 0);
      // The sheet slides in; wait for it to settle before the screenshot.
      await page.waitForTimeout(800);
      await page.screenshot({ path: join(SHOTS, '1-http-section-published.png') });

      // Non-vacuous pair with the edit below: another origin is refused before anything is sent.
      await url.fill('https://other.bank.test/v1/x');
      const blocked = (await page.getByTestId('op-stage').isDisabled()) && (await http.getByText(/Keep the module endpoint/).count()) === 1;
      check('a URL off the module endpoint is refused in the sheet and cannot be staged', blocked);

      await url.fill(`https://${HOST}/v2/statements/latest`);
      const unused = page.getByTestId('op-unused-inputs');
      check('a path that drops {accountId} warns that the input is unused', (await unused.innerText().catch(() => '')).startsWith('accountId is an input'));
      const staged = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/tool-modules/${id}/operations/`), { timeout: 60_000 }));
      await page.getByTestId('op-stage').click();
      const stageRes = await staged;
      const sent = stageRes ? JSON.parse(stageRes.request().postData() ?? '{}') : {};
      const pending = stageRes ? (await stageRes.json()).data?.pendingChanges ?? [] : [];
      check('Stage change sends only the new path, staged as one major change', stageRes?.status() === 200 && JSON.stringify(sent) === JSON.stringify({ path: '/v2/statements/latest' }) && pending.length === 1 && pending[0].major === true && pending[0].kind === 'schema_changed', { status: stageRes?.status(), sent, pending });
      await page.getByTestId('unpublished-indicator').waitFor({ timeout: 30_000 });
      const callLine = page.getByTestId('op-call');
      await callLine.getByText(/staged; calls run the published call/).waitFor({ timeout: 10_000 }).catch(() => undefined);
      check('the sheet labels the staged call as not yet what calls run', (await callLine.innerText()).includes('staged; calls run the published call'), await callLine.innerText());
      await page.screenshot({ path: join(SHOTS, '2-pending-path-edit-unused-warning.png') });
      const live = await api('GET', `/v1/tool-modules/${id}`);
      check('the published version is unchanged until publish', live.data?.version === start && live.data?.pendingChanges?.length === 1, { version: live.data?.version });

      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: 'Publish version' }).first().click();
      const dialog = page.getByRole('dialog', { name: 'Publish a major version?' });
      await dialog.getByRole('textbox').first().fill('Statements moved to v2');
      const publishedRes = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/versions`), { timeout: 60_000 }));
      await dialog.getByRole('button', { name: 'Publish', exact: true }).click();
      const pub = await publishedRes;
      const after = pub ? (await pub.json()).data : undefined;
      check('publishing the path edit makes the next major version and opens a security review', pub?.status() === 200 && after?.version === nextMajor && after?.reviews?.some((r) => r.decision === 'pending'), { status: pub?.status(), version: after?.version, nextMajor });
      await page.getByText(`Published v${nextMajor}`).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      await dialog.waitFor({ state: 'hidden', timeout: 30_000 }).catch(() => undefined);
      await page.getByText(`v${nextMajor}`, { exact: true }).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      await page.waitForTimeout(500);
      await page.screenshot({ path: join(SHOTS, '3-published-major-version.png') });
      const opNow = after?.operations?.find((o) => o.name === OP);
      check('the operation now calls the edited path', opNow?.path === '/v2/statements/latest', opNow?.path);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { tools: {} },
);

finish();
