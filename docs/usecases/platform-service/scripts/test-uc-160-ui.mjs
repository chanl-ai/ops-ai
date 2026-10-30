// uc-160 a person resets their password by a mailed link and signs in with it, ui layer:
// docs/usecases/platform-service/password-sign-in-and-reset.md. Ravi asks for a reset on Forgot password, follows the
// link mailed to him, sets a new password on the console's reset page and signs in with it; the demo password stops
// working for him. Platform sign-in with the fake mailer writing to the stack's mail folder.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { askForReset, resetLinks, setPasswordFromLink, tryPassword } from '../../lib/signin_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const NEW = `harbour lights ${Math.random().toString(36).slice(2, 8)}`;

await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      const sent = await askForReset(page, consoleUrl, RAVI);
      const links = resetLinks(stack.mailDir, RAVI);
      check('1 Ravi asks on Forgot password, and one reset link is mailed to him', sent && links.length === 1, { sent, links });

      const done = links[0] ? await setPasswordFromLink(page, consoleUrl, links[0], NEW) : false;
      check('3 the link opens the reset page, which takes his new password', done, done);

      const withNew = await tryPassword(page, consoleUrl, RAVI, NEW);
      check('5 he signs in with the new password', withNew.status === 200 && withNew.signedIn, { status: withNew.status, signedIn: withNew.signedIn });

      const fresh = await (await browser.newContext()).newPage();
      const withOld = await tryPassword(fresh, consoleUrl, RAVI, 'northfield-demo');
      check('5 the demo password no longer signs him in', withOld.status === 401 && !withOld.signedIn, { status: withOld.status, says: withOld.says.slice(0, 200) });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true },
);

finish();
