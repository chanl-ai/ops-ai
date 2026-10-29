// uc-252 a builder archives a workflow and restores it, ui layer: docs/usecases/agents-service/archive-a-workflow.md.
// James publishes a one-step workflow and runs it. Archived (the console has no archive button, so through the API
// as the api script does), it leaves the Workflows list and the Start run picker while its run's page still opens;
// restored, it is listed and offered again. Platform sign-in, no model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, readRunPage, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `Old intake uc-252 ${TAG}`;
const DEFINITION = `
schemaVersion: 2
id: uc252_old_intake_${TAG}
name: ${NAME}
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
`;

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const made = await saveAndPublish(J, DEFINITION);
    await stack.startWorker();
    const runId = await start(J, made.id, {});
    const ran = await settled(J, runId);
    check('0 the workflow goes live and its run succeeds', made.live && ran?.status === 'succeeded', { live: made.live, status: ran?.status });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      // What a person sees of it: its row on the Workflows page, and whether Start run offers it.
      const seen = async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByPlaceholder('Search workflows…').fill(TAG);
        const listed = await page.getByRole('row').filter({ hasText: NAME }).first().waitFor({ timeout: 15_000 }).then(() => true, () => false);
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 60_000 });
        const picker = page.getByRole('dialog', { name: 'Start a run' });
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill(TAG);
        const offered = await page.getByRole('option', { name: new RegExp(NAME) }).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
        await page.keyboard.press('Escape');
        return { listed, offered };
      };
      const before = await seen();
      check('1 live, it is listed on the Workflows page and offered by Start run', before.listed && before.offered, before);

      const archived = await fetch(`${agents}/v1/workflows/definitions/${made.id}/archive`, { method: 'POST', headers: J });
      const gone = await seen();
      const kept = await readRunPage(page, consoleUrl, runId);
      check(
        '2 archived, it leaves the Workflows page and Start run, and its run still opens',
        archived.ok && !gone.listed && !gone.offered && /succeeded|done/i.test(kept.status),
        { archived: archived.status, ...gone, run: kept.status },
      );

      const restored = await fetch(`${agents}/v1/workflows/definitions/${made.id}/restore`, { method: 'POST', headers: J });
      const back = await seen();
      check('3 restored, it is listed and offered again', restored.ok && back.listed && back.offered, { restored: restored.status, ...back });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
