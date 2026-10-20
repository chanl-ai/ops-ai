import type { ReactNode } from 'react';

/** A link to one of the standalone HTML pages under /docs/files: a native link, since the page is a file. */
export function FileLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={`/docs${href}`}>{children}</a>;
}
