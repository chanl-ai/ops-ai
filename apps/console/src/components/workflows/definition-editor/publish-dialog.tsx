'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useWorkflowPublishPreview } from '@/hooks/engine-queries';
import type { WorkflowPublishPreview } from '@/lib/types/engine';

import { ChangesList } from './changes-list';

/** What happens once Publish is pressed, from the team's publish policy as the server read it. */
function nextStep(p: WorkflowPublishPreview): string {
  if (p.reviewRequired) return 'Needs approval from another person in Reviews before it goes live.';
  if (p.reviewReason === 'minor_change') return 'Only step positions or the workflow name changed: goes live at once.';
  return 'Your team publishes without a review: goes live at once.';
}

/**
 * Publishes the working copy: makes the next version from it and opens its review, or puts it live at once where the
 * team's policy needs none. It lists what changed against the live version and every problem that stops the publish;
 * pressing Publish while one remains moves to the list and sends nothing.
 */
export function PublishDefinitionDialog({
  open,
  onOpenChange,
  workflowId,
  nodeName,
  onFix,
  onRequest,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  nodeName: (id: string) => string;
  /** Opens a step's settings, closing the dialog. */
  onFix: (nodeId: string) => void;
  onRequest: (note: string) => Promise<unknown>;
}) {
  const preview = useWorkflowPublishPreview(workflowId, open);
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string>();
  const [pending, setPending] = React.useState(false);
  const [noteMissing, setNoteMissing] = React.useState(false);
  const problemsRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(undefined);
      setNoteMissing(false);
    }
  }, [open]);

  const p = preview.data;
  const blockers = p?.blockers ?? [];

  const submit = async () => {
    if (!p) return;
    if (blockers.length) {
      problemsRef.current?.scrollIntoView({ block: 'nearest' });
      problemsRef.current?.focus();
      return;
    }
    if (p.reviewRequired && !note.trim()) return setNoteMissing(true);
    setPending(true);
    try {
      await onRequest(note.trim());
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nothing was published');
      void preview.refetch();
    } finally {
      setPending(false);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Publish your changes"
      description={p ? (p.liveVersion ? `Makes the next version from your changes, to replace version ${p.liveVersion} for new runs. Runs under way keep their version.` : 'Makes the first version from your changes.') : undefined}
      footer={
        <>
          {p && (
            <p className="mr-auto text-xs text-muted-foreground" data-testid="definition-publish-next">
              {nextStep(p)}
            </p>
          )}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <LoadingButton type="button" onClick={submit} isLoading={pending} loadingText="Publishing…" disabled={!p} data-testid="definition-publish-submit">
            {p?.reviewRequired ? 'Send for review' : 'Publish'}
          </LoadingButton>
        </>
      }
    >
      {preview.isPending ? (
        <div className="flex flex-col gap-2" data-testid="definition-publish-loading">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : preview.isError ? (
        <QueryError what="what this publish changes" error={preview.error} onRetry={() => preview.refetch()} retrying={preview.isFetching} />
      ) : (
        p && (
          <div className="flex flex-col gap-4">
            {blockers.length > 0 && (
              <div ref={problemsRef} tabIndex={-1} className="outline-none" data-testid="definition-publish-blockers">
                <Alert variant="destructive">
                  <AlertTriangle />
                  <AlertTitle>{blockers.length === 1 ? 'Fix 1 problem to publish' : `Fix ${blockers.length} problems to publish`}</AlertTitle>
                  <AlertDescription>
                    <Rows className="w-full">
                      {blockers.map((c, i) => (
                        <Row
                          key={`${c.code}-${c.node ?? ''}-${i}`}
                          wrap
                          title={c.message}
                          description={c.node ? nodeName(c.node) : 'Whole workflow'}
                          trailing={
                            c.node ? (
                              <Button type="button" size="sm" variant="outline" onClick={() => onFix(c.node as string)} data-testid="definition-publish-fix">
                                Fix
                              </Button>
                            ) : undefined
                          }
                        />
                      ))}
                    </Rows>
                  </AlertDescription>
                </Alert>
              </div>
            )}
            <Section title="What changed" description={p.liveVersion ? `Against version ${p.liveVersion}, the live one` : 'Every step is new'} flush>
              <ChangesList diff={p.changes} />
            </Section>
            {error && <p className="text-sm text-destructive-text">{error}</p>}
            <FormField
              id="definition-publish-note"
              label="Note to the reviewer"
              optional={!p.reviewRequired}
              hint="The reviewer reads this beside the steps that changed."
              error={noteMissing ? 'Say what changed, for the reviewer' : undefined}
            >
              <Textarea id="definition-publish-note" value={note} onChange={(e) => (setNote(e.target.value), setNoteMissing(false))} rows={3} placeholder="e.g. Refunds over 100 now wait for a review" />
            </FormField>
          </div>
        )
      )}
    </DialogShell>
  );
}
