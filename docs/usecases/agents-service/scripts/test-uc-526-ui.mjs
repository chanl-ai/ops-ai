// uc-526 another team's records answer not found, ui layer: docs/usecases/agents-service/another-team-s-records-answer-not.md.
// Priya, in Operations, makes a case, a workflow and a run, and opens each one's page. Sam, signed in to Security, opens
// the same addresses: each page says not found and names neither Operations nor team_ops. Platform sign-in; no model.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, PRIYA, agents, as, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';

const SAM = 's.adeyemi@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const ID = `uc526_note_${TAG}`;
const SUBJECT = `Card dispute (uc-526 ${TAG})`;
const DEFINITION = `
schemaVersion: 2
id: ${ID}
name: Note (uc-526 ${TAG})
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: End}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
`;

/** What a record's page shows once it has loaded: its own content or the not-found state. */
async function shown(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(() => /Not found|couldn.t find|This (case|run|workflow)/i.test(document.querySelector('main')?.innerText ?? '') || document.querySelector('[data-testid="run-status"],[data-testid="case-whats-left"],[data-testid="definition-stage"]'), null, { timeout: 60_000 }).catch(() => undefined);
  return (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ');
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const P = await as(PRIYA);
    const caseRes = await fetch(`${agents}/v1/cases`, { method: 'POST', headers: P, body: JSON.stringify({ subject: SUBJECT, priority: 'high', customerId: 'C-526', customerName: 'Ann' }) });
    const caseId = (await caseRes.json()).data?.id;
    const made = await saveAndPublish(P, DEFINITION);
    const runId = made.live ? await start(P, ID, {}) : undefined;
    if (runId) await settled(P, runId);
    if (!caseId || !runId) throw new Error(`setup: case ${caseRes.status} ${caseId}, workflow live ${made.live}, run ${runId}`);
    const pages = [
      ['the case', `${consoleUrl}/cases/${caseId}`, SUBJECT],
      ['the workflow', `${consoleUrl}/workflows/definitions/${ID}`, `Note (uc-526 ${TAG})`],
      ['the run', `${consoleUrl}/workflows/runs/${runId}`, `Note (uc-526 ${TAG})`],
    ];

    const browser = await chromium.launch();
    const errors = [];
    try {
      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const sam = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      for (const [what, url, name] of pages) {
        const hers = await shown(priya, url);
        check(`3 Priya opens ${what} in Operations and sees it`, hers.includes(name) && !/Not found/i.test(hers), hers.slice(0, 200));
        const his = await shown(sam, url);
        // The page header names the team Sam is in; the not-found answer itself must name no other team.
        const body = his.replace(/^.*?(Not found|We couldn.t find)/i, '$1');
        check(`4 Sam, in Security, opens ${what} and is told it is not found`, /Not found|couldn.t find/i.test(his) && !his.includes(name), his.slice(0, 300));
        check(`5 the not-found page for ${what} names neither Operations nor team_ops`, !/Operations|team_ops/.test(body), body.slice(0, 300));
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
