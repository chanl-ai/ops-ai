import Link from 'next/link';
import type { ReactNode } from 'react';

export function SummaryCards({ children }: { children: ReactNode }) {
  return <div className="ops-cards not-prose">{children}</div>;
}

export function SummaryCard({ title, href, children }: { title: string; href?: string; children?: ReactNode }) {
  const body = (
    <>
      <h3 className="ops-card-title">{title}</h3>
      <div className="ops-card-body">{children}</div>
    </>
  );
  if (!href) return <div className="ops-card">{body}</div>;
  const external = /^https?:/.test(href);
  return external ? (
    <a href={href} className="ops-card ops-card-link" target="_blank" rel="noreferrer">
      {body}
    </a>
  ) : (
    <Link href={href} className="ops-card ops-card-link">
      {body}
    </Link>
  );
}
