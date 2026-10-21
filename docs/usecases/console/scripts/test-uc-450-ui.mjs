// uc-450, ui layer: docs/usecases/console/demo-team-shows-each-once.md. Signs in to a deployed console (STG_ORIGIN,
// STG_EMAIL, STG_PASSWORD from the environment) in the demo team (STG_TEAM) and checks, as a person sees them, that the
// Open cases view and the run picker show each record once and that Dispute Desk finds a seeded dispute's charge at the
// bank. Step c is one chat turn on the team's live model; UC450_ONLY=a,b leaves it out.
import { check, chromium, finish } from '@ops-ai/usecase-runner/harness';

const ORIGIN = process.env.STG_ORIGIN;
const TEAM = process.env.STG_TEAM;
const ONLY = process.env.UC450_ONLY?.split(',');
const SHOTS = process.env.UC450_SHOTS;
// A turn on a real model makes several model calls of a few seconds each.
const TURN = 180_000;

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.setDefaultTimeout(60_000);
const errors = [];
page.on('pageerror', (e) => errors.push(e.message.slice(0, 200)));

async function step(name, body) {
  if (ONLY && !ONLY.includes(name[0])) return;
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/uc450-${name[0]}.png`, fullPage: true }).catch(() => {});
}

/** How many times each text in `texts` appears among `labels`, and the texts that appear more than once. */
function counted(labels) {
  const n = new Map();
  for (const l of labels) n.set(l, (n.get(l) ?? 0) + 1);
  return { n: Object.fromEntries(n), twice: [...n].filter(([, c]) => c > 1).map(([l]) => l) };
}

try {
  await page.goto(`${ORIGIN}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(process.env.STG_EMAIL);
  await page.getByLabel('Password').fill(process.env.STG_PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 90_000 });
  // The console acts in the team the tab chose (sessionStorage `ops-team`, as the team switcher sets it).
  await page.evaluate((id) => sessionStorage.setItem('ops-team', id), TEAM);

  await step('a the Open cases view shows each case once', async () => {
    await page.goto(`${ORIGIN}/cases`, { waitUntil: 'domcontentloaded' });
    const rows = page.locator('main table tbody tr');
    await rows.first().waitFor();
    await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
    const subjects = await rows.evaluateAll((trs) => trs.map((tr) => (tr.querySelector('a')?.textContent ?? '').trim()).filter(Boolean));
    const { n, twice } = counted(subjects);
    const levy = subjects.filter((s) => s.startsWith('Levy notice:'));
    check('a the Open cases view shows each case once', subjects.length > 0 && twice.length === 0 && levy.length === 3, { rows: subjects.length, twice, n });
  });

  await step('b the run picker shows each workflow once', async () => {
    await page.goto(`${ORIGIN}/workflows`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Start run' }).click();
    await page.getByTestId('start-run-workflow').getByRole('button', { name: 'Choose a workflow' }).click();
    const options = page.getByRole('option');
    await options.first().waitFor();
    await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
    const labels = (await options.allInnerTexts()).map((t) => t.split('\n')[0].trim());
    const { n, twice } = counted(labels);
    const levy = labels.filter((l) => l.startsWith('Levy notice:'));
    check('b the run picker shows each workflow once', twice.length === 0 && levy.length === 2, { options: labels.length, twice, n });
    await page.keyboard.press('Escape');
  });

  await step('c Dispute Desk finds the Coastal Air charge on Marcus Bell\'s credit card', async () => {
    await page.goto(`${ORIGIN}/chat`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('combobox', { name: 'Agent' }).click({ timeout: 120_000 });
    await page.getByRole('option', { name: /^Dispute Desk/ }).click();
    const box = page.getByRole('textbox', { name: 'Message' });
    await box.fill('Marcus Bell (customer CUS-1001) says a Coastal Air charge of 1,240.00 CAD on his credit card is wrong. Find that charge.');
    const done = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: TURN });
    await box.press('Enter');
    // The reply streams; through the deployed proxy the response's end can arrive long after the reply has, so the
    // wait is bounded and the reply's text decides the step.
    const res = await done;
    await Promise.race([res.finished(), new Promise((r) => setTimeout(r, 30_000))]);
    await page.getByText('Thinking…').waitFor({ state: 'detached', timeout: TURN }).catch(() => undefined);
    await page.getByText(/VISA-|no (such|record|matching)|could ?n.t find/i).last().waitFor({ timeout: TURN }).catch(() => undefined);
    const text = (await page.locator('main').innerText()).replace(/\s+/g, ' ');
    const reply = text.slice(text.lastIndexOf('Find that charge.'));
    const found = /list_transactions/.test(reply) && /VISA-5521/.test(reply) && /1,?240/.test(reply) && /coastal air/i.test(reply);
    const denied = /no (such|record|matching)|could ?n.t find|did not find|not find/i.test(reply);
    check('c Dispute Desk finds the Coastal Air charge on Marcus Bell\'s credit card', found && !denied, { tail: reply.slice(-700) });
  });

  check('no page errors', errors.length === 0, errors.slice(0, 3));
} finally {
  await browser.close().catch(() => undefined);
}
finish();
