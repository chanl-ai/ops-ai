'use client';

import * as React from 'react';
import { KeyRound, Plus } from 'lucide-react';

import { SecretDialog } from '@/components/settings/secret-dialog';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useCan } from '@/hooks/me-queries';
import { useSecrets } from '@/hooks/secrets-queries';

/**
 * Pick a secret by name, or add one without leaving the page. `onPick` receives the reference as a header or body
 * writes it, `{{NAME}}`. Adding a secret is allowed to whoever the server's grid lets (secrets_egress.create); everyone else
 * can pick what exists. It is the one place a secret is chosen: tool headers use it, and the Secrets page owns the list.
 */
export function SecretPicker({ onPick, disabled, label = 'Insert a secret' }: { onPick: (reference: string) => void; disabled?: boolean; label?: string }) {
  const [open, setOpen] = React.useState(false);
  const [adding, setAdding] = React.useState(false);
  const secrets = useSecrets();
  const canAdd = useCan('secrets_egress', 'create') === true;
  const pick = (name: string) => (onPick(`{{${name}}}`), setOpen(false));
  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" size="icon" variant="ghost" className="size-8" aria-label={label} title={label} disabled={disabled}>
            <KeyRound className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="end">
          <Command>
            <CommandInput placeholder="Search secrets…" />
            <CommandList>
              <CommandEmpty>{secrets.isPending ? 'Loading…' : 'No secret found.'}</CommandEmpty>
              <CommandGroup>
                {(secrets.data ?? []).map((s) => (
                  <CommandItem key={s.name} value={s.name} onSelect={() => pick(s.name)}>
                    <span className="font-mono text-xs">{s.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
              {canAdd && (
                <>
                  <CommandSeparator />
                  <CommandGroup>
                    <CommandItem
                      value="add a secret"
                      onSelect={() => {
                        setOpen(false);
                        setAdding(true);
                      }}
                    >
                      <Plus className="size-4" /> Add a secret
                    </CommandItem>
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {canAdd && <SecretDialog open={adding} rotating={null} onOpenChange={setAdding} onSaved={(name) => pick(name)} />}
    </>
  );
}
