// uc-015 tool module details page, ui layer: docs/usecases/tools-service/tool-module-details-page.md. Headless
// Chromium against the console; tool modules come from the mock until tools-service serves /v1/tool-modules.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const MODULE = 'mod_core_banking';

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto(`${consoleUrl}/tools/${MODULE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const panel = page.getByTestId('module-test-panel');
    await panel.waitFor({ timeout: 120_000 });
    const ops = page.getByRole('tab', { name: /Operations/ });
    const [panelBox, opsBox] = [await panel.boundingBox(), await ops.boundingBox()];
    check('the test panel sits beside the Operations tab', !!panelBox && !!opsBox && panelBox.x > opsBox.x + 400, { panelBox, opsBox });
    check('there is no Test console tab', (await page.getByRole('tab', { name: 'Test console' }).count()) === 0);

    // Allow: get_loan_account run as the lending inbox case, which is approved for it; the case binds the account.
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const allowed = await panel.getByText('Allowed').waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('an approved operation run against the stub is allowed', allowed && (await panel.getByText('HTTP 200').count()) === 1);

    // Non-vacuous pair: transfer_funds is hidden in this module, so the gateway refuses a valid input for it.
    await panel.getByRole('combobox', { name: 'Operation' }).click();
    await page.getByRole('option', { name: /transfer_funds/ }).click();
    await panel.getByLabel('toAccount').fill('CHQ-1182');
    await panel.getByLabel('amount').fill('100');
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const denied = await panel.getByText('The operation is hidden in this module.', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a hidden operation is denied with its reason', denied && (await panel.getByText('HTTP 403').count()) === 1, (await panel.innerText()).slice(-300));

    await page.getByRole('tab', { name: 'Activity' }).click();
    const firstRow = page.locator('[data-testid^="execution-row-"]').first();
    const listed = await firstRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    const caller = listed ? (await firstRow.getByTestId('caller-cell').innerText()).split('\n') : [];
    check('executions list a caller and who it acted via', caller.length === 2 && caller[0].length > 0 && caller[1].startsWith('via '), caller);

    await firstRow.getByTestId('caller-cell').click();
    const sheet = page.getByTestId('tool-call-sheet');
    const opened = await sheet.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a row opens the call with its workflow', opened && (await sheet.getByText(caller[0] ?? '-', { exact: true }).count()) > 0, opened ? 'workflow not in the sheet' : 'sheet not open');
    await page.keyboard.press('Escape');

    await page.setViewportSize({ width: 375, height: 800 });
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check('no sideways scroll at phone width', overflow <= 0, `${overflow}px wider than the viewport`);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
