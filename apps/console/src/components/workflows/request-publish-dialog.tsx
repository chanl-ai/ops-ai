'use client';

import * as React from 'react';
import { AlertTriangle, CheckCircle2, Minus, PenLine, Plus, XCircle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import type { ValidationRun } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

import type { GraphIssue } from './graph-checks';
import type { diffGraphs } from './graph-diff';
import { plural } from '@/lib/format';

/**
 * Validate, then send for approval. Validation is advisory: failures and regressions are shown and travel
 * with the request to the reviewer, but they never block the request.
 */
export function RequestPublishDialog({
  open,
  onOpenChange,
  nextVersion,
  firstPublish,
  diff,
  issues,
  validation,
  validating,
  validationError,
  onRevalidate,
  onRequest,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nextVersion: number;
  firstPublish: boolean;
  diff: ReturnType<typeof diffGraphs>;
  issues: GraphIssue[];
  validation?: ValidationRun;
  validating: boolean;
  validationError?: string | null;
  onRevalidate: () => void;
  onRequest: (note: string) => Promise<unknown>;
  isPending: boolean;
}) {
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(null);
    }
  }, [open]);

  const changes = [
    ...diff.added.map((n) => ({ icon: Plus, cls: 'text-emerald-600', text: `Added ${n.data.label}` })),
    ...diff.changed.map((n) => ({ icon: PenLine, cls: 'text-sky-600', text: `Changed ${n.data.label}` })),
    ...diff.removed.map((n) => ({ icon: Minus, cls: 'text-red-600', text: `Removed ${n.data.label}` })),
    ...diff.config.map((text) => ({ icon: PenLine, cls: 'text-sky-600', text })),
  ];
  const s = validation?.summary;
  const errorCount = issues.filter((i) => i.severity === 'error').length;

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={firstPublish ? `Request first publish (v${nextVersion})` : `Request publish of v${nextVersion}`}
      description={firstPublish ? 'Tests run against this draft. The request goes to the Reviews queue; another publisher approves it.' : 'Tests run against this draft and the live version. The request goes to the Reviews queue; another publisher approves it.'}
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <span className={cn('text-xs', errorCount ? 'font-medium text-destructive' : 'text-muted-foreground')}>
            {errorCount ? `Fix ${errorCount} error${errorCount === 1 ? '' : 's'} on the canvas before requesting.` : 'Test results are advisory and travel with the request.'}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={isPending}
              disabled={validating || errorCount > 0}
              loadingText="Sending…"
              onClick={async () => {
                if (note.trim().length < 4) return setError('Describe the change in a few words; the approver reads it first.');
                try {
                  await onRequest(note.trim());
                  onOpenChange(false);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Request publish
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-4">
          <FormField id="pub-note" label="What changed" error={error ?? undefined}>
            <Input id="pub-note" autoFocus value={note} onChange={(e) => (setNote(e.target.value), setError(null))} placeholder="Raised the analyst SLA to 30 min" aria-invalid={!!error} />
          </FormField>
          <div className="rounded-lg border">
            <div className="border-b px-3 py-2 text-sm font-medium">{firstPublish ? 'First publish' : `Changes since v${nextVersion - 1}`}</div>
            {firstPublish ? (
              <p className="px-3 py-3 text-sm text-muted-foreground">Nothing is live yet; every step ships.</p>
            ) : changes.length === 0 && diff.rewired === 0 ? (
              <p className="px-3 py-3 text-sm text-muted-foreground">Only positions changed.</p>
            ) : (
              <ul className="flex max-h-40 flex-col gap-1.5 overflow-y-auto px-3 py-2.5 text-sm">
                {changes.map((c, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <c.icon className={cn('size-3.5', c.cls)} /> {c.text}
                  </li>
                ))}
                {diff.rewired > 0 && <li className="text-muted-foreground">{plural(diff.rewired, 'connection')} rewired</li>}
              </ul>
            )}
          </div>
          <div className="rounded-lg border">
            <div className="border-b px-3 py-2 text-sm font-medium">Checks · {issues.length ? `${issues.length} not passing` : 'all passing'}</div>
            {issues.length === 0 ? (
              <p className="flex items-center gap-2 px-3 py-3 text-sm text-emerald-700 dark:text-emerald-400">
                <CheckCircle2 className="size-4" /> Every step is wired and configured.
              </p>
            ) : (
              <ul className="flex max-h-40 flex-col gap-1.5 overflow-y-auto px-3 py-2.5 text-sm">
                {issues.map((i, k) => (
                  <li key={k} className="flex items-start gap-2">
                    <AlertTriangle className={cn('mt-0.5 size-3.5 shrink-0', i.severity === 'error' ? 'text-red-600' : 'text-amber-600')} /> {i.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-col rounded-lg border" data-testid="validation-results">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-medium">Tests</span>
            <Button variant="ghost" size="sm" className="h-7" onClick={onRevalidate} disabled={validating}>
              Run again
            </Button>
          </div>
          {validating ? (
            <div className="flex flex-col gap-2 p-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : validationError ? (
            <p className="p-3 text-sm text-destructive">Tests could not run: {validationError}</p>
          ) : !validation || s?.total === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">This workflow has no test cases. Add them on the Tests tab so approvers can see how a change behaves.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-b px-3 py-2 text-sm">
                <span>
                  <span className="font-semibold tabular-nums">{s!.passed}</span>/{s!.total} pass on draft
                </span>
                {!firstPublish && (
                  <span className={cn(s!.regressions ? 'font-medium text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                    {s!.regressions} regression{s!.regressions === 1 ? '' : 's'} vs live
                  </span>
                )}
              </div>
              <ul className="flex max-h-72 flex-col divide-y overflow-y-auto">
                {validation.results.map((r) => (
                  <li key={r.caseId} className={cn('flex items-start gap-2 px-3 py-2 text-sm', r.regression && 'bg-red-500/5')}>
                    {r.draft.passed ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{r.caseName}</div>
                      {r.draft.failure && <div className="text-xs text-red-600 dark:text-red-400">{r.draft.failure}</div>}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{r.regression ? 'Passed on live' : r.live ? (r.live.passed ? 'Live: pass' : 'Live: fail') : ''}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </DialogShell>
  );
}
