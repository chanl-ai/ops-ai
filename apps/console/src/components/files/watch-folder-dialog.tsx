'use client';

import * as React from 'react';
import Link from 'next/link';
import { ExternalLink, Users } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { KeyValues, Section } from '@/components/shared/surface';
import { SourceScopeStep, useSourceScopePreview } from '@/components/sources/source-scope-step';
import { initialValues, valueErrors } from '@/components/sources/source-values-form';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { type Watch, useChangeWatch, useCreateWatch, useCheckWatch } from '@/hooks/file-queries';
import { useSourceKinds } from '@/hooks/knowledge-queries';
import { appPageHref } from '@/lib/app-links';
import { count } from '@/lib/format';
import type { SourceKindOption } from '@/lib/types/knowledge';

const STEPS = ['Source', 'What to include', 'Review'] as const;

/**
 * The app sources whose items are files. Knowledge lists every source an app offers; a watch copies each item's bytes
 * into Files, so only the ones that hold files are offered (an app that adds another, such as S3, names it here).
 */
const FILE_SOURCES = ['files'];
const watchable = (k: SourceKindOption) => k.type === 'tool' && !k.site && !!k.pickers && !!k.source && FILE_SOURCES.includes(k.source);
const kindKey = (k: SourceKindOption) => `${k.plugin}/${k.source}`;

/** A value as one line of the Review: lists joined, switches as on or off, nothing as a dash. */
function shown(v: unknown) {
  if (Array.isArray(v)) return v.filter((x) => String(x).trim()).join(', ') || '—';
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  return v === undefined || v === null || v === '' ? '—' : String(v);
}

/**
 * Watch a folder in three steps, drawn like Knowledge's Add source: the name and the app connection, what to include
 * (the same fields and live preview, `SourceScopeStep`), then a review that says who will read the files. With `watch`
 * it changes that watch's name and folders instead; the connection stays. Closing with changes asks first.
 */
export function WatchFolderDialog({ open, onOpenChange, watch }: { open: boolean; onOpenChange: (o: boolean) => void; watch?: Watch }) {
  const kinds = useSourceKinds(open);
  const create = useCreateWatch();
  const change = useChangeWatch();
  const check = useCheckWatch();
  const [step, setStep] = React.useState(1);
  const [key, setKey] = React.useState<string | null>(null);
  const [name, setName] = React.useState('');
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [attempted, setAttempted] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const [confirmClose, setConfirmClose] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  const options = (kinds.data ?? []).filter(watchable);
  const usable = options.filter((k) => !(k.needsConnection && !k.connected) && k.canCreate !== false);
  const kind = options.find((k) => (watch ? k.plugin === watch.plugin && k.source === watch.source : kindKey(k) === key)) ?? null;
  const inputs = kind?.type === 'tool' ? (kind.inputs ?? {}) : {};
  const errors = valueErrors(inputs, values);
  // An empty required field is said once Next was pressed; a malformed value is said as it is typed.
  const shownErrors = Object.fromEntries(Object.entries(errors).filter(([n]) => attempted || !(values[n] === undefined || values[n] === '' || (Array.isArray(values[n]) && !(values[n] as unknown[]).length))));
  const valid = Object.keys(errors).length === 0;
  const nameError = name.trim().length < 2 || name.trim().length > 80 ? 'Name it in 2 to 80 characters.' : undefined;
  const preview = useSourceScopePreview(kind, values, step >= 2);

  // Opened afresh each time: a watch opens on its folders with its own values, a new one on step 1.
  React.useEffect(() => {
    if (!open) return;
    setStep(watch ? 2 : 1);
    setName(watch?.name ?? '');
    setValues((watch?.values as Record<string, unknown> | undefined) ?? {});
    setKey(null);
    setAttempted(false);
    setError(undefined);
  }, [open, watch]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);
  // With one connection to choose from, it is chosen (a new watch only).
  React.useEffect(() => {
    if (!open || watch || key || usable.length !== 1) return;
    setKey(kindKey(usable[0]));
    setValues(initialValues(usable[0].inputs ?? {}));
  }, [open, watch, key, usable]);

  const dirty = watch ? JSON.stringify(values) !== JSON.stringify(watch.values) || name !== watch.name : !!key && (name !== '' || Object.keys(values).length > 0);
  const busy = create.isPending || change.isPending;
  const close = (o: boolean) => {
    if (o) return onOpenChange(true);
    if (busy) return;
    if (dirty) return setConfirmClose(true);
    onOpenChange(false);
  };

  const choose = (k: string) => {
    const next = options.find((o) => kindKey(o) === k);
    if (!next || k === key) return;
    setKey(k);
    setValues(initialValues(next.inputs ?? {}));
  };
  const toScope = () => {
    setAttempted(true);
    if (nameError || !kind) return;
    setStep(2);
  };
  const toReview = () => {
    setAttempted(true);
    if (!valid) return;
    setStep(3);
  };

  const submit = async () => {
    if (!kind) return;
    setError(undefined);
    try {
      if (watch) {
        await change.mutateAsync({ id: watch.id, name: name.trim(), values: values as never });
        toast.success(`Changed ${name.trim()}`, { description: 'New folders are listed whole on the next check.' });
      } else {
        const made = await create.mutateAsync({ name: name.trim(), plugin: kind.plugin!, source: kind.source!, values: values as never });
        toast.success(`Watching ${made.name}`, {
          description: 'Nothing is copied until the first check.',
          action: { label: 'Check now', onClick: () => void check.mutateAsync(made.id).catch((e: Error) => toast.error(e.message)) },
        });
      }
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toConnect = options.filter((k) => k.needsConnection && !k.connected && k.cannotCreateCode !== 'sign_in_not_team' && !!k.plugin);
  const noConnection = !kinds.isPending && !kinds.isError && usable.length === 0;

  const footer = (
    <div className="flex w-full items-center justify-end gap-2">
      {error && <p className="mr-auto text-xs text-destructive-text" data-testid="watch-error">{error}</p>}
      {step === 1 ? (
        <Button variant="outline" onClick={() => close(false)}>
          Cancel
        </Button>
      ) : (
        <Button variant="outline" onClick={() => setStep(step - 1)} disabled={busy}>
          Back
        </Button>
      )}
      {step === 1 && (
        <Button onClick={toScope} disabled={!kind} title={noConnection ? 'Connect an app first' : undefined} data-testid="watch-next">
          {noConnection ? 'Next (connect an app first)' : 'Next'}
        </Button>
      )}
      {step === 2 && (
        <Button onClick={toReview} data-testid="watch-next">
          Next
        </Button>
      )}
      {step === 3 && (
        <LoadingButton isLoading={busy} loadingText="Saving…" onClick={submit} data-testid="watch-create">
          {watch ? 'Save folders' : 'Watch folder'}
        </LoadingButton>
      )}
    </div>
  );

  return (
    <>
      <DialogShell
        open={open}
        onOpenChange={close}
        size="lg"
        title={watch ? 'Change folders' : 'Watch a folder'}
        description="Files keeps one entry per file in these folders and a version each time its content changes."
        headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="watch-stepper" />}
        footer={footer}
        bodyRef={bodyRef}
        panelClassName="sm:h-[min(44rem,90vh)]"
        data-testid="watch-folder-dialog"
      >
        {step === 1 && (
          <div className="flex flex-col gap-5">
            <FormField id="wf-name" label="Name" error={attempted ? nameError : undefined}>
              <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Supplier invoices" maxLength={80} aria-invalid={attempted && !!nameError} data-testid="watch-name" />
            </FormField>
            {kinds.isPending ? (
              <p className="text-sm text-muted-foreground">Loading the apps that can list files…</p>
            ) : kinds.isError ? (
              <div className="flex flex-col items-start gap-2 text-sm">
                <p className="text-destructive-text">Couldn’t load the apps: {kinds.error.message}</p>
                <Button variant="outline" size="sm" onClick={() => kinds.refetch()}>
                  Try again
                </Button>
              </div>
            ) : noConnection ? (
              <Alert data-testid="watch-no-connection">
                <AlertTitle>No connection can list files</AlertTitle>
                <AlertDescription className="flex flex-col items-start gap-2">
                  <span>Connect an app that holds files, such as SharePoint, on the Apps page first. Next stays disabled until one is connected.</span>
                  {toConnect.map((k) => (
                    <Link key={kindKey(k)} href={appPageHref(`plugin:${k.plugin}`)} className="inline-flex items-center gap-1 text-foreground underline underline-offset-4" data-testid="watch-connect-link">
                      Connect {k.title} on its app page <ExternalLink className="size-3" />
                    </Link>
                  ))}
                  {!toConnect.length && (
                    <Link href="/data/connectors" className="inline-flex items-center gap-1 text-foreground underline underline-offset-4" data-testid="watch-connect-link">
                      Open Apps <ExternalLink className="size-3" />
                    </Link>
                  )}
                </AlertDescription>
              </Alert>
            ) : (
              <FormField id="wf-connection" label="Connection" hint={watch ? 'A watch keeps its connection; add a new watch to use another.' : 'The app account that lists the files.'}>
                <Select value={watch && kind ? kindKey(kind) : (key ?? '')} onValueChange={choose} disabled={!!watch}>
                  <SelectTrigger id="wf-connection" className="w-full" data-testid="watch-connection">
                    <SelectValue placeholder="Choose a connection" />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((k) => (
                      <SelectItem key={kindKey(k)} value={kindKey(k)} disabled={(k.needsConnection && !k.connected) || k.canCreate === false}>
                        {k.title}
                        {(k.needsConnection && !k.connected) || k.canCreate === false ? ' (not connected)' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            )}
          </div>
        )}

        {step === 2 && kind && (
          <SourceScopeStep idPrefix="wf" kind={kind} values={values} onChange={setValues} errors={shownErrors} valid={valid} preview={preview} storedNote="Nothing is copied until a check runs." />
        )}

        {step === 3 && kind && (
          <div className="flex flex-col gap-4">
            <Section title="Watch" actions={<EditLink onClick={() => setStep(1)} />}>
              <KeyValues rows={[['Name', name.trim()], ['Connection', kind.title]]} />
            </Section>
            <Section title="What to include" actions={<EditLink onClick={() => setStep(2)} />}>
              <KeyValues
                rows={[
                  ...Object.keys(inputs).map((n): [string, React.ReactNode] => [n.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()), shown(values[n])]),
                  ['First check', preview.data ? `${count(preview.data.found)} files found, ${count(preview.data.willFetch)} will be brought in` : 'Not previewed'],
                ]}
              />
            </Section>
            <Alert data-testid="watch-team-notice">
              <Users className="size-4" />
              <AlertTitle>Everyone on the team can read these files</AlertTitle>
              <AlertDescription>
                Files records who may see each file in {kind.title.split(' ')[0]} but does not apply it yet. Pick folders the whole team may see.
              </AlertDescription>
            </Alert>
          </div>
        )}
      </DialogShell>

      <AlertDialog open={confirmClose} onOpenChange={setConfirmClose}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard these changes?</AlertDialogTitle>
            <AlertDialogDescription>Nothing is saved until you finish the last step. Closing now discards what you chose.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction className={buttonVariants({ variant: 'destructive' })} onClick={() => onOpenChange(false)} data-testid="watch-discard">
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function EditLink({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}>
      Edit
    </Button>
  );
}
