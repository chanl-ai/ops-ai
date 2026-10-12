/** Paths the sign-in screens own; the app shell renders them bare and never redirects them to /login. */
export const AUTH_PATHS = ['/login', '/sso', '/forgot-password', '/reset-password', '/mfa', '/signup', '/invite'];
export const isAuthPath = (pathname: string) => AUTH_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

/** A `next` value that stays inside the console: a path, never another origin. */
export function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || isAuthPath(raw.split('?')[0])) return '/';
  return raw;
}
