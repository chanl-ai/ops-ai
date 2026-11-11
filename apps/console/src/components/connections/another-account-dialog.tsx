'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import type { MyConnector } from '@/hooks/connections-queries';
import { useCardAppPage } from '@/hooks/systems-queries';

/** What the person adds: its name and, per setting the app keeps for each account, where it signs in. */
export interface AnotherAccount {
  name: string;
  settings: Record<string, string>;
}

/**
 * Another account of the person's own on an app: two questions, its name (steps and chats pick it by this name) and
 * where it signs in, read from the app's own per-account settings (a company's sign-in address), so it lands in its own
 * org rather than where their first account does. A key or password app adds one through an admin, as the sheet says.
 */
export function AnotherAccountDialog({
  connector: c,
  busy,
  error,
  onClose,
  onAdd,
}: {
  connector: MyConnector;
  busy: boolean;
  error?: string | null;
  onClose: () => void;
  onAdd: (a: AnotherAccount) => void;
}) {
  const page = useCardAppPage(c.appId);
  const places = (page.data?.card.plugin?.settings ?? []).filter((x) => x.perAccount && !x.secret && x.asked !== 'settings');
  const [name, setName] = React.useState('');
  const [values, setValues] = React.useState<Record<string, string>>({});
  const next = name.trim();
  const taken = c.accounts.some((a) => a.name.trim().toLowerCase() === next.toLowerCase());
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Add another ${c.name} account`}
      description="An account of your own beside the one you use, such as a personal and an office login."
      data-testid="another-account"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={busy}
            disabled={!next || taken}
            onClick={() => onAdd({ name: next, settings: Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim())) })}
            data-testid="another-account-add"
          >
            Sign in
          </LoadingButton>
        </>
      }
    >
      <FormField id="another-account-name" label="Account name" hint="Steps and chats pick an account by this name." error={taken ? 'You already have an account with this name.' : undefined}>
        <Input id="another-account-name" value={name} placeholder="Office" onChange={(e) => setName(e.target.value)} data-testid="another-account-name" />
      </FormField>
      {page.isLoading ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        places.map((x) => (
          <FormField key={x.name} id={`another-account-${x.name}`} label={x.label} hint={x.default ? `Leave empty to sign in at ${String(x.default)}.` : undefined}>
            <Input
              id={`another-account-${x.name}`}
              value={values[x.name] ?? ''}
              placeholder={x.default ? String(x.default) : undefined}
              onChange={(e) => setValues((v) => ({ ...v, [x.name]: e.target.value }))}
              data-testid={`another-account-${x.name}`}
            />
          </FormField>
        ))
      )}
      {error && (
        <p className="text-sm text-destructive-text" role="alert" data-testid="another-account-error">
          {error}
        </p>
      )}
    </DialogShell>
  );
}
