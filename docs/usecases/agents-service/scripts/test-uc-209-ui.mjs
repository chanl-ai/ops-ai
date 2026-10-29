// uc-209 a workflow starts a child workflow for each item of a list, ui layer:
// docs/usecases/agents-service/start-a-workflow-per-item.md. James publishes the api script's case and intake on the
// run's own stack and starts the intake for three persons. The intake's run page lists the three children in item
// order, each linking to a run whose page shows that person; a test run's page lists its one child. Platform sign-in,
// no model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, readRunPage, saveAndPublish, settled, start, until } from '../../lib/workflow_ui.mjs';

const RUN = Math.random().toString(36).slice(2, 10);
const CHILD = `uc209_case_${RUN}`;
const INTAKE = `uc209_intake_${RUN}`;
const PERSONS = [{ name: 'Ana Silva' }, { name: 'Bo Chen' }, { name: 'Cy Okafor' }];
const node = (id, type, name, parameters = {}) => ({ id, type, typeVersion: 1, name, parameters });
const wire = (a, port, b) => ({ from: { node: a, port }, to: { node: b, port: 'in' } });
const CASE = {
  schemaVersion: 2,
  id: CHILD,
  name: `Levy case ${RUN}`,
  nodes: [node('in', 'ops.trigger.request', 'Request'), node('done', 'ops.flow.end', 'Open', { outcome: 'open' })],
  connections: [wire('in', 'payload', 'done')],
};
const INTAKE_DEF = {
  schemaVersion: 2,
  id: INTAKE,
  name: `Levy intake ${RUN}`,
  nodes: [
    node('in', 'ops.trigger.request', 'Request'),
    node('open', 'ops.action.workflow', 'Open a case per person', { workflow: CHILD, forEach: '$.input.persons', input: { name: '$.item.name', position: '$.index', notice: '$.input.notice' } }),
    node('done', 'ops.flow.end', 'Cases opened', { outcome: 'cases_opened' }),
    node('failed', 'ops.flow.end', 'Not opened', { outcome: 'not_opened' }),
  ],
  connections: [wire('in', 'payload', 'open'), wire('open', 'started', 'done'), wire('open', 'error', 'failed')],
};

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const made = [await saveAndPublish(J, CASE), await saveAndPublish(J, INTAKE_DEF)];
    check('1 James publishes the case and the intake', made.every((m) => m.saved.status === 201 && m.live), made.map((m) => [m.saved.status, m.asked.data?.status]));
    await stack.startWorker();
    const parentId = await start(J, INTAKE, { notice: `N-${RUN}`, persons: PERSONS });
    const parent = await settled(J, parentId);
    const childrenOf = async (id) => ((await (await fetch(`${agents}/v1/runs?workflowId=${CHILD}&pageSize=100`, { headers: J })).json()).data?.data ?? []).filter((r) => r.createdBy === `run:${id}`);
    await until(async () => (await childrenOf(parentId)).filter((r) => r.status === 'succeeded').length === 3, 60);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const shown = await readRunPage(page, consoleUrl, parentId);
      const byPosition = (await childrenOf(parentId)).sort((a, b) => a.input.position - b.input.position).map((r) => r.id);
      check(
        "2 the intake's run page lists the three children it started, in item order",
        parent?.status === 'succeeded' && shown.outcome === 'cases_opened' && shown.children.length === 3 && shown.children.join() === byPosition.join(),
        { outcome: shown.outcome, shown: shown.children, byPosition },
      );
      // Each listed child opens on a page that shows the person it was started for.
      const named = [];
      for (const [i, id] of shown.children.entries()) {
        await page.goto(`${consoleUrl}/workflows/runs/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('run-status').waitFor({ timeout: 60_000 });
        named.push((await page.getByText(PERSONS[i].name).count()) > 0);
      }
      check("3 each child's run page shows the person it was started for", named.length === 3 && named.every(Boolean), named);

      const trialId = await start(J, INTAKE, { notice: 'T', persons: PERSONS.slice(0, 1) }, { mode: 'test' });
      await settled(J, trialId);
      await until(async () => (await childrenOf(trialId)).length === 1, 30);
      const trial = await readRunPage(page, consoleUrl, trialId);
      const modes = (await childrenOf(trialId)).map((r) => r.mode);
      check("4 a test run's page lists its one child, and that child is a test run", trial.children.length === 1 && modes.join() === 'test', { listed: trial.children, modes });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
