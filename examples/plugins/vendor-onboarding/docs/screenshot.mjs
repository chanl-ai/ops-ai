// A screenshot of a finished vendor-onboarding run's page in the console, signed in as the approver who decided it.
//
//   node examples/plugins/vendor-onboarding/docs/screenshot.mjs <runId> [consoleUrl] [adminEnvFile]
//
// Defaults: the isolated stack's console (http://localhost:4016) and .run/isolated/dev-admin.env, whose
// OPS_DEMO_PASSWORD is the sample team's people's password. Writes run-finished.png beside this file.
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium, consoleSignIn } from '@ops-ai/usecase-runner/harness';

const here = dirname(fileURLToPath(import.meta.url));
const [runId, consoleUrl = 'http://localhost:4016', envFile = resolve(here, '../../../../.run/isolated/dev-admin.env')] = process.argv.slice(2);
if (!runId) throw new Error('usage: screenshot.mjs <runId> [consoleUrl] [adminEnvFile]');
const password = readFileSync(envFile, 'utf8').match(/^OPS_DEMO_PASSWORD=(.+)$/m)?.[1]?.trim();
if (!password) throw new Error(`${envFile} has no OPS_DEMO_PASSWORD; run make sample-team first`);

const errors = [];
const browser = await chromium.launch();
try {
  const page = await consoleSignIn(browser, consoleUrl, 'riley.chen@harborpine.example', password, errors);
  await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByText('Onboarded').first().waitFor({ timeout: 60_000 });
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  const out = join(here, 'run-finished.png');
  await page.screenshot({ path: out, fullPage: true });
  console.log(`saved ${out}${errors.length ? `; page errors: ${errors.join(' | ')}` : ''}`);
} finally {
  await browser.close();
}
