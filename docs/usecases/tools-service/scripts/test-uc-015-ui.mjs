// uc-015 tool module details page, ui layer: docs/usecases/tools-service/tool-module-details-page.md. Headless
// Chromium against the console; the module and its operations come from tools-service, run against the core-banking fake.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { allowBank } from '../../lib/connection_ui.mjs';

const MODULE = 'mod_core_banking';

// The core banking module is the Platform team's in tools-service's seed, so its admin opens it; Security allows the
// fake bank's host, as on the shared stack.
await withUiStack(async (consoleUrl, stack) => {
  await allowBank(stack.bank);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // An operation is tested on its own workbench page: the module page has no side panel, and a row opens it.
    await page.goto(`${consoleUrl}/tools/${MODULE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const row = page.getByRole('row', { name: /get_loan_account/ });
    await row.waitFor({ timeout: 120_000 });
    const sidePanel = await page.getByTestId('module-test-panel').count();
    await row.click();
    await page.waitForURL(`**/tools/${MODULE}/operations/get_loan_account`, { timeout: 60_000 });
    const panel = page.getByTestId('module-test-panel');
    await panel.waitFor({ timeout: 120_000 });
    const [panelBox, benchBox] = [await panel.boundingBox(), await page.getByTestId('tool-workbench').boundingBox()];
    check('a row opens the operation with its run beside its definition', sidePanel === 0 && !!panelBox && !!benchBox && panelBox.x > benchBox.x + 400, { sidePanel, panelBox, benchBox });
    check('there is no Test console tab', (await page.getByRole('tab', { name: 'Test console' }).count()) === 0);

    // Run as offers the module's owner and nothing else: no workflow's "sample values" context.
    await panel.getByLabel('Run as').click();
    const options = await page.getByRole('option').allInnerTexts();
    await page.keyboard.press('Escape');
    check('Run as offers the owner only, with no sample-values context', options.length === 1 && /^Owner/.test(options[0]) && !options.some((o) => /sample values/i.test(o)), options);

    // Allow: get_loan_account run as the owner, who needs no workflow approval; the account is typed, not bound.
    await panel.getByLabel('loanAccountId').fill('LN-0048213');
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const allowed = await panel.getByText('Allowed').waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('an approved operation run against the stub is allowed', allowed && (await panel.getByText('HTTP 200').count()) === 1);

    // Non-vacuous pair: transfer_funds is hidden in this module, so the gateway refuses a valid input for it.
    await page.goto(`${consoleUrl}/tools/${MODULE}/operations/transfer_funds`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await panel.waitFor({ timeout: 120_000 });
    await panel.getByLabel('fromAccount').fill('CHQ-0001');
    await panel.getByLabel('toAccount').fill('CHQ-1182');
    await panel.getByLabel('amount').fill('100');
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const denied = await panel.getByText('The operation is hidden in this module.', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a hidden operation is denied with its reason', denied && (await panel.getByText('HTTP 403').count()) === 1, (await panel.innerText()).slice(-300));

    await page.goto(`${consoleUrl}/tools/${MODULE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('tab', { name: 'Activity' }).click({ timeout: 120_000 });
    // The module's operations answer from the stub, and a test run through the panel is logged nowhere, so the tab
    // lists no calls here; the caller and "via" cells are checked on real gateway calls in uc-086.
    await page.getByText('No calls yet').waitFor({ timeout: 60_000 }).catch(() => {});
    check('the Activity tab lists executions, none yet for stub test runs', (await page.getByText('Executions', { exact: true }).count()) === 1 && (await page.getByText('No calls yet').count()) === 1);

    await page.setViewportSize({ width: 375, height: 800 });
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check('no sideways scroll at phone width', overflow <= 0, `${overflow}px wider than the viewport`);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, { tools: { bank: 'core' }, signedInAs: 'platform' });

finish();
