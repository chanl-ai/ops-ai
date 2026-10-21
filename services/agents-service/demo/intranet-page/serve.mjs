// A stand-in bank intranet on its own origin, for trying the embedded chat with the person's SSO (c-118, c-224) and for
// use case uc-109. OPS_WIDGET_SNIPPET is the `/embed/v1.js` tag plus an `OpsChat.init` whose getSession is
// `opsSessionFrom(<agents url>, <deployment>)`:
//   OPS_WIDGET_SNIPPET='<script …>' PLATFORM_URL=http://127.0.0.1:8810 node serve.mjs 4610
// It serves index.html with that snippet, and answers /sso-token by signing the demo person in to
// platform-service, standing in for the intranet's identity provider. No Ops AI key is involved anywhere.
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const port = Number(process.argv[2] ?? 4610);
const snippet = process.env.OPS_WIDGET_SNIPPET ?? '';
const platform = process.env.PLATFORM_URL ?? 'http://127.0.0.1:8810';
const email = process.env.DEMO_EMAIL ?? 'm.okafor@harborpine.example';
const password = process.env.DEMO_PASSWORD ?? 'northfield-demo';
const page = readFileSync(new URL('./index.html', import.meta.url), 'utf8').replace('<!-- OPS_WIDGET_SNIPPET -->', snippet);

createServer(async (req, res) => {
  if (req.url === '/sso-token') {
    const r = await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const body = await r.json().catch(() => ({}));
    res.writeHead(r.ok ? 200 : 502, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ token: body?.data?.token ?? null }));
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(page);
}).listen(port, '127.0.0.1', () => console.log(`intranet demo on http://127.0.0.1:${port}`));
