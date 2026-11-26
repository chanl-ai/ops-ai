'use client';

import * as React from 'react';
import { Check, Search } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

/** What a server-searched, paged list hands the dialog; `useServerList` returns exactly this. */
export interface SearchAddQuery<T> {
  rows: T[];
  total?: number;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isFetching: boolean;
  /** The search typed is not what the rows answer yet. */
  searching: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
  refetch: () => unknown;
}

export interface SearchAddDialogProps<T> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  searchLabel: string;
  search: string;
  onSearchChange: (text: string) => void;
  query: SearchAddQuery<T>;
  /** What the list is called in "Couldn’t load templates" and "No templates match". */
  what: string;
  /** Shown when nothing exists at all, with no search typed. */
  empty: React.ReactNode;
  rowKey: (row: T) => string;
  rowTitle: (row: T) => React.ReactNode;
  rowDescription?: (row: T) => React.ReactNode;
  /** The chosen row, drawn beside the list (under it on a phone). */
  preview: (row: T) => React.ReactNode;
  /** Adds the row; the dialog stays open on a refusal and the caller closes it on success. */
  onAdd: (row: T) => Promise<unknown>;
  addLabel?: string;
  /** Whether the person may add this row; a row they may not add says why in the preview and the button is off. */
  canAdd?: (row: T) => boolean;
  /** The id the test finds the dialog by. */
  testId?: string;
}

/**
 * One search-and-add dialog for the library pickers: one search field the server answers (paged, "Show more"), a list
 * where one row is chosen, a preview of the chosen row, and the add button. Loading, empty, nothing-matched and error
 * each have their own state. The caller owns the query and the add, so any kind of row fits.
 */
export function SearchAddDialog<T>({ open, onOpenChange, title, description, searchLabel, search, onSearchChange, query, what, empty, rowKey, rowTitle, rowDescription, preview, onAdd, addLabel = 'Add', canAdd, testId = 'search-add-dialog' }: SearchAddDialogProps<T>) {
  const [chosenKey, setChosenKey] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  React.useEffect(() => {
    if (open) setChosenKey(null);
  }, [open]);
  const chosen = query.rows.find((r) => rowKey(r) === chosenKey) ?? null;
  const add = async () => {
    if (!chosen) return;
    setAdding(true);
    try {
      await onAdd(chosen);
    } finally {
      setAdding(false);
    }
  };
  const typed = search.trim().length > 0;
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={title}
      description={description}
      data-testid={testId}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={adding}>
            Cancel
          </Button>
          <LoadingButton isLoading={adding} disabled={!chosen || (canAdd ? !canAdd(chosen) : false)} onClick={() => void add()} data-testid={`${testId}-add`}>
            {addLabel}
          </LoadingButton>
        </div>
      }
    >
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input value={search} onChange={(e) => onSearchChange(e.target.value)} placeholder={`Search ${what}`} aria-label={searchLabel} className="pl-8" data-testid={`${testId}-search`} />
      </div>
      {query.isPending ? (
        <div className="space-y-2" role="status" aria-label={`Loading ${what}`}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <QueryError what={what} error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
      ) : query.rows.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground" data-testid={`${testId}-empty`}>
          {typed ? `No ${what} match “${search.trim()}”.` : empty}
        </div>
      ) : (
        <div className={cn('grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]', query.searching && 'opacity-70')}>
          <div className="flex min-w-0 flex-col">
            <ul role="listbox" aria-label={what} className="min-w-0 divide-y rounded-lg border" data-testid={`${testId}-list`}>
              {query.rows.map((r) => {
                const key = rowKey(r);
                const on = key === chosenKey;
                return (
                  <li key={key} role="option" aria-selected={on}>
                    <button type="button" onClick={() => setChosenKey(key)} className={cn('flex w-full min-w-0 items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50', on && 'bg-accent')} data-testid={`${testId}-row`}>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{rowTitle(r)}</span>
                        {rowDescription && <span className="block truncate text-xs text-muted-foreground">{rowDescription(r)}</span>}
                      </span>
                      {on && <Check className="size-4 shrink-0" aria-hidden />}
                    </button>
                  </li>
                );
              })}
            </ul>
            {query.hasNextPage && (
              <LoadingButton variant="ghost" size="sm" className="mt-2 self-center" isLoading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()} data-testid={`${testId}-more`}>
                Show more
              </LoadingButton>
            )}
          </div>
          <div className="min-w-0 rounded-lg border bg-muted/30 p-4" data-testid={`${testId}-preview`}>
            {chosen ? preview(chosen) : <p className="text-sm text-muted-foreground">Choose one to see what it brings.</p>}
          </div>
        </div>
      )}
    </DialogShell>
  );
}
