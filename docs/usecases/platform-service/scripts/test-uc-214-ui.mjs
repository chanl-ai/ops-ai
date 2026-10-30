// uc-214 five wrong passwords lock sign-in for fifteen minutes, and a reset ends the lock, ui layer:
// docs/usecases/platform-service/wrong-passwords-lock-sign-in.md. Lena types a wrong password five times on the sign-in
// page and is told she is locked out; her right password is refused while the lock holds. She resets it through Forgot
// password and the mailed link, and signs in with the new one. Platform sign-in with the fake mailer.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { askForReset, resetLinks, setPasswordFromLink, tryPassword } from '../../lib/signin_ui.mjs';

const LENA = 'l.fischer@harborpine.example';
const NEW = `quay steps ${Math.random().toString(36).slice(2, 8)}`;

await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      const tries = [];
      for (let i = 0; i < 5; i++) tries.push(await tryPassword(page, consoleUrl, LENA, `wrong guess ${i}`));
      const last = tries[4];
      check(
        '1 Lena types a wrong password five times: four are refused, the fifth locks sign-in and the page says so',
        tries.slice(0, 4).every((t) => t.status === 401) && last.status === 429 && /lock|too many|try again/i.test(last.says) && !/lock|too many|try again/i.test(tries[3].says),
        { statuses: tries.map((t) => t.status), fourth: tries[3].says.slice(0, 200), fifth: last.says.slice(0, 300) },
      );

      const right = await tryPassword(page, consoleUrl, LENA, 'northfield-demo');
      check('2 her right password is refused while the lock holds', right.status === 429 && !right.signedIn && /lock|too many|try again/i.test(right.says), { status: right.status, says: right.says.slice(0, 300) });

      const sent = await askForReset(page, consoleUrl, LENA);
      const links = resetLinks(stack.mailDir, LENA);
      const done = links.length ? await setPasswordFromLink(page, consoleUrl, links[links.length - 1], NEW) : false;
      const after = await tryPassword(page, consoleUrl, LENA, NEW);
      check('5 she resets her password from the mailed link and signs in with it: the reset ended the lock', sent && done && after.status === 200 && after.signedIn, { sent, links: links.length, done, status: after.status });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true },
);

finish();
