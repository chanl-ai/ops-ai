'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { FormShell } from '@/components/shared/setting/form-shell';
import { PrefixedInput } from '@/components/shared/setting/prefixed-input';
import { Input } from '@/components/ui/input';
import { previewStore } from '@/lib/settings-preview-store';

const HOST = /^(?=.{3,253}$)([a-z0-9-]+\.)+[a-z]{2,}$/;

/**
 * Allow a host for tool calls (S15). The same component is the Egress section of Govern › Security (`shell="card"`) and
 * the "Add allowed host" dialog a tool page opens in place (`shell="dialog"`). Both call the same add.
 */
export function EgressHostForm({ shell, open, onOpenChange, locked, onAdded, presetHost }: { shell: 'card' | 'dialog'; open?: boolean; onOpenChange?: (o: boolean) => void; locked?: boolean; onAdded?: (host: string) => void; presetHost?: string }) {
  const [host, setHost] = React.useState(presetHost ?? '');
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) (setHost(presetHost ?? ''), setNote(''), setError(undefined));
  }, [open, presetHost]);
  const submit = () => {
    const h = host.trim().toLowerCase();
    if (!HOST.test(h)) return setError('Enter a hostname such as api.example.com, with no https:// or path.');
    previewStore.addHost(h, note.trim());
    toast.success(`Allowed ${h}`, { description: 'Tool calls to it go out from the next run. Design mock: nothing is stored.' });
    setHost(presetHost ?? '');
    setNote('');
    setError(undefined);
    onOpenChange?.(false);
    onAdded?.(h);
  };
  return (
    <FormShell shell={shell} id="egress-add" open={open} onOpenChange={onOpenChange} title="Add allowed host" description="Tool calls can reach only the hosts on this list. Add the host a module calls." submitLabel="Allow host" onSubmit={submit} locked={locked} requiredRole="Security admin" help="A host, not a URL. Subdomains need their own entry.">
      <FormField id="egress-host" label="Host" error={error}>
        <PrefixedInput prefix="https://" id="egress-host" value={host} onChange={(e) => (setHost(e.target.value), setError(undefined))} placeholder="e.g. api.example.com" aria-invalid={!!error} autoComplete="off" />
      </FormField>
      <FormField id="egress-note" label="Why" optional hint="Shown to the next admin who reviews the list.">
        <Input id="egress-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Core banking read API" className="bg-card" />
      </FormField>
    </FormShell>
  );
}
