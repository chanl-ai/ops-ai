// What a bank needs to embed an agent's chat (c-224), generated from the mint-key flow in
// docs/console/embedding-the-chat.md: its server mints a 15-minute session with the deployment's mint key, and the page
// loads `/embed/v1.js` and starts it with `OpsChat.init`. Neither part carries a key: the server reads it from its own
// secrets. Relative imports only: the test runs under `node --test`.

/** The bank's own endpoint the page asks for a session; the doc's example uses this path. */
export const SESSION_PATH = '/api/ops-chat/session';
/** The environment variable the bank's server keeps the mint key in. */
export const KEY_VARIABLE = 'OPS_WIDGET_KEY';
/** The steps the snippet follows, for the link beside it. */
export const STEPS_DOC = 'https://github.com/chanl-ai/ops-ai/blob/main/docs/console/embedding-the-chat.md';

export interface EmbedSnippet {
  /** The request the bank's server makes for each signed-in person. */
  server: string;
  /** What goes on the page, before </body>. */
  page: string;
}

export function snippetFor(loaderUrl: string, deploymentId: string, tenant: string): EmbedSnippet {
  const host = new URL(loaderUrl).origin;
  const js = (v: string) => JSON.stringify(v).replace(/</g, '\\u003c');
  const server = [
    `curl -X POST ${host}/v1/widget-deployments/${deploymentId}/sessions \\`,
    `  -H "Authorization: Bearer $${KEY_VARIABLE}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"email": "<the signed-in person's email>", "name": "<their name>", "origin": "<this page's origin>"}'`,
  ].join('\n');
  const page = [
    `<script src=${js(loaderUrl)} async></script>`,
    '<script>',
    '  function startChat() {',
    '    OpsChat.init({',
    `      deployment: ${js(deploymentId)},`,
    `      tenant: ${js(tenant)},`,
    `      // Your server's endpoint: it makes the request above and returns { session, expiresIn }, or 401 when signed out.`,
    '      getSession: async () => {',
    `        const r = await fetch(${js(SESSION_PATH)}, { method: 'POST', credentials: 'include' });`,
    '        return r.ok ? await r.json() : null;',
    '      },',
    '    });',
    '  }',
    "  window.OpsChat ? startChat() : window.addEventListener('ops-chat:load', startChat);",
    '</script>',
  ].join('\n');
  return { server, page };
}
