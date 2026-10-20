import { type NextRequest, NextResponse } from 'next/server';

import { readConfig } from './config';

// The console's own origin, where an editor previews a deployment as a person: it may frame any live deployment's
// chat, which still answers only a session minted for it (agents-service's preview session).
const CONSOLE = process.env.OPS_CONSOLE_URL ? new URL(process.env.OPS_CONSOLE_URL).origin : null;

/**
 * `frame-ancestors` for the chat page from the deployment's listed origins (c-158), plus the console's for its preview:
 * only those pages may frame it. An unknown or paused deployment, or a failed read, answers `'none'`, so the page never
 * falls open.
 */
export async function proxy(request: NextRequest) {
  const deployment = request.nextUrl.pathname.split('/')[2] ?? '';
  const config = await readConfig(deployment, request.nextUrl.searchParams.get('tenant') ?? '', request.headers.get('referer'));
  const origins = config && !config.paused ? [...config.allowedOrigins, ...(CONSOLE ? [CONSOLE] : [])] : [];
  const ancestors = origins.length ? origins.join(' ') : "'none'";
  const response = NextResponse.next();
  response.headers.set('Content-Security-Policy', `frame-ancestors ${ancestors}`);
  return response;
}

// The loader script is served from agents-service through the rewrite; every other /embed path is a chat page.
export const config = { matcher: ['/embed/((?!v1\\.js$).+)'] };
