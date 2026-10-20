import { NextResponse } from 'next/server';

/**
 * Developer pages (/dev: the widget gallery, design mocks; /preview: the settings mock) exist only on a development
 * server. Anywhere else every such route answers 404 before any page renders, so a mock that skips the signed-in shell
 * is never reachable. A use-case run serves the console from a production build and sets OPS_ALLOW_PREVIEW_PAGES so
 * its checks can open those pages; no deployment sets it.
 */
export function proxy() {
  if (process.env.NODE_ENV !== 'development' && process.env.OPS_ALLOW_PREVIEW_PAGES !== '1') return new NextResponse(null, { status: 404 });
  return NextResponse.next();
}

export const config = { matcher: ['/dev/:path*', '/preview/:path*'] };
