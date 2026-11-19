// uc-756, ui layer: docs/usecases/agents-service/a-shared-form-filled-in-signed.md. A person with the shared link, signed
// out, fills the hosted form and gets the thank-you; the run reads the account, searches the knowledge source and waits;
// Maya approves the hold in Human Tasks; the hold reaches the mock bank once and the run finishes held with a case.
// Platform sign-in, a workflow worker, the fake bank on https; no model call.
import { AGENTS_PORT, TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, as, decideInConsole, saveAndPublish, settled, until, writeApprovalsOn } from '../../lib/workflow_ui.mjs';

const NADIA = 'n.petrov@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 7);
const READ = `get_account_${RUN}`;
const WRITE = `freeze_account_${RUN}`;
const WF = `uc756_form_${RUN}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const call = async (method, url, headers, body) => {
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};
const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, name: id, parameters });
const wire = (from, port, to) => ({ from: { node: from, port }, to: { node: to, port: 'in' } });

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    await writeApprovalsOn();
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-756' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-756' });
    const J = await as(JAMES);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Accounts ${RUN}`, name: `accounts-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    const url = `https://${stack.bank.host}/v1/accounts/{accountId}`;
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: READ, description: 'Read an account', access: 'read', method: 'GET', url });
    const added = await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: WRITE, description: 'Freeze an account', access: 'write', method: 'POST', url: `${url}/holds` });
    const opId = added.data?.operations?.find((o) => o.name === WRITE)?.id;
    await call('PATCH', `${tools}/v1/tool-modules/${moduleId}/operations/${opId}`, J, { approvers: 1, requiresApproval: true });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-756' });
    await approveToolReview(moduleId, await as(NADIA, 'team_security'), J);
    await until(async () => ((await call('GET', `${agents}/v1/tools/options?search=${WRITE}`, J)).data?.data ?? []).some((o) => o.id === WRITE), 60);

    const schema = {
      type: 'object',
      title: 'Hold my account',
      required: ['accountId', 'question'],
      properties: { accountId: { type: 'string', title: 'Account number' }, question: { type: 'string', title: 'What do you need to know first' } },
    };
    const live = await saveAndPublish(J, {
      schemaVersion: 2,
      id: WF,
      name: `Hold an account ${RUN}`,
      nodes: [
        node('start', 'ops.trigger.request', { inputSchema: schema }),
        node('read', 'ops.action.tool', { operation: READ, input: { accountId: '$.input.accountId' } }),
        node('search', 'ops.ai.knowledge', { query: '$.input.question', kbIds: ['kb_people'], limit: 3 }),
        node('review', 'ops.flow.humanReview', { title: 'Hold {$.input.accountId}?', approves: 'freeze' }),
        node('freeze', 'ops.action.tool', { operation: WRITE, approvedBy: 'review', input: { accountId: '$.input.accountId' } }),
        node('open', 'ops.action.openCase', { subject: 'Hold on {$.input.accountId}', priority: 'normal', caseType: 'complaint', fields: { complaint: '$.input.question' } }),
        node('done', 'ops.flow.end', { outcome: 'held' }),
        node('declined', 'ops.flow.end', { outcome: 'declined' }),
        node('failed', 'ops.flow.end', { outcome: 'failed', result: 'failed' }),
      ],
      connections: [
        wire('start', 'payload', 'read'), wire('read', 'ok', 'search'), wire('read', 'error', 'failed'), wire('read', 'refused', 'failed'),
        wire('search', 'found', 'review'), wire('search', 'notFound', 'failed'),
        wire('review', 'approve', 'freeze'), wire('review', 'reject', 'declined'),
        wire('freeze', 'ok', 'open'), wire('freeze', 'refused', 'failed'), wire('freeze', 'error', 'failed'),
        wire('open', 'opened', 'done'), wire('open', 'error', 'failed'),
      ],
    });
    check('setup: the workflow saves and goes live', live.live, { saved: live.saved.status, asked: live.asked.status });
    const shared = await call('POST', `${agents}/v1/workflows/${WF}/forms`, J, { mode: 'link', expiresInDays: 7, dailyCap: 20, title: 'Hold my account', afterText: 'Thanks, we have your request.' });
    const form = shared.data;
    check('setup: the workflow is shared as a form with a link', shared.status === 201 && Boolean(form?.url), shared.status);
    const ran = async (name) => ((await call('GET', `${tools}/v1/executions?tool=${name}`, J)).data?.data ?? []).filter((r) => r.status === 'ok');

    const browser = await chromium.launch();
    const errors = [];
    try {
      // Signed out: a fresh context with no session, as a bank customer opens the link.
      const outside = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      outside.setDefaultTimeout(30_000);
      outside.on('pageerror', (e) => errors.push(e.message));
      const target = new URL(form.url, stack.embedUrl);
      await outside.goto(`${stack.embedUrl}${target.pathname}${target.search}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await outside.getByTestId('hosted-form').waitFor({ timeout: 60_000 });
      await outside.getByLabel('Account number').fill('CHQ-2219');
      await outside.getByLabel('What do you need to know first').fill('What is the daily wire limit for a personal account?');
      await outside.getByTestId('hosted-form-send').click();
      const thanks = await outside.getByTestId('hosted-form-thanks').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('1 a signed-out person fills the shared form and gets the thank-you', thanks, outside.url());

      const started = await until(async () => {
        const rows = (await call('GET', `${agents}/v1/runs?workflowId=${WF}&pageSize=20`, J)).data?.data ?? [];
        return rows.find((r) => String(r.createdBy).startsWith('trigger:form:'));
      }, 60);
      check('2 the form started a run in the team', Boolean(started), started);
      const waiting = started ? await settled(J, started.id, { orWaiting: true }) : undefined;
      const steps = Object.fromEntries((waiting?.steps ?? []).map((s) => [s.nodeId, s]));
      // Non-vacuous: nothing has reached the bank while the review waits, so the one hold below is the approval's doing.
      check('3 the run read the account and searched the knowledge source, then waits for a person with no hold made', waiting?.status === 'waiting' && Boolean(steps.read) && Boolean(steps.search) && (await ran(WRITE)).length === 0, { status: waiting?.status, steps: Object.keys(steps) });

      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      const decided = await decideInConsole(maya, consoleUrl, waiting);
      const done = await settled(J, started.id);
      const caseId = done?.steps?.find((s) => s.nodeId === 'open')?.output?.caseId;
      const rows = await ran(WRITE);
      check('4 Maya approves in Human Tasks; the hold runs once and the run finishes held with a case', decided === 200 && rows.length === 1 && done?.outcome === 'held' && Boolean(caseId), { decided, holds: rows.length, outcome: done?.outcome, caseId });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true }, embed: true },
);

finish();
