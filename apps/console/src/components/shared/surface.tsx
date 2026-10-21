import type { ReactNode } from 'react';
import Link from 'next/link';

import { FieldRow } from '@/components/shared/field-row';
import { cn } from '@/lib/utils';

/** One bordered panel with a title row; rows inside separate with hairlines. Never nest one inside another. */
export function Section({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  flush,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean;
  id?: string;
}) {
  return (
    <section id={id} className={cn('min-w-0 rounded-lg border bg-card', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(!flush && 'p-4', bodyClassName)}>{children}</div>
    </section>
  );
}

/** A homogeneous list as rows, not cards. */
export function Rows({ children, className, testId }: { children: ReactNode; className?: string; testId?: string }) {
  return (
    <ul className={cn('min-w-0 divide-y', className)} data-testid={testId}>
      {children}
    </ul>
  );
}

export function Row({
  leading,
  title,
  description,
  trailing,
  href,
  onClick,
  className,
  wrap,
  children,
}: {
  leading?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  trailing?: ReactNode;
  href?: string;
  onClick?: () => void;
  className?: string;
  /** Title and description wrap instead of truncating, and the row wraps its trailing controls below on a phone. */
  wrap?: boolean;
  /** A body under the description for entries that carry more than a title line; it never truncates. */
  children?: ReactNode;
}) {
  const inner = (
    <>
      {leading && <div className="flex shrink-0 items-center">{leading}</div>}
      <div className={cn('min-w-0 flex-1', wrap && 'min-w-40')}>
        <div className={cn('text-sm font-medium', wrap ? 'break-words' : 'truncate')}>{title}</div>
        {description && <div className={cn('text-xs text-muted-foreground', wrap ? 'break-words' : 'truncate')}>{description}</div>}
        {children}
      </div>
      {trailing && <div className="flex shrink-0 items-center gap-2 text-sm tabular-nums">{trailing}</div>}
    </>
  );
  const base = cn('flex min-w-0 gap-3 px-4 py-2.5', wrap ? 'flex-wrap items-start' : 'items-center', (href || onClick) && 'transition-colors hover:bg-accent/50', className);
  if (href)
    return (
      <li>
        <Link href={href} className={base}>
          {inner}
        </Link>
      </li>
    );
  if (onClick)
    return (
      <li>
        <button type="button" onClick={onClick} className={cn(base, 'w-full text-left')}>
          {inner}
        </button>
      </li>
    );
  return <li className={base}>{inner}</li>;
}

/** One number with a label above and a hint below; links through when `href` is set. */
export function StatTile({ label, value, hint, tone = 'default', href }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'default' | 'bad' | 'warn'; href?: string }) {
  const body = (
    <div className={cn('flex h-full min-w-0 flex-col gap-1 rounded-lg border bg-card px-4 py-3', href && 'transition-colors hover:bg-accent/40')}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('text-2xl font-semibold tabular-nums leading-tight tracking-tight', tone === 'bad' && 'text-destructive', tone === 'warn' && 'text-warning-text')}>{value}</span>
      {hint && <span className="truncate text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

/** Label and value pairs for summaries and review steps; values wrap instead of truncating. Each pair is a FieldRow, so
 * the label sits above its value in a narrow panel, as on every record rail (c-434). */
export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <div>
      {rows.map(([k, v]) => (
        <FieldRow key={k} label={k} value={v} wrap />
      ))}
    </div>
  );
}
