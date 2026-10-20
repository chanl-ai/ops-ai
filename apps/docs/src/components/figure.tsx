import type { ReactNode } from 'react';

/** A wireframe or screenshot, framed like the spec pages, with its alt text as the caption. */
export function OpsFigure({ caption, children }: { caption?: string; children: ReactNode }) {
  return (
    <figure className="ops-figure not-prose">
      <div className="ops-figure-media">{children}</div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
