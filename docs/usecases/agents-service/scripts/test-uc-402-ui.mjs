// uc-402 a workflow waits for its children and uses their results, ui layer:
// docs/usecases/agents-service/wait-for-children.md. James saves the api script's child and parent and starts the
// parent with three files, one the child cannot read. The parent's run page shows it finished with the Run workflow
// step once, by done, and that step's sheet lists each child's outcome in item order with the counts. Platform
// sign-in, no model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, as, readRunPage, readStepSheet, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const CHILD_ID = `uc402_read_one_${TAG}`;
const CHILD = `
schemaVersion: 2
id: ${CHILD_ID}
name: Read one attachment (uc-402)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Attachment}
  - id: readable
    type: ops.flow.if
    typeVersion: 1
    name: Readable?
    parameters: {conditions: [{left: "$.input.name", op: eq, right: "scan.pdf"}]}
  - {id: unreadable, type: ops.flow.end, typeVersion: 1, name: Unreadable, parameters: {outcome: unreadable, result: failed}}
  - {id: read, type: ops.flow.end, typeVersion: 1, name: Read, parameters: {outcome: read, output: {file: "$.input.name"}}}
connections:
  - {from: {node: start, port: payload}, to: {node: readable, port: in}}
  - {from: {node: readable, port: "true"}, to: {node: unreadable, port: in}}
  - {from: {node: readable, port: "false"}, to: {node: read, port: in}}
`;
const PARENT = `
schemaVersion: 2
id: uc402_letter_${TAG}
name: Read every attachment (uc-402)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Letter}
  - id: each
    type: ops.action.workflow
    typeVersion: 1
    name: Read each attachment
    parameters: {workflow: ${CHILD_ID}, forEach: "$.input.files", input: {name: "$.item.name"}, wait: true, batchSize: 2}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: read, output: "$.nodes.each.out"}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: failed, result: failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: each, port: in}}
  - {from: {node: each, port: done}, to: {node: done, port: in}}
  - {from: {node: each, port: error}, to: {node: failed, port: in}}
`;
const FILES = { files: [{ name: 'levy.pdf' }, { name: 'scan.pdf' }, { name: 'id.pdf' }] };

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const child = await saveAndPublish(J, CHILD);
    const parent = await saveAndPublish(J, PARENT);
    check('0 the child and parent workflows save and go live', child.live && parent.live, [child.asked.data?.status, parent.asked.data?.status]);
    await stack.startWorker();
    const runId = await start(J, parent.id, FILES);
    const run = await settled(J, runId, { seconds: 120 });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const shown = await readRunPage(page, consoleUrl, runId);
      check(
        '1 the parent finishes after its children: its page shows the Run workflow step once, then Done',
        run?.status === 'succeeded' && shown.outcome === 'read' && shown.count('each') === 1 && shown.count('done') === 1,
        { status: shown.status, outcome: shown.outcome, steps: shown.steps.map((s) => s.nodeId) },
      );
      const sheet = await readStepSheet(page, 'each');
      const children = sheet.output?.children ?? [];
      check(
        "2 the step's sheet lists each child's outcome in item order, the unreadable one too, with the counts",
        sheet.port === 'done' &&
          JSON.stringify(children.map((c) => [c.index, c.outcome])) === JSON.stringify([[0, 'read'], [1, 'unreadable'], [2, 'read']]) &&
          children[0]?.output?.file === 'levy.pdf' &&
          JSON.stringify(sheet.output?.counts) === JSON.stringify({ read: 2, unreadable: 1 }),
        sheet,
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
