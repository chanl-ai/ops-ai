'use client';

import * as React from 'react';

import { Row, Rows, Section } from '@/components/shared/surface';
import { QueryError } from '@/components/shared/query-states';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { X } from 'lucide-react';

export interface AgentListRow {
  id: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** The key state of the row (an approval, a deprecation, how much it loaded), before Remove. */
  state?: React.ReactNode;
  /** Absent when the row cannot be taken away by this person. */
  remove?: { label: string; onClick: () => void; disabled?: boolean; reason?: string };
}

/**
 * What an agent holds, as one always-open section: the name with its count and Add in the header, then a row per item.
 * Tools, knowledge and skills all use it, so the three read alike and a fix lands in all of them.
 */
export function AgentListSection({
  id,
  icon: Icon,
  title,
  count,
  description,
  add,
  rows,
  empty,
  loading,
  error,
  children,
}: {
  id: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  count: number;
  description?: React.ReactNode;
  /** The picker that adds an item, drawn as the button in the header. */
  add?: React.ReactNode;
  rows: AgentListRow[];
  empty: string;
  loading?: boolean;
  error?: { what: string; onRetry: () => void };
  /** Under the rows: a note or a setting that belongs to the whole list. */
  children?: React.ReactNode;
}) {
  return (
    <Section
      id={id}
      flush
      title={
        <span className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" aria-hidden />
          {title}
          <span className="font-normal text-muted-foreground tabular-nums" data-testid={`${id}-count`}>
            {count}
          </span>
        </span>
      }
      description={description}
      actions={add}
    >
      {loading ? (
        <Skeleton className="m-4 h-16" />
      ) : error ? (
        <div className="p-4">
          <QueryError what={error.what} onRetry={error.onRetry} />
        </div>
      ) : rows.length ? (
        <Rows testId={`${id}-rows`}>
          {rows.map((r) => (
            <Row
              key={r.id}
              wrap
              title={r.title}
              description={r.description}
              trailing={
                <>
                  {r.state}
                  {r.remove && (
                    <DisabledReason reason={r.remove.reason}>
                      <Button type="button" variant="ghost" size="icon" disabled={r.remove.disabled} aria-label={r.remove.label} onClick={r.remove.onClick}>
                        <X className="size-4" />
                      </Button>
                    </DisabledReason>
                  )}
                </>
              }
            />
          ))}
        </Rows>
      ) : (
        <p className="p-4 text-sm text-muted-foreground">{empty}</p>
      )}
      {children}
    </Section>
  );
}
