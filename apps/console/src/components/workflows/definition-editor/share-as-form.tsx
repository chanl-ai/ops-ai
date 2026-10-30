'use client';

import * as React from 'react';
import { Download, Link2, RefreshCw } from 'lucide-react';
import QRCode from 'qrcode';

import { CopyButton } from '@/components/shared/copy-button';
import { FormField, FormFieldGroup } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Section } from '@/components/shared/surface';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useCreateForm, useFormPageUrl, useRotateForm, useUpdateForm, useWorkflowForms } from '@/hooks/form-queries';
import { count, shortDate } from '@/lib/format';
import type { HostedFormLink, HostedFormMode } from '@/lib/types/forms';
import { cn } from '@/lib/utils';

type InputSchema = { title?: string; description?: string; properties?: Record<string, unknown> };

const MODES: { mode: HostedFormMode; title: string; hint: string }[] = [
  { mode: 'link', title: 'Anyone with the link', hint: 'A signed link that stops working when it expires or is rotated' },
  { mode: 'members', title: 'Team members, signed in', hint: 'Opens in Ops AI after sign-in; the run starts as that person' },
];
const THANKS = 'Thank you. We will reply by email within two working days.';

/**
 * Share as a form on a Request trigger (c-535): the workflow's start form on a page of its own, for anyone holding a
 * signed link (the embed app) or for the team's signed-in members (the console). A link's token is shown once, in the
 * answer that made it; the list never holds it, so a link made earlier is got again by rotating it.
 */
export function ShareAsForm({ workflowId, schema: raw, readOnly }: { workflowId: string; schema: Record<string, unknown>; readOnly: boolean }) {
  const schema = raw as InputSchema;
  const forms = useWorkflowForms(workflowId);
  const create = useCreateForm(workflowId);
  const [open, setOpen] = React.useState(false);
  // The just-made or just-rotated answer of each form, the only ones that carry a link's token.
  const [fresh, setFresh] = React.useState<Record<string, HostedFormLink>>({});
  const [mode, setMode] = React.useState<HostedFormMode>('link');
  const [days, setDays] = React.useState('30');
  const [cap, setCap] = React.useState('200');
  const [after, setAfter] = React.useState(THANKS);
  const [error, setError] = React.useState<string | null>(null);
  const noInputs = Object.keys(schema.properties ?? {}).length === 0;
  const daysN = Number(days);
  const capN = Number(cap);
  const badDays = mode === 'link' && (!Number.isInteger(daysN) || daysN < 1 || daysN > 90) ? 'From 1 to 90 days.' : undefined;
  const badCap = !Number.isInteger(capN) || capN < 1 || capN > 10000 ? 'From 1 to 10,000 a day.' : undefined;

  const share = async () => {
    setError(null);
    try {
      const made = await create.mutateAsync({
        mode,
        ...(mode === 'link' ? { expiresInDays: daysN } : {}),
        dailyCap: capN,
        // The page shows the start form's own title when it has one, else the server uses the workflow's name.
        ...(schema.title ? { title: schema.title } : {}),
        ...(schema.description ? { description: schema.description } : {}),
        afterText: after.trim(),
      });
      setFresh((f) => ({ ...f, [made.id]: made }));
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The form could not be shared.');
    }
  };

  const list = forms.data ?? [];
  return (
    <div data-testid="trigger-share-form">
      <Section
        title="Share as a form"
        description="People fill this workflow’s start form on a page of its own, and each send starts a run."
        actions={
          !readOnly && (
            <Button type="button" variant="outline" size="sm" disabled={noInputs} onClick={() => setOpen(true)} data-testid="share-as-form">
              <Link2 /> Share as a form
            </Button>
          )
        }
      >
        <div className="flex min-w-0 flex-col gap-5">
          {noInputs && <p className="text-sm text-muted-foreground">Add the fields people fill in to the run input first: a form needs at least one.</p>}
          {open && !noInputs && (
            <div className="flex min-w-0 flex-col gap-4 rounded-md border p-3" data-testid="share-form-settings">
              <FormFieldGroup label="Who can send it">
                <RadioGroup value={mode} onValueChange={(m) => setMode(m as HostedFormMode)} className="grid gap-2">
                  {MODES.map((m) => (
                    <label key={m.mode} htmlFor={`form-mode-${m.mode}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', mode === m.mode && 'border-primary bg-primary/5')}>
                      <RadioGroupItem value={m.mode} id={`form-mode-${m.mode}`} className="mt-0.5" />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{m.title}</span>
                        <span className="block text-xs text-muted-foreground">{m.hint}</span>
                      </span>
                    </label>
                  ))}
                </RadioGroup>
              </FormFieldGroup>
              <div className="grid gap-4 sm:grid-cols-2">
                {mode === 'link' && (
                  <FormField id="form-expiry" label="Link expires in (days)" hint="From 1 to 90 days." error={badDays}>
                    <Input id="form-expiry" type="number" inputMode="numeric" min={1} max={90} value={days} aria-invalid={!!badDays} onChange={(e) => setDays(e.target.value)} />
                  </FormField>
                )}
                <FormField id="form-cap" label="Submissions a day" hint="And at most 10 a minute from one address." error={badCap}>
                  <Input id="form-cap" type="number" inputMode="numeric" min={1} value={cap} aria-invalid={!!badCap} onChange={(e) => setCap(e.target.value)} />
                </FormField>
              </div>
              <FormField id="form-thanks" label="After sending, show" optional>
                <Textarea id="form-thanks" rows={2} value={after} maxLength={1000} onChange={(e) => setAfter(e.target.value)} />
              </FormField>
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => (setOpen(false), setError(null))}>
                  Cancel
                </Button>
                <LoadingButton type="button" isLoading={create.isPending} loadingText="Sharing…" disabled={!!badDays || !!badCap} onClick={() => void share()}>
                  Share
                </LoadingButton>
              </div>
            </div>
          )}
          {forms.isError && <p className="text-sm text-destructive">The shared forms could not be loaded. {forms.error instanceof Error ? forms.error.message : ''}</p>}
          {forms.isSuccess && list.length === 0 && !open && !noInputs && <p className="text-sm text-muted-foreground">Not shared yet.</p>}
          {list.map((f) => (
            <SharedForm key={f.id} form={fresh[f.id] ?? f} paused={f.paused} readOnly={readOnly} onRotated={(r) => setFresh((x) => ({ ...x, [r.id]: r }))} />
          ))}
        </div>
      </Section>
    </div>
  );
}

// Medium error correction survives a printed code that is a little smudged; the margin is the quiet zone scanners need.
const QR = { margin: 1, width: 224, errorCorrectionLevel: 'M' } as const;

/** The link as a QR code, drawn in the browser so the link never leaves it, with a PNG to print or paste. */
function LinkQr({ url, slug }: { url: string; slug: string }) {
  const [src, setSrc] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    QRCode.toDataURL(url, QR).then(
      (made) => live && setSrc(made),
      () => live && setSrc(null),
    );
    return () => {
      live = false;
    };
  }, [url]);
  if (!src) return null;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <img src={src} alt="QR code of the link" width={112} height={112} className="rounded-md border bg-white" data-testid="form-qr" />
      <a href={src} download={`${slug}-qr.png`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        <Download /> Download QR code
      </a>
    </div>
  );
}

/** One shared form: its link with Copy and its QR code, Rotate (asks first) and whether it takes submissions. */
function SharedForm({ form, paused, readOnly, onRotated }: { form: HostedFormLink; paused: boolean; readOnly: boolean; onRotated: (f: HostedFormLink) => void }) {
  const pageUrl = useFormPageUrl();
  const rotate = useRotateForm();
  const update = useUpdateForm();
  const [asking, setAsking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const members = form.mode === 'members';
  const url = members ? (typeof window === 'undefined' ? `/forms/${form.slug}` : `${window.location.origin}/forms/${encodeURIComponent(form.slug)}`) : form.token ? pageUrl(form) : null;
  const id = `form-link-${form.id}`;

  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-md border p-3" data-testid="shared-form">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="min-w-0 truncate text-sm font-medium">{form.title}</span>
        <Badge variant="outline">{members ? 'Team members' : 'Anyone with the link'}</Badge>
        {paused && <Badge variant="secondary">Paused</Badge>}
      </div>
      {url ? (
        <FormField id={id} label="Link">
          <div className="flex min-w-0 items-center gap-2">
            <Input id={id} readOnly value={url} className="min-w-0 flex-1 font-mono text-xs" onFocus={(e) => e.target.select()} data-testid="form-link" />
            <CopyButton text={url} variant="outline" />
          </div>
          <LinkQr url={url} slug={form.slug} />
        </FormField>
      ) : (
        <p className="text-sm text-muted-foreground">The link is shown once, when it is made. Rotate it to get a new one; the old link then stops working.</p>
      )}
      <p className="text-xs text-muted-foreground">
        {members ? 'Signed-in members of this team can send it.' : `Expires ${shortDate(form.expiresAt)}.`} At most {count(form.dailyCap)} a day. Refused sends show in Activity with the reason.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!readOnly && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={!paused}
              disabled={update.isPending}
              aria-label="Taking submissions"
              onCheckedChange={(on) => {
                setError(null);
                update.mutate({ id: form.id, patch: { paused: !on } }, { onError: (e) => setError(e.message) });
              }}
            />
            Taking submissions
          </label>
          {!members && (
            <LoadingButton type="button" variant="outline" size="sm" isLoading={rotate.isPending} loadingText="Rotating…" className="text-destructive" onClick={() => setAsking(true)} data-testid="form-rotate">
              <RefreshCw /> Rotate link
            </LoadingButton>
          )}
        </div>
      )}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Rotate the link?</AlertDialogTitle>
            <AlertDialogDescription>The current link stops working at once. Anyone you sent it to needs the new one.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: 'destructive' })}
              onClick={() => {
                setError(null);
                rotate.mutate(form, { onSuccess: onRotated, onError: (e) => setError(e.message) });
              }}
            >
              Rotate link
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
