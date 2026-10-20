// uc-073 chat widgets draw by shape on the dev widget page, ui layer: docs/usecases/console/widgets-by-shape.md.
// The page renders apps/console/src/lib/widgets/sample-parts.json (the parts uc-061 will replay through the chat stream) with
// the chat's renderers; its actions are recorded on the page instead of reaching a service.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const parts = JSON.parse(readFileSync(join(ROOT, 'apps/console/src/lib/widgets/sample-parts.json'), 'utf8'));
const DEFAULTS = { 'rows-monthly': 'table', 'rows-prefer-bar': 'bar', 'rows-people': 'table', 'rows-transactions': 'table', 'series-balance': 'line', 'record-account': 'fields', 'metric-open-cases': 'stat', 'form-callback': 'form', 'decision-hold': 'confirmation', 'steps-dispute': 'task' };

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/dev/widgets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('widget-log').waitFor({ timeout: 120_000 });
      await page.waitForTimeout(800);

      const sample = (id) => page.getByTestId(`sample-${id}`);
      const renderer = async (id) => sample(id).getByTestId('widget').getAttribute('data-renderer');
      const drawn = Object.fromEntries(await Promise.all(parts.map(async (p) => [p.id, await renderer(p.id)])));
      check('every sample draws with its shape default, and a valid hint picks bar over the table', JSON.stringify(drawn) === JSON.stringify(DEFAULTS), drawn);

      const switches = async (id) => sample(id).getByRole('radio').allInnerTexts();
      const monthly = await switches('rows-monthly');
      const people = await switches('rows-people');
      check('rows that can be charted offer table and three charts; rows that cannot offer no switch', monthly.join('|') === 'Table|Line chart|Bar chart|Area chart' && people.length === 0, { monthly, people });

      // 23 rows: the data table shows 10 and pages the rest.
      const tx = sample('rows-transactions');
      const firstPage = await tx.locator('tbody tr').count();
      const pageOne = (await tx.getByText('Page 1 of 3').count()) === 1;
      await tx.getByRole('button', { name: 'Go to next page' }).click();
      const pageTwo = (await tx.getByText('Page 2 of 3').count()) === 1 && (await tx.getByText('2026-10-11').count()) === 1;
      check('a long rows result shows 10 rows on the data table and pages the rest', firstPage === 10 && pageOne && pageTwo, { firstPage, pageOne, pageTwo });

      await sample('rows-monthly').getByRole('radio', { name: 'Line chart' }).click();
      await sample('series-balance').getByRole('radio', { name: 'Table' }).click();
      await page.waitForTimeout(500);
      const lineNow = (await renderer('rows-monthly')) === 'line' && (await sample('rows-monthly').locator('svg .recharts-line').count()) === 2;
      const tableNow = (await renderer('series-balance')) === 'table' && (await sample('series-balance').getByRole('columnheader').allInnerTexts()).join('|') === 'week|Chequing|Savings';
      check('the person switches rows to a line chart and a series to a table keyed by the hint x', lineNow && tableNow, { lineNow, tableNow });

      const log = async () => JSON.parse((await page.getByTestId('widget-log').locator('pre').innerText()).trim() || '[]');
      const form = sample('form-callback');
      const blocked = await form.getByRole('button', { name: 'Submit' }).isDisabled();
      await form.getByLabel('Phone').fill('416-555-0100');
      await form.getByRole('button', { name: 'Submit' }).click();
      await form.getByRole('button', { name: 'Sent' }).waitFor({ timeout: 10_000 }).catch(() => undefined);
      const sent = (await log()).at(-1);
      check('the form waits for its required field, then submits its values with the defaults', blocked && JSON.stringify(sent) === JSON.stringify({ widget: 'form-callback', values: { phone: '416-555-0100', slot: 'Morning', urgent: false } }), { blocked, sent });

      const decision = sample('decision-hold');
      await decision.getByRole('button', { name: 'Approve' }).click();
      await decision.getByText('Approved').waitFor({ timeout: 10_000 }).catch(() => undefined);
      const decided = (await log()).at(-1);
      const shown = (await decision.getByText('Approved').count()) === 1 && (await decision.getByRole('button', { name: 'Approve' }).count()) === 0;
      check('approving the decision sends its hold id and the card shows it approved', shown && JSON.stringify(decided) === JSON.stringify({ widget: 'decision-hold', holdId: 'hold_demo_1', approved: true }), { shown, decided });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
