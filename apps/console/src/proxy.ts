import { NextResponse, type NextRequest } from 'next/server';
import { movedTo } from '@/lib/routes/moved';

/**
 * Two jobs before any page renders.
 * Old addresses: pages moved under their area (/agents is /build/agents), so an old link answers a temporary
 * redirect to the new one with its query kept. Temporary first, so a reverted release does not leave browsers
 * holding a cached permanent redirect.
 * Developer pages (/dev: the widget gallery; /preview: the Human Tasks layout options) exist only on a development
 * server. Anywhere else they answer 404, so a mock that skips the signed-in shell is never reachable. A use-case run
 * serves the console from a production build and sets OPS_ALLOW_PREVIEW_PAGES so its checks can open those pages.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const to = movedTo(pathname);
  if (to) return NextResponse.redirect(new URL(to + search, request.url), 307);
  if (pathname.startsWith('/dev') || pathname.startsWith('/preview')) {
    if (process.env.NODE_ENV !== 'development' && process.env.OPS_ALLOW_PREVIEW_PAGES !== '1') return new NextResponse(null, { status: 404 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    '/dev/:path*', '/preview/:path*',
    '/integrations/:path*', '/workflows/:path*', '/knowledge/:path*', '/logs/:path*', '/document-types/:path*',
    '/reviews/:path*', '/tools/:path*', '/model-risk/:path*', '/guardrails/:path*', '/assurance/:path*',
    '/channels/:path*', '/activity/:path*', '/policies/:path*', '/widgets/:path*', '/agents/:path*', '/access/:path*',
    '/skills/:path*', '/files/:path*', '/cases/:path*', '/wiki/:path*',
  ],
};
