// What the sign-in ui scripts share (c-553): typing a password on the console's sign-in page, and resetting it the way
// a person does, by asking on Forgot password and following the mailed link. Mail is platform-service's fake mailer,
// which writes each message to the stack's mail folder (withUiStack with `signIn: true`).
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/** Types `email` and `password` on the sign-in page and returns where the page went and what it says. */
export async function tryPassword(page, consoleUrl, email, password) {
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/auth\/sign-in$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  const res = await answered;
  const signedIn = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15_000 }).then(() => true, () => false);
  return { status: res?.status() ?? 0, signedIn, says: (await page.locator('main, body').first().innerText().catch(() => '')).replace(/\s+/g, ' ') };
}

/** The reset links mailed to `email`, oldest first. */
export function resetLinks(mailDir, email) {
  return readdirSync(mailDir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(readFileSync(join(mailDir, f), 'utf8')))
    .filter((m) => (m.to ?? []).includes(email))
    .map((m) => /\/reset-password\/(prt_[A-Za-z0-9_-]+)/.exec(m.body ?? '')?.[0])
    .filter(Boolean);
}

/** Asks for a reset on Forgot password as a signed-out person; returns whether the page says the mail is on its way. */
export async function askForReset(page, consoleUrl, email) {
  await page.goto(`${consoleUrl}/forgot-password`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Work email').press('Enter');
  return page.getByTestId('forgot-sent').waitFor({ timeout: 30_000 }).then(() => true, () => false);
}

/** Opens a mailed reset link and sets `password`; returns whether the page says it is done. */
export async function setPasswordFromLink(page, consoleUrl, link, password) {
  await page.goto(`${consoleUrl}${link}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('New password').fill(password);
  await page.getByLabel('Confirm password').fill(password);
  await page.getByLabel('Confirm password').press('Enter');
  return page.getByTestId('reset-done').waitFor({ timeout: 30_000 }).then(() => true, () => false);
}
