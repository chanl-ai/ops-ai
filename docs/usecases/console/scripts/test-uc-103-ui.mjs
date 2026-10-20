// uc-103 a builder edits a widget with forms, ui layer: docs/usecases/console/widget-edited-with-forms.md. Headless
// Chromium against the console on agents-service. James adds a data field, gives it a sample value, lays a caption out
// from it, and saves; the saved template binds the caption to the field and keeps the limits the JSON had.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all', 'Content-Type': 'application/json' };
const TAG = Math.random().toString(36).slice(2, 6);
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(async (consoleUrl) => {
  // A draft widget with a length limit and additionalProperties false, set in JSON; the form must keep both.
  const made = await fetch(`${agents}/v1/widgets`, {
    method: 'POST',
    headers: TEAM,
    body: JSON.stringify({
      name: `Case card ${TAG}`,
      useWhen: 'Show one dispute case.',
      tree: { type: 'card', title: { $bind: '/title' }, children: [{ type: 'text', text: { $bind: '/summary' } }] },
      dataSchema: { type: 'object', additionalProperties: false, required: ['title'], properties: { title: { type: 'string', maxLength: 80 }, summary: { type: 'string' } } },
      sample: { title: 'Dispute 4471', summary: 'Card charge disputed' },
    }),
  });
  const created = (await made.json()).data;
  if (made.status !== 201) throw new Error(`setup: creating the widget answered ${made.status}: ${JSON.stringify(created).slice(0, 300)}`);
  const id = created.widgetId;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`${consoleUrl}/widgets/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const preview = page.getByTestId('widget-preview');
    await page.getByTestId('layout-editor').waitFor({ timeout: 120_000 });
    check('the editor opens on forms, with no raw JSON box, and previews the sample', (await page.locator('#widget-tree').count()) === 0 && (await preview.getByText('Dispute 4471').count()) > 0);

    // A new data field and its sample value.
    await page.getByTestId('input-add-field').click();
    await page.getByLabel('Field 3 name').fill('region');
    await page.locator('#sample-region').fill('North');

    // A caption in the card, taken from the new field.
    await page.getByRole('button', { name: 'Add a block to Top block' }).click();
    await page.getByRole('menuitem', { name: 'Caption', exact: true }).click();
    const caption = page.locator('[data-testid="layout-block"][data-path="1"]');
    await caption.getByRole('combobox', { name: 'Text source' }).click();
    await page.getByRole('option', { name: 'From region' }).click();
    const shown = await preview.getByText('North').waitFor({ timeout: 15_000 }).then(() => true, () => false);
    check('the caption bound to the new field shows its sample value in the preview', shown);

    const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/widgets/${id}`), { timeout: 30_000 }));
    await page.getByTestId('save-widget').click();
    const status = (await saved)?.status();
    const after = (await (await fetch(`${agents}/v1/widgets/${id}`, { headers: TEAM })).json()).data;
    const props = after?.dataSchema?.properties ?? {};
    const stored = {
      status,
      caption: after?.tree?.children?.[1],
      region: props.region,
      titleLimit: props.title?.maxLength,
      closed: after?.dataSchema?.additionalProperties,
      sample: after?.sample?.region,
    };
    check(
      'the saved template binds the caption to the field, adds the field, keeps the JSON limits, and stores the sample',
      status === 200 && JSON.stringify(stored.caption) === JSON.stringify({ type: 'caption', text: { $bind: '/region' } }) && stored.region?.type === 'string' && stored.titleLimit === 80 && stored.closed === false && stored.sample === 'North',
      stored,
    );

    // JSON stays as the advanced view, holding the same template.
    await page.getByTestId('widget-mode-json').click();
    const json = await page.locator('#widget-tree').inputValue({ timeout: 15_000 }).catch(() => '');
    check('JSON (advanced) shows the same template', json.includes('"$bind": "/region"'), json.slice(0, 300));

    // A save the service refuses shows as an alert on the page.
    await page.locator('#widget-tree').fill('{"type":"nope"}');
    await page.getByTestId('save-widget').click();
    const refusal = page.getByTestId('widget-save-error');
    const refused = await refusal.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a refused save shows an alert on the page', refused && (await refusal.getAttribute('role')) === 'alert' && (await refusal.evaluate((el) => el.tagName)) === 'DIV', refused ? await refusal.innerText() : 'no alert');

    // Retire asks for a reason on the shared confirm and holds the button until there is one.
    await page.goto(`${consoleUrl}/widgets/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('retire-widget').click({ timeout: 120_000 });
    const confirm = page.getByRole('dialog').getByRole('button', { name: 'Retire widget' });
    const heldWithoutReason = await confirm.isDisabled();
    await page.locator('#retire-reason').fill('uc-103 is done with it');
    const retired = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/widgets/${id}/retire`), { timeout: 30_000 }));
    await confirm.click();
    const retireStatus = (await retired)?.status();
    const final = (await (await fetch(`${agents}/v1/widgets/${id}`, { headers: TEAM })).json()).data;
    check('retire waits for a reason, then retires the widget', heldWithoutReason && retireStatus === 200 && final?.status === 'deprecated', { heldWithoutReason, retireStatus, status: final?.status });

    // A widget id the service does not have says so, and is not an error page.
    await page.goto(`${consoleUrl}/widgets/no-such-widget-${TAG}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const missing = await page.getByText('Widget not found').waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('an unknown widget id says Widget not found', missing);

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
