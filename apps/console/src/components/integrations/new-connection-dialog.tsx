'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { AuthMethod, CatalogSystem, DraftConnectInput } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

import { AUTH } from './integration-meta';

/**
 * Connect a system in one screen: which system, a name and how the platform signs in. It saves a draft and opens
 * the connection page, whose Setup tab grants scopes, adds the credential and sets owner and expiry before it goes
 * live. The guided connect stays the second button.
 */
export function NewConnectionDialog({ open, onOpenChange, catalog, existingNames, isPending, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; catalog: CatalogSystem[]; existingNames: string[]; isPending: boolean; onSubmit: (input: DraftConnectInput) => Promise<unknown> }) {
  const choices = catalog.filter((c) => c.available);
  const [systemId, setSystemId] = React.useState('');
  const [name, setName] = React.useState('');
  const [auth, setAuth] = React.useState<AuthMethod | ''>('');
  const [errors, setErrors] = React.useState<{ system?: string; name?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setSystemId('');
      setName('');
      setAuth('');
      setErrors({});
    }
  }, [open]);
  const system = catalog.find((c) => c.id === systemId);

  const pick = (sid: string) => {
    const s = catalog.find((c) => c.id === sid);
    setSystemId(sid);
    if (!s) return;
    setAuth(s.authMethods[0]);
    if (!name.trim()) setName(s.connected ? `${s.name} · ${s.connected + 1}` : s.name);
  };

  const submit = async () => {
    const e = {
      system: system ? undefined : 'Choose the system to connect.',
      name: !name.trim() ? 'Name the connection.' : existingNames.some((n) => n.toLowerCase() === name.trim().toLowerCase()) ? 'A connection with this name already exists.' : undefined,
    };
    setErrors(e);
    if (e.system || e.name || !system || !auth) return;
    try {
      await onSubmit({ catalogId: system.id, name: name.trim(), authMethod: auth });
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Connect a system"
      description="Saves a draft. Grant scopes, add the credential and set owner and expiry on the next page; nothing can use it until it connects."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} onClick={submit} data-testid="new-connection-submit">
            Save draft
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="nc-system" label="System" error={errors.system}>
          <Select value={systemId} onValueChange={pick}>
            <SelectTrigger id="nc-system" className="w-full" aria-invalid={!!errors.system} data-testid="new-connection-system">
              <SelectValue placeholder="Choose a system" />
            </SelectTrigger>
            <SelectContent>
              {choices.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="nc-name" label="Connection name" error={errors.name} hint="Shown on every source, module and mailbox that uses it.">
          <Input id="nc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ServiceNow · operations desk" aria-invalid={!!errors.name} />
        </FormField>
        {system && (
          <FormField id="nc-auth" label="Sign-in method" hint="Only the methods this system’s owner allows are offered.">
            <RadioGroup value={auth} onValueChange={(a) => setAuth(a as AuthMethod)} className="grid gap-2">
              {system.authMethods.map((a, i) => (
                <label key={a} htmlFor={`nc-auth-${a}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', auth === a && 'border-primary bg-primary/5')}>
                  <RadioGroupItem value={a} id={`nc-auth-${a}`} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">
                      {AUTH[a].label}
                      {i === 0 && system.authMethods.length > 1 && <span className="ml-1.5 text-xs font-normal text-muted-foreground">Recommended</span>}
                    </span>
                    <span className="block text-xs text-muted-foreground">{AUTH[a].hint}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
