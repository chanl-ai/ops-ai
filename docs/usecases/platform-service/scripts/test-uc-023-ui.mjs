// uc-023 members and roles, ui layer: docs/usecases/platform-service/members-and-roles.md. A console signed in through
// platform-service (dev seed: Priya Shah admin, James Richardson builder, both on team_ops), tools-service beside it.
// Priya invites a new address as viewer on Access; the link, opened in a fresh browser, signs the new person in as a
// viewer, whom the console and tools-service both hold to that role. Each step is checked on its own.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 7);
const NEWCOMER = `newcomer.${TAG}@harborpine.example`;
const NAME = `Newcomer ${TAG.toUpperCase()}`;
const KEY = 'ops-platform-session';
const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? 'null'), KEY);
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    let link = '';
    try {
      const priya = await signIn(browser, consoleUrl, 'p.shah@harborpine.example', errors);

      // 1. Access lists the team's members from platform-service, with the stored approver read as Reviewer.
      await step('1 Access lists the team from platform-service', async () => {
        const listed = armed(priya.waitForResponse((r) => r.url().startsWith(`${platform}/v1/settings/members`), { timeout: 60_000 }));
        await priya.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const res = await listed;
        const james = priya.getByRole('row', { name: /James Richardson/ });
        await james.waitFor({ timeout: 60_000 });
        const maya = (await priya.getByRole('row', { name: /Maya Okafor/ }).innerText().catch(() => '')).includes('Reviewer');
        // platform-service sends no last-active time and no team facet, so neither column is drawn; Role is on screen at 400 px.
        const heads = await priya.getByRole('columnheader').allInnerTexts();
        const fields = heads.filter((h) => /last active|^team/i.test(h.trim()));
        // At 400 px the page does not scroll sideways; the table, with its select and id columns, scrolls in its own
        // container, as the rulebook records for Access.
        await priya.setViewportSize({ width: 400, height: 900 });
        await priya.waitForTimeout(500);
        const pageWidth = await priya.evaluate(() => document.documentElement.scrollWidth);
        // Role rides under the name on a phone (its column is hidden), so the scroll is read from Status's header.
        const scrolls = await priya.getByRole('columnheader', { name: /Status/ }).evaluate((el) => {
          for (let n = el.parentElement; n; n = n.parentElement) if (n.scrollWidth > n.clientWidth && getComputedStyle(n).overflowX !== 'visible') return true;
          return false;
        });
        const role = pageWidth <= 400 && scrolls ? { x: 0, width: 0 } : null;
        await priya.setViewportSize({ width: 1440, height: 1000 });
        check('1 Access lists the team from platform-service', res?.status() === 200 && (await james.innerText()).includes('Builder') && maya && fields.length === 0 && !!role && role.x + role.width <= 400, { status: res?.status(), maya, heads, role });
      });

      // 2. Priya invites the new address as viewer; the link is shown once.
      await step('2 an invite shows its link once', async () => {
        await priya.getByTestId('access-invite').click();
        const dialog = priya.getByRole('dialog');
        await dialog.getByRole('textbox').first().fill(NEWCOMER);
        // It starts on the least role, so an unchanged choice never hands out approval rights.
        const startsOnViewer = await dialog.getByRole('radio', { name: /Viewer/ }).isChecked();
        await dialog.getByRole('radio', { name: /Viewer/ }).click();
        // The dialog says what happens (a link, shown once), names the team, offers no team the service ignores, and is one form.
        const said = await dialog.innerText();
        const form = await dialog.locator('form').count();
        const submit = await dialog.getByRole('button', { name: /^Invite/ }).getAttribute('type');
        const teamField = await dialog.locator('#invite-team').count();
        const sent = armed(priya.waitForResponse((r) => r.url() === `${platform}/v1/settings/members/invite`, { timeout: 60_000 }));
        await dialog.getByRole('button', { name: /^Invite/ }).click();
        const res = await sent;
        const body = res ? await res.json() : {};
        link = await priya.getByRole('textbox', { name: `Invitation link for ${NEWCOMER}` }).inputValue();
        const token = body.data?.invites?.[0]?.token;
        check('2 an invite shows its link once', res?.status() === 200 && !!token && link === `${consoleUrl}/invite/${token}`, { status: res?.status(), link });
        await priya.getByRole('button', { name: 'Done' }).click();
        check(
          '2 the invite dialog is a form for the current team and says what happens',
          form === 1 && submit === 'submit' && /Invite to Operations/.test(said) && /No email is sent/.test(said) && !/single sign-on/.test(said) && teamField === 0,
          { form, submit, teamField, said: said.replace(/\s+/g, ' ').slice(0, 200) },
        );
        // The service keeps only a hash of the link, so the invited row offers none afterwards.
        const invitedRow = priya.getByRole('row', { name: new RegExp(NEWCOMER.replace(/\./g, '\\.')) });
        await invitedRow.waitFor({ timeout: 60_000 });
        check('2b the invite dialog starts on Viewer, the least role', startsOnViewer, { startsOnViewer });
        check('2 an invited row shows no link to copy again', (await invitedRow.innerText()).includes('Invited') && (await invitedRow.getByRole('link').count()) === 0);
      });

      // 3. The link in a fresh browser names Priya, the team and the role, asks only for a name, and signs the person in.
      const newcomer = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      newcomer.on('pageerror', (e) => errors.push(`newcomer: ${e.message}`));
      await step('3 accepting signs the newcomer in as viewer on Operations', async () => {
        await newcomer.goto(link, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const form = newcomer.getByTestId('invite-form');
        await form.waitFor({ timeout: 60_000 });
        const said = await form.innerText();
        const passwordAsked = await newcomer.locator('#inv-password').count();
        await newcomer.locator('#inv-name').fill(NAME);
        // The workspace signs in by password, so a new person sets one (c-188); a test value for this run.
        if (passwordAsked) {
          await newcomer.locator('#inv-password').fill('uc023-newcomer-pass');
          await newcomer.locator('#inv-confirm').fill('uc023-newcomer-pass').catch(() => undefined);
        }
        await newcomer.getByTestId('invite-accept').click();
        // Joining welcomes the person; the invitation, now accepted, never reads as a used link to them.
        const welcomed = await newcomer.getByText(/Welcome to Operations/).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const usedShown = await newcomer.getByText('This invitation was already used').count();
        await newcomer.waitForURL((u) => !u.pathname.startsWith('/invite'), { timeout: 60_000 }).catch(async (e) => { throw new Error(`page: ${(await newcomer.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 300)} | ${newcomer.url()}`); });
        const session = await stored(newcomer);
        check(
          '3 accepting signs the newcomer in as viewer on Operations, welcomed, never told the link was used',
          said.includes('Priya Shah') && said.includes('Operations') && said.includes('Viewer') && passwordAsked === 1 && session?.principal?.roles?.team_ops === 'viewer' && welcomed && usedShown === 0,
          { said: said.slice(0, 160), passwordAsked, roles: session?.principal?.roles, welcomed, usedShown },
        );
      });

      // 4. As a viewer: no Invite on Access, no builder controls on Tools, and tools-service refuses a write.
      await step('4 the viewer is held to the role in the console and the service', async () => {
        await newcomer.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await newcomer.getByRole('row', { name: new RegExp(NAME) }).waitFor({ timeout: 60_000 });
        const invite = await newcomer.getByTestId('access-invite').count();
        // A viewer sees Invite locked with the reason, rather than no button at all.
        await newcomer.getByTestId('access-invite-locked').hover();
        const why = await newcomer.getByRole('tooltip').first().innerText().catch(() => '');
        // The card's screen evidence: a viewer's Access page with the locked Invite and its reason.
        mkdirSync(evidenceDir('311', 'screens'), { recursive: true });
        // At the review widths, each with the reason open beside the button.
        for (const width of [1280, 400]) {
          await newcomer.setViewportSize({ width, height: 800 });
          await newcomer.mouse.move(0, 0);
          await newcomer.getByTestId('access-invite-locked').scrollIntoViewIfNeeded();
          await newcomer.getByTestId('access-invite-locked').hover();
          await newcomer.getByRole('tooltip').first().waitFor({ timeout: 10_000 }).catch(() => undefined);
          await newcomer.waitForTimeout(300);
          await newcomer.screenshot({ path: join(evidenceDir('311', 'screens'), `invite-locked-${width}.png`) });
        }
        await newcomer.setViewportSize({ width: 1440, height: 1000 });
        check('4b a viewer sees Invite locked with why: it needs Manage on Access', /Manage on Access/.test(why), { why });
        await newcomer.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await newcomer.getByTestId('page-title').first().waitFor({ timeout: 60_000 });
        await newcomer.waitForTimeout(1500);
        const build = await newcomer.getByTestId('import-operations').count();
        const token = (await stored(newcomer))?.token;
        const r = await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ displayName: `Viewer ${TAG}`, name: `viewer-${TAG}`, type: 'http' }) });
        const code = (await r.json()).error?.code;
        check('4 the viewer is held to the role in the console and the service', invite === 0 && build === 0 && r.status === 403 && code === 'role_required', { invite, build, status: r.status, code });
      });

      // 5. Priya sees the newcomer active as a viewer.
      await step('5 Access shows the newcomer active as viewer', async () => {
        await priya.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = priya.getByRole('row', { name: new RegExp(NAME) });
        await row.waitFor({ timeout: 60_000 });
        const text = await row.innerText();
        check('5 Access shows the newcomer active as viewer', text.includes('Viewer') && text.includes('Active') && text.includes(NEWCOMER), text.replace(/\s+/g, ' '));
      });

      // 6. The same link again reads as used, and the service refuses a second accept.
      await step('6 a used link cannot be used again', async () => {
        const again = await (await browser.newContext()).newPage();
        await again.goto(link, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const used = await again.getByTestId('invite-used').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const token = link.split('/invite/')[1];
        const r = await fetch(`${platform}/v1/invites/${token}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Second' }) });
        const code = (await r.json()).error?.code;
        check('6 a used link cannot be used again', used && r.status === 409 && code === 'invite_used', { used, status: r.status, code });
      });

      // 7. A builder sees no Invite and platform-service refuses a member write from them.
      await step('7 a builder cannot manage members', async () => {
        const james = await signIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
        await james.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByRole('row', { name: /Priya Shah/ }).waitFor({ timeout: 60_000 });
        const invite = await james.getByTestId('access-invite').count();
        const token = (await stored(james))?.token;
        const r = await fetch(`${platform}/v1/settings/members/invite`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ emails: [`x.${TAG}@harborpine.example`], role: 'admin' }) });
        const code = (await r.json()).error?.code;
        check('7 a builder cannot manage members', invite === 0 && r.status === 403 && code === 'admin_required', { invite, status: r.status, code });
      });

      // 8. An invitation to someone who already has an account (Omar, Fraud) never signs in whoever holds the link:
      // a stranger's browser is asked to sign in as Omar and the service refuses the bare link; Omar, signed in as
      // himself, joins Operations as viewer and keeps his own account and teams.
      await step('8 an existing person accepts only as themselves', async () => {
        const OMAR = 'o.haddad@harborpine.example';
        await priya.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await priya.getByTestId('access-invite').click();
        const dialog = priya.getByRole('dialog');
        await dialog.getByRole('textbox').first().fill(OMAR);
        await dialog.getByRole('radio', { name: /Viewer/ }).click();
        await dialog.getByRole('button', { name: /^Invite/ }).click();
        const omarLink = await priya.getByRole('textbox', { name: `Invitation link for ${OMAR}` }).inputValue();
        await priya.getByRole('button', { name: 'Done' }).click();

        const stranger = await (await browser.newContext()).newPage();
        await stranger.goto(omarLink, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const asked = await stranger.getByTestId('invite-sign-in-first').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const strangerStored = await stored(stranger);
        const bare = await fetch(`${platform}/v1/invites/${omarLink.split('/invite/')[1]}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Not Omar' }) });
        const bareCode = (await bare.json()).error?.code;

        await stranger.getByTestId('invite-sign-in-first').getByRole('link').first().click();
        await stranger.waitForURL((u) => u.pathname.startsWith('/login'), { timeout: 60_000 });
        await stranger.getByLabel('Password').fill('northfield-demo');
        await stranger.getByRole('button', { name: /^Sign in/ }).first().click();
        await stranger.getByTestId('invite-join').waitFor({ timeout: 60_000 });
        await stranger.getByTestId('invite-join').getByRole('button').first().click();
        await stranger.waitForURL((u) => !u.pathname.startsWith('/invite'), { timeout: 60_000 });
        const omar = await stored(stranger);
        check(
          '8 an existing person accepts only as themselves',
          asked && strangerStored === null && bare.status === 401 && bareCode === 'sign_in_as_invitee' && omar?.principal?.email === OMAR && omar?.principal?.roles?.team_ops === 'viewer' && omar?.principal?.roles?.team_fraud === 'approver',
          { asked, bare: bare.status, bareCode, roles: omar?.principal?.roles },
        );
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
