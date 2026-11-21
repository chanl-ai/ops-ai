// uc-761 a builder edits a workflow that saves itself, publishes it past its problems and compares its versions, ui
// layer: docs/usecases/console/workflow-drafts-and-versions.md. Signed in through platform-service: James (builder)
// edits, Priya (admin) saves on an old copy through the API, Maya approves reviews, Ravi (viewer) only looks.
import { approvePublishRequest, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, PRIYA, agents, as, publishReviewOn } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const ID = `uc761_${Math.random().toString(36).slice(2, 6)}`;
const node = (id, type, name, x, parameters) => ({ id, type, typeVersion: 1, name, ...(parameters ? { parameters } : {}), position: { x, y: 0 } });
const WORKFLOW = {
  schemaVersion: 2,
  id: ID,
  name: 'Card limit change (uc-761)',
  nodes: [node('start', 'ops.trigger.request', 'Limit asked', 0), node('note', 'ops.data.set', 'Note the new limit', 300, { values: { limit: '$.input.limit' } }), node('done', 'ops.flow.end', 'Done', 600, { outcome: 'done' })],
  connections: [
    { from: { node: 'start', port: 'payload' }, to: { node: 'note', port: 'in' } },
    { from: { node: 'note', port: 'out' }, to: { node: 'done', port: 'in' } },
  ],
};
const path = `/v1/workflows/definitions/${ID}`;
const view = async (h) => (await (await fetch(`${agents}${path}`, { headers: h })).json()).data;

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

await withUiStack(
  async (consoleUrl) => {
    await publishReviewOn({ workflows: 'major' });
    const J = await as(JAMES);
    const M = await as(MAYA);
    const made = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: WORKFLOW }) })).json();
    const asked = await (await fetch(`${agents}${path}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'first' }) })).json();
    await approvePublishRequest(asked.data, M);
    check('0 the workflow is live at version 1', made.data?.version === 1 && (await view(J)).liveVersion === 1, { made, asked });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const saves = [];
      page.on('request', (r) => r.url().includes('/working-copy') && r.method() === 'PUT' && saves.push(r.url()));
      const state = () => page.getByTestId('definition-save-state');
      const open = async () => {
        await page.goto(`${consoleUrl}/build/workflows/definitions/${ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
      };
      const settings = async (parameters) => {
        await page.locator('[data-testid="definition-node"]', { hasText: 'Note the new limit' }).click();
        await page.getByTestId('step-sheet').waitFor();
        if (!(await page.getByTestId('definition-node-parameters').isVisible())) await page.getByTestId('definition-node-all-settings').click();
        await page.getByTestId('definition-node-parameters').fill(JSON.stringify(parameters));
      };
      const saved = () => state().getByText(/Saved/).waitFor({ timeout: 30_000 });
      await open();

      await step('1 no Save button; nothing saved yet; no problems', async () => {
        const text = (await state().innerText()).trim();
        const chip = (await page.getByTestId('definition-problems').innerText()).trim();
        check('1 no Save button; nothing saved yet; no problems', (await page.getByTestId('definition-save').count()) === 0 && text === 'No changes yet' && chip === 'No problems', { text, chip });
      });

      await step('2 a change saves itself and makes no version', async () => {
        await settings({ values: { limit: '$.input.limit', reason: '$.input.reason' } });
        await state().getByText('Saving').waitFor({ timeout: 10_000 }).catch(() => undefined);
        await saved();
        const v = await view(J);
        check('2 a change saves itself and makes no version', saves.length >= 1 && v.versions.length === 1 && !!v.workingCopy && (await state().innerText()).includes('Saved just now'), { saves: saves.length, versions: v.versions.length });
      });

      await step('3 a broken step shows in the problems chip and still saves', async () => {
        await settings({ values: 5 });
        await page.locator('[data-testid="definition-problems"]:not([data-errors="0"])').waitFor({ timeout: 30_000 });
        const chip = (await page.getByTestId('definition-problems').innerText()).trim();
        await saved();
        const v = await view(J);
        check('3 a broken step shows in the problems chip and still saves', /^\d+ problems?$/.test(chip) && v.workingCopy.checks.some((c) => c.level === 'error') && v.versions.length === 1, { chip, checks: v.workingCopy.checks });
      });

      await step('4 leaving before the save lands asks first', async () => {
        await settings({ values: 6 });
        await page.locator('a[href="/build/workflows"]').first().click();
        await page.getByTestId('leave-guard').waitFor({ timeout: 5_000 });
        await page.getByTestId('leave-guard-keep').click();
        await saved();
        check('4 leaving before the save lands asks first', page.url().includes(ID));
      });

      await step('5 publish lists the problem and sends nothing', async () => {
        await page.keyboard.press('Escape');
        await page.getByTestId('definition-publish').click();
        await page.getByTestId('definition-publish-blockers').waitFor({ timeout: 30_000 });
        await page.getByTestId('definition-publish-submit').click();
        await page.waitForTimeout(800);
        const v = await view(J);
        const fixes = await page.getByTestId('definition-publish-fix').count();
        await shootBothWidths(page, 'console', 'uc-761-publish-blocked', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('5 publish lists the problem and sends nothing', fixes >= 1 && v.versions.length === 1 && (await page.getByRole('dialog').count()) === 1, { fixes, versions: v.versions.length });
        await page.getByTestId('definition-publish-fix').first().click();
      });

      await step('6 a save made on an older copy is refused, naming who saved first', async () => {
        const P = await as(PRIYA);
        const r = await fetch(`${agents}${path}/working-copy`, { method: 'PUT', headers: P, body: JSON.stringify({ definition: WORKFLOW, baseVersion: 1, baseDigest: made.data.digest }) });
        const body = await r.json();
        check('6 a save made on an older copy is refused, naming who saved first', r.status === 409 && body.error?.code === 'stale_base' && body.error?.details?.savedBy === JAMES, body.error);
      });

      await step('7 a fixed step publishes for review with its change listed', async () => {
        await settings({ values: { limit: '$.input.limit', reason: '$.input.reason' } });
        await page.getByTestId('definition-problems').getByText('No problems').waitFor({ timeout: 30_000 });
        await saved();
        await page.keyboard.press('Escape');
        await page.getByTestId('definition-publish').click();
        await page.getByTestId('definition-changes').waitFor({ timeout: 30_000 });
        const listed = await page.getByTestId('definition-changes').innerText();
        const next = await page.getByTestId('definition-publish-next').innerText();
        await page.locator('#definition-publish-note').fill('Notes the reason with the new limit');
        await page.getByTestId('definition-publish-submit').click();
        await page.getByTestId('definition-review-link').waitFor({ timeout: 30_000 });
        const v = await view(J);
        check('7 a fixed step publishes for review with its change listed', listed.includes('Note the new limit') && /another person/.test(next) && v.versions.length === 2 && v.review?.version === 2 && !v.workingCopy, { listed, next, versions: v.versions.length });
        await approvePublishRequest({ id: v.review.id, status: 'pending' }, M);
      });

      await step('8 moving a step alone goes live with no review', async () => {
        await open();
        const box = await page.locator('[data-testid="definition-node"]', { hasText: 'Done' }).boundingBox();
        await page.mouse.move(box.x + 40, box.y + 12);
        await page.mouse.down();
        await page.mouse.move(box.x + 40, box.y + 160, { steps: 8 });
        await page.mouse.up();
        await saved();
        await page.getByTestId('definition-publish').click();
        await page.getByTestId('definition-publish-next').getByText(/goes live at once/).waitFor({ timeout: 30_000 });
        await page.getByTestId('definition-publish-submit').click();
        await page.waitForTimeout(1500);
        const v = await view(J);
        check('8 moving a step alone goes live with no review', v.liveVersion === 3 && !v.review, { live: v.liveVersion, review: v.review });
      });

      await step('9 Versions compares a setting old and new', async () => {
        await page.getByTestId('workflow-tab-versions').click();
        await page.getByTestId('definition-version-1').waitFor({ timeout: 30_000 });
        const listed = await page.locator('[data-testid^="definition-version-"]').count();
        await page.getByTestId('definition-compare-1').click();
        await page.getByTestId('definition-field-change').first().waitFor({ timeout: 30_000 });
        const fields = await page.getByTestId('definition-field-change').evaluateAll((els) => els.map((e) => e.getAttribute('data-field')));
        await shootBothWidths(page, 'console', 'uc-761-versions-compare', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('9 Versions compares a setting old and new', listed >= 3 && fields.includes('parameters.values'), { listed, fields });
        await page.keyboard.press('Escape');
      });

      await step('10 restoring version 1 fills the working copy and adds no version', async () => {
        await page.getByTestId('definition-restore-1').click();
        await page.getByRole('dialog').getByRole('button', { name: 'Restore' }).click();
        await page.getByTestId('definition-version-working-copy').waitFor({ timeout: 30_000 });
        const v = await view(J);
        check('10 restoring version 1 fills the working copy and adds no version', v.versions.length === 3 && JSON.stringify(v.workingCopy?.definition.nodes[1].parameters) === JSON.stringify(WORKFLOW.nodes[1].parameters), { versions: v.versions.length });
        await open();
        await shootBothWidths(page, 'console', 'uc-761-canvas-saved', async () => page.waitForTimeout(300));
      });

      await step('11 a viewer sees the canvas with no save state and no Publish', async () => {
        const ravi = await consoleSignIn(browser, consoleUrl, RAVI, PASSWORD, errors);
        await ravi.goto(`${consoleUrl}/build/workflows/definitions/${ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await ravi.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
        const seen = { save: await ravi.getByTestId('definition-save-state').count(), publish: await ravi.getByTestId('definition-publish').count(), viewOnly: await ravi.getByTestId('definition-view-only').count() };
        await shootBothWidths(ravi, 'console', 'uc-761-viewer', async () => ravi.waitForTimeout(300));
        check('11 a viewer sees the canvas with no save state and no Publish', seen.save === 0 && seen.publish === 0 && seen.viewOnly === 1, seen);
      });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
