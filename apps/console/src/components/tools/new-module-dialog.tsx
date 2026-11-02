'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SaveProblem } from '@/components/shared/save-problem';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ConnectionSelect } from '@/components/tools/connection-select';
import { useConnectionOptions } from '@/hooks/systems-queries';
import { HostHeldError } from '@/lib/api/held-host';
import type { IntegrationStatus } from '@/lib/types/integrations';
import type { BlankModuleInput } from '@/lib/types/tool-modules';

const kebab = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/**
 * New module: one screen, a name and the app it calls (group F). The app's connection gives its address and sign-in, so
 * each operation is a path on it; how an operation runs comes from its executor, never a type picked here. It saves a
 * draft and opens the module page, where operations and every other setting are added tab by tab.
 */
export function NewModuleDialog({ open, onOpenChange, onCreate, creating }: { open: boolean; onOpenChange: (o: boolean) => void; onCreate: (input: BlankModuleInput) => Promise<void>; creating: boolean }) {
  const [displayName, setDisplayName] = React.useState('');
  const [name, setName] = React.useState('');
  const [nameEdited, setNameEdited] = React.useState(false);
  const [connectionId, setConnectionId] = React.useState<string | null>(null);
  const connections = useConnectionOptions(open);
  const [description, setDescription] = React.useState('');
  const [err, setErr] = React.useState<{ display?: string; name?: string; form?: unknown }>({});
  React.useEffect(() => {
    if (!open) return;
    setDisplayName('');
    setName('');
    setNameEdited(false);
    setConnectionId(null);
    setDescription('');
    setErr({});
  }, [open]);

  const submit = async () => {
    const e = { display: displayName.trim() ? undefined : 'Give it a display name.', name: kebab(name) ? undefined : 'Give it a name, e.g. document-service.' };
    setErr(e);
    if (e.display || e.name) return;
    try {
      await onCreate({ displayName: displayName.trim(), name: kebab(name), ...(connectionId ? { connectionId } : {}), description: description.trim() || undefined });
    } catch (x) {
      const message = (x as Error).message;
      setErr(x instanceof HostHeldError ? { form: x } : /already exists|name/i.test(message) ? { name: message } : { form: x });
    }
  };

  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      size="md"
      title="New tool"
      description="Saves a draft. Add its operations, each a path on the app, on its page."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={creating} loadingText="Saving…" data-testid="new-module-save">
            Save draft
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4" data-testid="new-module-dialog">
        <SaveProblem error={err.form} />
        <FormField id="nm-display" label="Display name" error={err.display}>
          <Input
            id="nm-display"
            autoFocus
            value={displayName}
            aria-invalid={!!err.display}
            onChange={(e) => {
              setDisplayName(e.target.value);
              if (!nameEdited) setName(kebab(e.target.value));
              setErr({});
            }}
            placeholder="e.g. Document service"
          />
        </FormField>
        <FormField id="nm-name" label="Name" error={err.name} hint="Workflows pin this name. It follows the display name until you edit it.">
          <Input
            id="nm-name"
            value={name}
            aria-invalid={!!err.name}
            onChange={(e) => {
              setName(e.target.value);
              setNameEdited(true);
              setErr({});
            }}
            placeholder="e.g. document-service"
            className="font-mono"
          />
        </FormField>
        <FormField id="nm-app" label="App" hint="Its address and sign-in come from the app. Add a custom app for one not listed.">
          <ConnectionSelect
            value={connectionId ? { id: connectionId, name: connections.data?.data.find((c) => c.id === connectionId)?.name ?? '' } : null}
            options={connections.data?.data.map((c) => ({ id: c.id, name: c.name, status: c.status as IntegrationStatus }))}
            loading={connections.isPending}
            onChange={setConnectionId}
          />
        </FormField>
        <FormField id="nm-desc" label="Description" optional>
          <Textarea id="nm-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Fetches signed loan documents for the lending inbox" className="min-h-16 resize-none" />
        </FormField>
      </div>
    </DialogShell>
  );
}
