'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { SettingsLookups, WebhookInput } from '@/lib/types/settings';

/** Adds a webhook for the current team. The signing secret is shown on the webhook after it is created. */
export function WebhookDialog({
  open,
  onOpenChange,
  events,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  events: SettingsLookups['webhookEvents'];
  onSubmit: (input: WebhookInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [name, setName] = React.useState('');
  const [url, setUrl] = React.useState('');
  const [picked, setPicked] = React.useState<string[]>([]);
  const [error, setError] = React.useState<{ field?: string; message: string } | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setName('');
    setUrl('');
    setPicked([]);
    setError(null);
  }, [open]);
  const err = (f: string) => (error?.field === f ? error.message : undefined);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Add webhook"
      description="Ops AI posts a signed JSON body to this URL for each event you pick, and retries failures three times."
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <p className="text-xs text-destructive">{error && !error.field ? error.message : ''}</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={isPending}
              onClick={async () => {
                if (!name.trim()) return setError({ field: 'name', message: 'Name the webhook.' });
                if (!/^https:\/\//.test(url.trim())) return setError({ field: 'url', message: 'Use an https:// URL.' });
                if (!picked.length) return setError({ field: 'events', message: 'Pick at least one event.' });
                try {
                  await onSubmit({ name, url, events: picked });
                  onOpenChange(false);
                } catch (e) {
                  setError({ message: (e as Error).message });
                }
              }}
            >
              Add webhook
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="wh-name" label="Name" error={err('name')}>
          <Input id="wh-name" value={name} onChange={(e) => (setName(e.target.value), setError(null))} placeholder="e.g. SIEM forwarder" aria-invalid={!!err('name')} />
        </FormField>
        <FormField id="wh-url" label="Endpoint URL" error={err('url')}>
          <Input id="wh-url" value={url} onChange={(e) => (setUrl(e.target.value), setError(null))} placeholder="e.g. https://example.internal/hooks/ops-ai" className="font-mono text-xs" aria-invalid={!!err('url')} />
        </FormField>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-sm font-medium">Events</legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {events.map((e) => (
              <div key={e.value} className="flex items-center gap-2">
                <Checkbox id={`wh-ev-${e.value}`} checked={picked.includes(e.value)} onCheckedChange={(v) => (setPicked((p) => (v ? [...p, e.value] : p.filter((x) => x !== e.value))), setError(null))} />
                <Label htmlFor={`wh-ev-${e.value}`} className="font-normal">
                  {e.label}
                </Label>
              </div>
            ))}
          </div>
          {err('events') && <p className="text-xs text-destructive">{err('events')}</p>}
        </fieldset>
      </div>
    </DialogShell>
  );
}
