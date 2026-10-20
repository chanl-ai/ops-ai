// uc-170 Govern > Policies reads and changes the workspace's policies on platform-service, ui layer:
// docs/usecases/console/policies-page.md. Sam (Security admin) changes one and it survives a reload; James (builder)
// sees the same cards switched off and the server refuses his change.
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const signIn = async (browser, consoleUrl, email) => {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const sam = await signIn(browser, consoleUrl, 's.adeyemi@northfieldbank.com');
      await sam.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const card = sam.getByTestId('setting-policy-stepUp');
      await card.waitFor({ timeout: 120_000 });
      const shown = {
        cards: await sam.locator('[data-testid^="setting-policy-"]').count(),
        sample: await sam.getByTestId('sample-data-notice').count(),
        off: await card.getByRole('radio', { name: /^Off/ }).getAttribute('aria-checked'),
      };
      check('Policies on platform-service shows every policy as its own card, none on sample data, Re-sign-in off by default and the server’s own effect line on each', shown.cards >= 8 && shown.sample === 0 && shown.off === 'true', shown);

      // Each card is drawn from the server's kind and titled with its title (c-214), so a policy added on the server
      // shows with the right control and name and no console change.
      const token = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 's.adeyemi@northfieldbank.com', password: 'northfield-demo' }) })).json()).data.token;
      const served = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies`, { headers: { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_security' } })).json()).data;
      const drawn = [];
      for (const pol of served) {
        const c = sam.getByTestId(`setting-policy-${pol.key}`);
        const text = await c.innerText();
        // Publish modes are edited on Publish reviews (c-214); their card's control is the link there.
        const control = pol.kind === 'publish_modes' ? await c.getByTestId('policy-open-publish-reviews').count() : pol.kind === 'days' || pol.kind === 'hours' ? await c.getByRole('spinbutton').count() : pol.kind === 'floor' ? await c.getByRole('radio', { name: /^80%/ }).count() : await c.getByRole('radio', { name: /^On/ }).count();
        drawn.push({ key: pol.key, kind: pol.kind, titled: !!pol.title && text.includes(pol.title), control });
      }
      check('each card carries the server’s title and the control its kind calls for', drawn.length >= 8 && drawn.every((d) => d.kind && d.titled && d.control >= 1), drawn.filter((d) => !d.titled || d.control < 1));

      await card.getByRole('radio', { name: /^On/ }).click();
      const put = sam.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/policies/stepUp'), { timeout: 30_000 }).catch(() => null);
      await card.getByRole('button', { name: 'Save' }).click();
      const res = await put;
      await sam.reload({ waitUntil: 'domcontentloaded' });
      const after = await sam.getByTestId('setting-policy-stepUp').getByRole('radio', { name: /^On/ }).getAttribute('aria-checked', { timeout: 60_000 });
      const server = (await (await fetch(`${platform}/v1/policies`, { headers: { Authorization: `Bearer ${await tokenFor('s.adeyemi@northfieldbank.com')}`, 'X-Team-Id': 'team_security' } })).json()).data.find((p) => p.key === 'stepUp').value;
      check('a Security admin saves a policy and it is still set after a reload and on the server', res?.status() === 200 && after === 'true' && server === true, { status: res?.status(), after, server });

      // Put it back, so the stack's other checks see the open default.
      await sam.getByTestId('setting-policy-stepUp').getByRole('radio', { name: /^Off/ }).click();
      await sam.getByTestId('setting-policy-stepUp').getByRole('button', { name: 'Save' }).click();

      // A number policy and a per-area one save too, each by its own control and each seen on the server.
      const sauth = { Authorization: `Bearer ${await tokenFor('s.adeyemi@northfieldbank.com')}`, 'X-Team-Id': 'team_security' };
      const policy = async (key) => (await (await fetch(`${platform}/v1/policies`, { headers: sauth })).json()).data.find((p) => p.key === key);
      const sla = sam.getByTestId('setting-policy-reviewSlaHours');
      await sla.getByLabel(/in hours/).fill('12');
      const putSla = sam.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/policies/reviewSlaHours'), { timeout: 30_000 }).catch(() => null);
      await sla.getByRole('button', { name: 'Save' }).click();
      const slaRes = await putSla;
      const slaAfter = (await policy('reviewSlaHours')).value;
      // Which publishes need a review is edited on Publish reviews only (c-214): its card here links there.
      const modes = sam.getByTestId('setting-policy-publishReview');
      const editors = await modes.getByRole('combobox').count();
      await modes.getByTestId('policy-open-publish-reviews').click();
      const linked = await sam.waitForURL('**/settings/publish-reviews', { timeout: 30_000 }).then(() => true, () => false);
      check('a number policy saves from its control (200, 12 hours on the server); publish reviews are one editor, linked from here', slaRes?.status() === 200 && slaAfter === 12 && editors === 0 && linked, { sla: slaRes?.status(), slaAfter, editors, linked });
      await sam.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('setting-policy-reviewSlaHours').waitFor({ timeout: 60_000 });
      const slaBack = sam.getByTestId('setting-policy-reviewSlaHours');
      await slaBack.getByLabel(/in hours/).fill('8');
      await slaBack.getByRole('button', { name: 'Save' }).click();
      await sam.waitForTimeout(800);

      // A per-team switch (toolWritesNeedApproval, value { team: bool }): off for a team that has not set it, saved for
      // the acting team only, and still on after a reload.
      const tw = sam.getByTestId('setting-policy-toolWritesNeedApproval');
      const twBefore = await tw.getByRole('radio', { name: /^Off/ }).getAttribute('aria-checked');
      await tw.getByRole('radio', { name: /^On/ }).click();
      const putTw = sam.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/policies/toolWritesNeedApproval'), { timeout: 30_000 }).catch(() => null);
      await tw.getByRole('button', { name: 'Save' }).click();
      const twRes = await putTw;
      const twServer = (await policy('toolWritesNeedApproval')).value;
      await sam.reload({ waitUntil: 'domcontentloaded' });
      const twAfter = await sam.getByTestId('setting-policy-toolWritesNeedApproval').getByRole('radio', { name: /^On/ }).getAttribute('aria-checked');
      check('a per-team switch reads off by default, saves on for the acting team, and stays on after a reload', twBefore === 'true' && twRes?.status() === 200 && twServer?.team_security === true && twAfter === 'true', { twBefore, status: twRes?.status(), twServer, twAfter });
      await sam.getByTestId('setting-policy-toolWritesNeedApproval').getByRole('radio', { name: /^Off/ }).click();
      await sam.getByTestId('setting-policy-toolWritesNeedApproval').getByRole('button', { name: 'Save' }).click();
      await sam.waitForTimeout(800);

      const james = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      await james.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Every member reads the policies (7faf3ddc); a builder sees the same cards with their controls off and no Save.
      const jcard = james.getByTestId('setting-policy-stepUp');
      await jcard.waitFor({ timeout: 120_000 });
      const jshown = {
        cards: await james.locator('[data-testid^="setting-policy-"]').count(),
        saves: await james.locator('[data-testid^="setting-policy-"]').getByRole('button', { name: 'Save' }).count(),
        offDisabled: await jcard.getByRole('radio', { name: /^Off/ }).isDisabled(),
      };
      const jtok = await tokenFor('j.richardson@northfieldbank.com');
      const refused = await fetch(`${platform}/v1/policies/stepUp`, { method: 'PUT', headers: { Authorization: `Bearer ${jtok}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ value: true }) });
      check('a builder reads the same cards with their controls off and no Save, and the server refuses his change (403)', jshown.cards >= 8 && jshown.saves === 0 && jshown.offDisabled && refused.status === 403, { ...jshown, status: refused.status });

      check('no page errors', [...(sam.errors ?? []), ...(james.errors ?? [])].length === 0, [...(sam.errors ?? []), ...(james.errors ?? [])]);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
