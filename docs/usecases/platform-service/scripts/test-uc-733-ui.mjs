// uc-733 the consent page of a person connecting an assistant to a team's MCP address, ui layer. Headless Chromium against
// a console signed in through platform-service. The page is /oauth/authorize in the (auth) layout and reads
// GET /v1/oauth/consent; its parts carry data-testid consent-client-name, consent-name-source, consent-redirect-host,
// consent-team and consent-allow. Doc: docs/usecases/platform-service/mcp-company-sign-in.md.
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
// tools-service's public base, which a proxy serves on another path than platform-service's.
const MCP_BASE = 'http://127.0.0.1:8890/api/tools';
const REDIRECT = 'https://claude.example/callback';
const SHOTS = evidenceDir('733');

async function call(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const r = await fetch(`${platform}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
}

await withUiStack(
  async (consoleUrl) => {
    const registered = await call('POST', '/oauth/register', {
      client_name: 'Official Microsoft Copilot',
      redirect_uris: [REDIRECT],
      token_endpoint_auth_method: 'none',
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
    });
    check('the client registers (201)', registered.status === 201, registered);
    const session = (await call('POST', '/v1/auth/sign-in', { email: 'j.richardson@harborpine.example', password: 'northfield-demo' })).body?.data;
    const challenge = createHash('sha256').update(randomBytes(32).toString('hex')).digest('base64url');
    const query = new URLSearchParams({
      response_type: 'code',
      client_id: registered.body?.client_id ?? '',
      redirect_uri: REDIRECT,
      code_challenge: challenge,
      code_challenge_method: 'S256',
      resource: `${MCP_BASE}/mcp/team_ops`,
      state: 's1',
    });
    mkdirSync(SHOTS, { recursive: true });

    const browser = await chromium.launch();
    try {
      for (const [width, name] of [[1440, 'desktop'], [390, 'phone']]) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        await context.addInitScript((s) => localStorage.setItem('ops-platform-session', JSON.stringify(s)), session);
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push(e.message));
        const response = await page.goto(`${consoleUrl}/oauth/authorize?${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('consent-allow').waitFor({ timeout: 15_000 }).catch(() => undefined);
        // Snapshot before the iframe step: the browser's own blocked-frame error is not a page error.
        let pageErrors = [];
        const text = (id) => page.getByTestId(id).innerText().catch(() => '');
        pageErrors = [...errors];
        if (width === 1440) {
          check('the real redirect host is shown', (await text('consent-redirect-host')).includes('claude.example'), await text('consent-redirect-host'));
          check(
            'the client name is shown and marked as the name it gave itself',
            (await text('consent-client-name')).includes('Official Microsoft Copilot') && /itself|self|claims/i.test(await text('consent-name-source')),
            await text('consent-name-source'),
          );
          check('the team comes from the address, with no team picker', (await text('consent-team')).includes('team_ops') && (await page.getByRole('combobox').count()) === 0, await text('consent-team'));
          const csp = response?.headers()['content-security-policy'] ?? '';
          check("the consent page cannot be framed (frame-ancestors 'none')", /frame-ancestors\s+'none'/.test(csp), csp);
          const framed = await page.evaluate(async (url) => {
            const f = document.createElement('iframe');
            f.src = url;
            document.body.append(f);
            await new Promise((r) => setTimeout(r, 3000));
            try { return f.contentDocument?.body?.innerText?.length ?? 0; } catch { return -1; }
          }, `${consoleUrl}/oauth/authorize?${query}`);
          check('a framed copy does not render the page', framed <= 0, framed);
        }
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        check(`nothing is clipped sideways at ${width}`, overflow <= 0, overflow);
        check(`no page errors at ${width}`, pageErrors.length === 0, pageErrors);
        await page.screenshot({ path: join(SHOTS, `uc-733-consent-${name}.png`) });
        await context.close();
      }
    } finally {
      await browser.close();
    }
  },
  { platform: true, signIn: true, platformEnv: { OPS_TOOLS_PUBLIC_URL: MCP_BASE } },
);
finish();
