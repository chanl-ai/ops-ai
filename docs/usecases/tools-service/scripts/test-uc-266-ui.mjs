// uc-266 a workflow's write is checked against the team's sending policy before it goes out, ui layer:
// docs/usecases/tools-service/check-before-sending.md. The team's sending policy (no refunds promised) is saved; a run
// that promises a refund opens its case while the check is off. Priya turns Check before sending on in Govern ›
// Policies, and James's next run's page ends at Held with the reason on its step; an allowed case opens. The console has
// no page for the policy's text yet, so it is saved through tools-service. Platform sign-in, the fake model as judge.
import { MODELS_PORT, TOOLS_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, PRIYA, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const ID = `uc266_open_case_${Math.random().toString(36).slice(2, 6)}`;
const POLICY = 'Never promise a refund, or any money back, in a case or a reply.';
const end = (id) => ({ id, type: 'ops.flow.end', typeVersion: 1, parameters: { outcome: id } });
const FLOW = {
  schemaVersion: 2,
  id: ID,
  name: `Open a case (uc-266 ${ID.slice(-4)})`,
  nodes: [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, parameters: {} },
    { id: 'open', type: 'ops.action.tool', typeVersion: 1, parameters: { operation: 'open_case', input: { subject: '$.input.subject' } } },
    end('opened'),
    end('held'),
    end('failed'),
  ],
  connections: [
    ['start', 'payload', 'open'],
    ['open', 'ok', 'opened'],
    ['open', 'refused', 'held'],
    ['open', 'error', 'failed'],
  ].map(([f, p, t]) => ({ from: { node: f, port: p }, to: { node: t, port: 'in' } })),
};

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const P = await as(PRIYA);
    const made = await saveAndPublish(J, FLOW);
    if (!made.live) throw new Error(`setup: the workflow did not go live: ${made.saved.status} ${JSON.stringify(made.saved.data).slice(0, 300)}`);
    const policy = await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/send-policy`, { method: 'PUT', headers: P, body: JSON.stringify({ text: POLICY }) });
    if (policy.status !== 200) throw new Error(`setup: saving the sending policy answered ${policy.status}: ${(await policy.text()).slice(0, 300)}`);
    const runOf = async (subject) => {
      const id = await start(J, ID, { subject }, { mode: 'live' });
      await settled(J, id);
      return id;
    };

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const off = await readRunPage(page, consoleUrl, await runOf('Refund promised for the double charge'));
      check('2 with Check before sending off, a run that promises a refund opens its case', off.outcome === 'opened', off.outcome);

      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const turned = await turnOnPolicy(priya, consoleUrl, 'checkBeforeSend');
      check('3 Priya turns Check before sending on in Policies (200)', turned === 200, turned);

      const held = await readRunPage(page, consoleUrl, await runOf('Refund promised for the double charge again'));
      const step = await readStepSheet(page, 'open');
      check(
        '4 the next refund promise ends at Held, and its step says why it was refused',
        held.outcome === 'held' && step.port === 'refused' && /promises a refund/.test(JSON.stringify(step.output)),
        { outcome: held.outcome, port: step.port, output: step.output },
      );
      const fine = await readRunPage(page, consoleUrl, await runOf('Card stopped working abroad'));
      check('5 a case the policy allows opens at once', fine.outcome === 'opened', fine.outcome);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { ...AI_STACK, tools: { gateway: true, env: { OPS_MODELS_URL: `http://127.0.0.1:${MODELS_PORT}`, OPS_MODELS_KEY: 'mk_dev_tools_check' } } },
);

finish();
