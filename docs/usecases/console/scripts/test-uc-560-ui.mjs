// uc-560 screens open from saved data, ui layer: docs/usecases/console/screen-speed.md. Every agents-service read is
// held back for a few seconds on each reload, so a screen that shows its rows before then shows what the browser saved.
// James's workflow list opens from saved data; nothing about his session, his permissions or Human Tasks is saved;
// a cache from another app version is ignored; sign-out, a sign-out in another tab and a team switch each leave nothing
// saved. Platform sign-in, no model call.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, as, saveAndPublish } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `Saved screen ${TAG}`;
// A held read answers after HOLD_MS; a screen counts as drawn from saved data when its row shows before EARLY_MS,
// which leaves a loaded host time to start the page.
const HOLD_MS = 20_000;
const EARLY_MS = 12_000;
const DEFINITION = {
  schemaVersion: 2,
  id: `uc560_saved_${TAG}`,
  name: NAME,
  nodes: [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, parameters: {} },
    { id: 'end_done', type: 'ops.flow.end', typeVersion: 1, parameters: { outcome: 'done' } },
  ],
  connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'end_done', port: 'in' } }],
};

/** Holds every GET to agents-service for HOLD_MS, so only saved data can draw a screen before then. */
async function holdAgentReads(page) {
  await page.route(
    (url) => url.port === String(AGENTS_PORT),
    async (route) => {
      if (route.request().method() === 'GET') await new Promise((r) => setTimeout(r, HOLD_MS));
      await route.continue().catch(() => undefined);
    },
  );
}

/** Every saved query, as [key, value] rows of the console's query store in IndexedDB (none when it does not exist). */
function saved(page) {
  return within(5_000, page.evaluate(
    () =>
      new Promise((done) => {
        const open = indexedDB.open('ops-console');
        open.onupgradeneeded = () => open.transaction?.abort();
        open.onerror = () => done([]);
        open.onsuccess = () => {
          const db = open.result;
          if (!db.objectStoreNames.contains('queries')) return (db.close(), done([]));
          const rows = [];
          const cursor = db.transaction('queries').objectStore('queries').openCursor();
          cursor.onsuccess = () => {
            const c = cursor.result;
            if (!c) return (db.close(), done(rows));
            rows.push([String(c.key), c.value]);
            c.continue();
          };
          cursor.onerror = () => (db.close(), done(rows));
        };
      }),
  ), []);
}

/** `promise`, or `fallback` once `ms` pass. */
const within = (ms, promise, fallback) => Promise.race([promise, new Promise((r) => setTimeout(() => r(fallback), ms))]);

const savedKeys = (rows) => rows.flatMap(([, v]) => (v?.clientState?.queries ?? []).map((q) => JSON.stringify(q.queryKey)));

/** Reloads /workflows with agents-service held back; true when the workflow's row shows within `withinMs`. */
let lastDrawn = '';
async function shownEarly(page, consoleUrl, withinMs = EARLY_MS) {
  await holdAgentReads(page);
  await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const early = await page.getByText(NAME).first().waitFor({ timeout: withinMs }).then(() => true, () => false);
  // What the page drew instead, while agents-service is still held.
  lastDrawn = early ? '' : (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 200);
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  return early;
}

/** Signs out from the sidebar's user menu, as a person does. */
async function signOut(page, email) {
  await page.locator('[data-sidebar="menu-button"]').filter({ hasText: email }).first().click();
  await page.getByTestId('sign-out').click();
}

await withUiStack(
  async (consoleUrl) => {
    const J = await as(JAMES);
    const made = await saveAndPublish(J, DEFINITION);
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const listed = await page.getByText(NAME).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      // He reads the list a moment, as a person does; saves are batched a second after the last read lands.
      await page.waitForTimeout(2_000);
      await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.waitForTimeout(3_000);
      check('6 James saves a workflow and sees it in the list', made.saved.status === 201 && listed, { saved: made.saved.status, listed });

      const early = await shownEarly(page, consoleUrl);
      const keys = savedKeys(await saved(page));
      check('6 on reload the list shows his workflow from saved data before agents-service answers', early, { workflowKeys: keys.filter((k) => k.startsWith('["workflows"')), drawn: lastDrawn });
      const leaked = keys.filter((k) => /^\[\s*"(me|teams|sign-in-policy|reviews)"/.test(k) || k.includes('preview-link') || !k.includes('{"team":'));
      check('7 nothing about his session, his permissions or Human Tasks is saved, and every saved key names his team', keys.length > 0 && leaked.length === 0, { leaked, keys });

      // A cache another app version wrote is ignored: the same rows under another buster, written once the page's own
      // saves have settled.
      await page.waitForTimeout(3_000);
      const rows = await saved(page);
      if (rows.length) {
        await page.evaluate((stale) => new Promise((done) => {
          const open = indexedDB.open('ops-console');
          open.onsuccess = () => {
            try {
              const tx = open.result.transaction('queries', 'readwrite');
              for (const [key, value] of stale) tx.objectStore('queries').put({ ...value, buster: 'an-older-version' }, key);
              tx.oncomplete = tx.onerror = tx.onabort = () => (open.result.close(), done());
            } catch {
              open.result.close();
              done();
            }
          };
          open.onerror = () => done();
        }), rows);
      }
      const afterVersion = await shownEarly(page, consoleUrl);
      check('8 a cache saved by another app version is not shown', rows.length > 0 && !afterVersion, { rows: rows.length, shown: afterVersion });

      // Sign-out leaves nothing saved, and the next sign-in starts empty.
      await shownEarly(page, consoleUrl, 60_000);
      await page.waitForTimeout(2_000);
      const beforeSignOut = (await saved(page)).length;
      await signOut(page, JAMES);
      await page.waitForURL((u) => u.pathname.startsWith('/login'), { timeout: 30_000 });
      const afterSignOut = (await saved(page)).length;
      // Signing in again in the same browser, where the saved copy would still be.
      await page.getByLabel('Work email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByTestId('login-submit').click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const shownAfterSignOut = await shownEarly(page, consoleUrl);
      check('9 after sign-out nothing is saved, and signing in again shows nothing early', beforeSignOut > 0 && afterSignOut === 0 && !shownAfterSignOut, { beforeSignOut, afterSignOut, shownAfterSignOut });

      // A sign-out in another tab wipes what this tab saved, and this tab saves nothing after it.
      const tab = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await tab.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await tab.getByText(NAME).first().waitFor({ timeout: 60_000 });
      await tab.waitForTimeout(2_000);
      const before = (await saved(tab)).length;
      const second = await tab.context().newPage();
      await second.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await second.getByText(NAME).first().waitFor({ timeout: 60_000 });
      await signOut(second, JAMES);
      await tab.waitForTimeout(3_000);
      const afterOtherTab = (await saved(tab)).length;
      check('10 a sign-out in another tab leaves nothing saved', before > 0 && afterOtherTab === 0, { before, afterOtherTab });
      await tab.context().close();

      // A team switch: Wanjiru, the workspace admin, makes a team with Priya its admin, so Priya holds two; switching
      // leaves nothing of team_ops saved.
      const P = await as(PRIYA);
      const W = await as('w.kamau@harborpine.example');
      const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
      const madeTeam = await fetch(`${platform}/v1/settings/teams`, { method: 'POST', headers: W, body: JSON.stringify({ name: `Saved screen team ${TAG}`, admin: PRIYA }) });
      const teams = (await (await fetch(`${platform}/v1/teams`, { headers: P })).json()).data ?? [];
      const other = teams.findIndex((t) => t.id !== 'team_ops');
      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await priya.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await priya.getByText(NAME).first().waitFor({ timeout: 60_000 });
      await priya.waitForTimeout(2_000);
      const opsSaved = savedKeys(await saved(priya)).filter((k) => k.includes('"team_ops"')).length;
      await priya.keyboard.press(`Control+${other + 1}`);
      await priya.waitForTimeout(3_000);
      const opsAfter = savedKeys(await saved(priya)).filter((k) => k.includes('"team_ops"')).length;
      check('11 a team switch leaves nothing of the old team saved', madeTeam.status === 201 && other >= 0 && opsSaved > 0 && opsAfter === 0, { made: madeTeam.status, teams: teams.map((t) => t.id), opsSaved, opsAfter });
      // A write then an immediate reload: James renames an agent on its page and reloads the agent list at once, with
      // agents-service held back, so whatever draws early comes from the saved copy. The old name must never draw.
      const OLD = `Saved agent ${TAG}`;
      const NEW = `Renamed agent ${TAG}`;
      const agent = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: OLD, role: 'Answers' }) })).json()).data;
      const renamer = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await renamer.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await renamer.getByText(OLD).first().waitFor({ timeout: 60_000 });
      await renamer.waitForTimeout(2_500);
      await renamer.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const name = renamer.getByLabel('Name').first();
      await name.waitFor({ timeout: 60_000 });
      // The draft is saved in place (it stays v1 until published), so the save is read from its request.
      const patched = renamer.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`), { timeout: 30_000 });
      await name.fill(NEW);
      const save = await patched.then((r) => r.status(), () => 0);
      await holdAgentReads(renamer);
      await renamer.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const oldDrawn = await renamer.getByText(OLD).first().waitFor({ timeout: EARLY_MS }).then(() => true, () => false);
      await renamer.unrouteAll({ behavior: 'ignoreErrors' });
      const newDrawn = await renamer.getByText(NEW).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('13 James renames an agent, reloads at once, and sees the new name, never the old one', save === 200 && !oldDrawn && newDrawn, { save, oldDrawn, newDrawn });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
