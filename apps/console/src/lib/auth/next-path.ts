/** Paths the sign-in screens own; the app shell renders them bare and never redirects them to /login. */
export const AUTH_PATHS = ['/login', '/sso', '/forgot-password', '/reset-password', '/mfa', '/signup', '/invite'];
export const isAuthPath = (pathname: string) => AUTH_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

/** A `next` value that stays inside the console: a path, never another origin. */
export function safeNext(raw: string | null | undefined): string {
  const path = raw?.split('?')[0] ?? '';
  // An invitation is the one auth page a signed-in person returns to: someone with an account accepts it as themselves.
  const invite = /^\/invite\/[^/]+$/.test(path);
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || (isAuthPath(path) && !invite)) return '/';
  return raw;
}
