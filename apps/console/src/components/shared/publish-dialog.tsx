'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { plural } from '@/lib/format';
import type { Blocker } from '@/lib/types/references';

/** A blocker as a check returns it; a workflow's carries a free-text `level`. */
export type BlockerRow = Pick<Blocker, 'node' | 'code' | 'message'> & { field?: string | null; level?: string };

/**
 * The one publish dialog for an agent, a skill and a workflow: the title and a line on what happens, what the page
 * adds (what changed, test results), every blocker from the one `Blocker` shape with a way to jump to it, a note, and
 * the one submit. Submit stays off while an error-level blocker remains. A blocker that names a step (`node`) or a
 * field jumps there through `onJump`; the page closes the dialog and moves.
 */
export function PublishDialog({
  open,
  onOpenChange,
  title,
  description,
  size = 'md',
  blockers,
  where,
  onJump,
  rowAction,
  loading,
  loadError,
  children,
  note,
  nextStep,
  submitLabel,
  submittingLabel,
  submitTestId,
  disabled,
  pending,
  onSubmit,
  testId = 'publish',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg';
  blockers: BlockerRow[];
  /** Names where a blocker is (a step's name, a heading); the default is its field, or the whole thing. */
  where?: (b: BlockerRow) => string | null;
  /** Jumps to the step or field a blocker names. Not offered for a blocker that names neither. */
  onJump?: (b: BlockerRow) => void;
  /** Anything else a blocker's row offers, such as Add it back. */
  rowAction?: (b: BlockerRow, index: number) => React.ReactNode;
  loading?: React.ReactNode;
  loadError?: React.ReactNode;
  children?: React.ReactNode;
  note: { label: string; hint?: string; placeholder?: string; multiline?: boolean; required: boolean; missing: string; minLength?: number };
  nextStep?: string;
  submitLabel: string;
  submittingLabel: string;
  submitTestId: string;
  /** Holds Submit for a reason the dialog does not know (the preview is not read yet). */
  disabled?: boolean;
  pending?: boolean;
  onSubmit: (note: string) => Promise<unknown>;
  testId?: string;
}) {
  const [text, setText] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [noteError, setNoteError] = React.useState<string | null>(null);
  const [sending, setSending] = React.useState(false);
  React.useEffect(() => {
    if (open) {
      setText('');
      setError(null);
      setNoteError(null);
    }
  }, [open]);

  const errors = blockers.filter((b) => b.level !== 'warning');
  const warnings = blockers.filter((b) => b.level === 'warning');
  const busy = sending || !!pending;
  const submit = async () => {
    if (note.required && text.trim().length < (note.minLength ?? 1)) return setNoteError(note.missing);
    setSending(true);
    try {
      await onSubmit(text.trim());
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nothing was published');
    } finally {
      setSending(false);
    }
  };
  const field = { id: `${testId}-note`, value: text, onChange: (v: string) => (setText(v), setNoteError(null)), placeholder: note.placeholder };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !sending && onOpenChange(o)}
      size={size}
      title={title}
      description={description}
      footer={
        <>
          {nextStep && (
            <p className="mr-auto text-xs text-muted-foreground" data-testid={`${testId}-next`}>
              {nextStep}
            </p>
          )}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={sending}>
            Cancel
          </Button>
          <LoadingButton type="button" onClick={() => void submit()} isLoading={busy} loadingText={submittingLabel} disabled={!!disabled || !!loading || !!loadError || errors.length > 0} title={errors.length ? 'Fix the problems listed first' : undefined} data-testid={submitTestId}>
            {submitLabel}
          </LoadingButton>
        </>
      }
    >
      {loading ?? loadError ?? (
        <div className="flex flex-col gap-4">
          {errors.length > 0 && (
            <div data-testid={`${testId}-blockers`}>
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertTitle>Fix {plural(errors.length, 'problem')} to publish</AlertTitle>
                <AlertDescription>
                  <Rows className="w-full">
                    {errors.map((b, i) => {
                      const at = where?.(b) ?? b.field ?? (b.node ? null : 'Whole page');
                      return (
                        <Row
                          key={`${b.code}-${b.node ?? ''}-${b.field ?? ''}-${i}`}
                          wrap
                          title={b.message}
                          description={at ?? undefined}
                          trailing={
                            <>
                              {rowAction?.(b, i)}
                              {onJump && (b.node || b.field) && (
                                <Button type="button" size="sm" variant="outline" onClick={() => onJump(b)} data-testid={`${testId}-fix`}>
                                  Fix
                                </Button>
                              )}
                            </>
                          }
                        />
                      );
                    })}
                  </Rows>
                </AlertDescription>
              </Alert>
            </div>
          )}
          {warnings.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-md border border-warning/30 bg-warning/5 p-3 text-sm text-warning-text" data-testid={`${testId}-warnings`}>
              <li className="font-medium">Does not block the publish</li>
              {warnings.map((w, i) => (
                <li key={`${w.code}-${i}`}>{w.message}</li>
              ))}
            </ul>
          )}
          {children}
          {error && <p className="text-sm text-destructive-text">{error}</p>}
          <FormField id={field.id} label={note.label} optional={!note.required} hint={note.hint} error={noteError ?? undefined}>
            {note.multiline ? (
              <Textarea id={field.id} value={field.value} onChange={(e) => field.onChange(e.target.value)} rows={3} placeholder={field.placeholder} aria-invalid={!!noteError} />
            ) : (
              <Input id={field.id} autoFocus value={field.value} onChange={(e) => field.onChange(e.target.value)} placeholder={field.placeholder} aria-invalid={!!noteError} />
            )}
          </FormField>
        </div>
      )}
    </DialogShell>
  );
}
