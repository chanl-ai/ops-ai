'use client';

/**
 * FieldRow + FieldSectionLabel — the ONE canonical record-detail row.
 *
 * Matches the Record UX artifact's `.frow` (c3cceac2 §03/§04):
 *   [icon] [UPPERCASE label · 112px, nowrap+truncate] [value · left, truncates] [verified/adornment/✎]
 * In a box narrower than 28rem (a record rail, a sheet or any panel at phone width) the label sits above the value,
 * which then has the panel's whole width (c-434): side by side, a 112px label left the value a strip a few
 * characters wide. Each row measures its own box (a container query), so no caller chooses the layout.
 *
 * One uniform row for EVERY profile field (built-in or custom) on BOTH the
 * customer and company records, so the two surfaces read identically — killing
 * the divergent per-field layouts (the customer rail had its own icon-led row,
 * the company rail a label/value one). This is the shared primitive both adopt.
 *
 * - `icon`      leading glyph (artifact `.fic`) — optional; both records pass one.
 * - `label`     rendered UPPERCASE (artifact `.fk`).
 * - `value`     left-aligned, truncates; empty renders a muted em-dash.
 * - `mono`      mono + tabular value (phone numbers, IDs, order #s).
 * - `href`      render the value as a link (internal Link, or external `a`).
 * - `verified`  trailing success check (e.g. a verified phone).
 * - `adornment` generic trailing node (e.g. provenance "extracted / manual" icon).
 * - `onEdit`    hover-revealed pencil → opens the record's single edit dialog.
 * Rows separate with a hairline top border (artifact `.frow + .frow`); the first
 * row in a card gets none via `first:border-t-0`.
 */

import * as React from 'react';
import Link from 'next/link';
import { Check, Pencil, type LucideIcon } from 'lucide-react';
import { WholeTokens } from '@/components/shared/whole-tokens';
import { cn } from '@/lib/utils';

/** Uppercase section divider label (e.g. "Main details", "Custom attributes"). */
export function FieldSectionLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={cn(
        'px-1 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70',
        className
      )}
    >
      {children}
    </p>
  );
}

interface FieldRowProps {
  /** Leading icon (artifact `.fic`). Optional — both records pass one. */
  icon?: LucideIcon;
  label: string;
  /** Left-aligned value. Empty/nullish renders a muted em-dash. */
  value?: React.ReactNode;
  /** Placeholder shown when value is empty (defaults to an em-dash). */
  emptyHint?: React.ReactNode;
  /** Mono + tabular value (phone, IDs, order numbers). */
  mono?: boolean;
  /** Let the label and value wrap instead of trimming to one line: for sentences and lists, where the trimmed part
   * matters. A wrapped value breaks between words and keeps a reference (NS-2026-GN-01187) whole. */
  wrap?: boolean;
  /** When set, a hover-revealed pencil opens the record's edit dialog. */
  onEdit?: () => void;
  /** Trailing success check (e.g. a verified phone/email). */
  verified?: boolean;
  /** Generic trailing node (e.g. a provenance "extracted from call" icon). */
  adornment?: React.ReactNode;
  /** Render the value as a link. */
  href?: string;
  /** Open the href in a new tab (external). */
  external?: boolean;
  /** Leading node inside the value slot (e.g. a rep avatar for "Owner"). */
  valueLeading?: React.ReactNode;
  /** A line under the value, aligned with it in either layout (e.g. the page quote a read came from). */
  note?: React.ReactNode;
  className?: string;
  testId?: string;
}

function isEmptyValue(v: React.ReactNode): boolean {
  return v === null || v === undefined || v === '';
}

export function FieldRow({
  icon: Icon,
  label,
  value,
  emptyHint = '—',
  mono,
  wrap,
  onEdit,
  verified,
  adornment,
  href,
  external,
  valueLeading,
  note,
  className,
  testId,
}: FieldRowProps) {
  const empty = isEmptyValue(value);
  const valueClass = cn(
    'flex-1 text-[13px]',
    wrap ? 'min-w-0 whitespace-normal break-words' : 'truncate',
    mono && 'font-mono text-xs tabular-nums text-muted-foreground',
    href && !empty && 'text-primary font-medium',
    empty && 'text-muted-foreground/60'
  );
  const valueNode = empty ? emptyHint : wrap && typeof value === 'string' ? <WholeTokens text={value} /> : value;
  const plain = typeof value === 'string' || typeof value === 'number' ? String(value) : undefined;

  let rendered: React.ReactNode;
  if (href && !empty) {
    rendered = external ? (
      <a href={href} target="_blank" rel="noreferrer" className={cn(valueClass, 'hover:underline')} title={plain}>
        {valueNode}
      </a>
    ) : (
      <Link href={href} className={cn(valueClass, 'hover:underline')} title={plain}>
        {valueNode}
      </Link>
    );
  } else {
    // The value truncates to one line, so the full text shows on hover.
    rendered = (
      <span className={valueClass} title={empty ? undefined : plain}>
        {valueNode}
      </span>
    );
  }

  const hasTrailing = verified || adornment || onEdit;

  return (
    // The outer box is the container the row measures; borders and padding stay on it so a caller's className still
    // overrides them. Side by side, every row is the same 36px whatever its content.
    <div className={cn('@container/field border-t border-border/40 py-1.5 first:border-t-0', className)} data-testid={testId}>
      <div className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-0.5 @md/field:min-h-6 @md/field:grid-cols-[auto_minmax(0,1fr)_auto]">
        <span className="col-start-1 row-start-1 flex min-w-0 items-center gap-2.5">
          {Icon ? <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden /> : null}
          <span
            className={cn(
              'min-w-0 text-[11px] uppercase tracking-wide text-muted-foreground @md/field:w-28 @md/field:shrink-0',
              wrap ? 'whitespace-normal break-words' : 'truncate whitespace-nowrap'
            )}
            title={label}
          >
            {label}
          </span>
        </span>
        <span className={cn('col-span-2 row-start-2 flex min-w-0 items-center gap-2.5 @md/field:col-span-1 @md/field:col-start-2 @md/field:row-start-1', Icon && 'pl-6 @md/field:pl-0')}>
          {valueLeading}
          {rendered}
        </span>
        {note ? (
          <span className={cn('col-span-2 row-start-3 min-w-0 @md/field:col-span-1 @md/field:col-start-2 @md/field:row-start-2', Icon && 'pl-6 @md/field:pl-0')}>{note}</span>
        ) : null}
        {hasTrailing ? (
          <span className="col-start-2 row-start-1 flex shrink-0 items-center gap-1.5 justify-self-end pl-1 @md/field:col-start-3">
            {verified ? <Check className="size-3.5 text-success" strokeWidth={2.4} aria-label="Verified" /> : null}
            {adornment}
            {onEdit ? (
              <button
                type="button"
                onClick={onEdit}
                aria-label={`Edit ${label}`}
                className="rounded opacity-0 transition-opacity focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100"
              >
                <Pencil className="size-3 text-muted-foreground" />
              </button>
            ) : null}
          </span>
        ) : null}
      </div>
    </div>
  );
}
