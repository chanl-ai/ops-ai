'use client';

import { AnchorProvider, useActiveAnchor } from 'fumadocs-core/toc';
import type { TOCItemType } from 'fumadocs-core/toc';
import { createContext, type ReactNode, use } from 'react';


const RailToc = createContext<TOCItemType[]>([]);

/**
 * The left contents rail: the open page's sections at the top, like the contents column of the spec pages, and the
 * pages of the site below them, so there is no second column on the right.
 */
export function RailTocProvider({ toc, children }: { toc: TOCItemType[]; children: ReactNode }) {
  return (
    <RailToc value={toc}>
      <AnchorProvider toc={toc} single>
        {children}
      </AnchorProvider>
    </RailToc>
  );
}

/** The open page's sections, numbered like the spec pages' contents column, at the top of the rail. */
export function RailSections() {
  const toc = use(RailToc).filter((t) => t.depth <= 3);
  const active = useActiveAnchor();
  if (!toc.length) return null;
  const min = Math.min(...toc.map((t) => t.depth));
  let n = 0;
  return (
    <nav className="ops-rail-contents" aria-label="Contents">
      <p className="ops-rail-heading">Contents</p>
      <ol className="ops-rail-toc">
        {toc.map((t) => (
          <li key={t.url} data-depth={t.depth - min}>
            {t.depth === min && <span className="ops-rail-num">{++n}.</span>}
            <a href={t.url} data-active={active === t.url.slice(1)}>
              {t.title}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
