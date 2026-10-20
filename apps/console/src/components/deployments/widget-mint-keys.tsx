'use client';

import * as React from 'react';
import { AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useCreateWidgetMintKey, useRevokeWidgetMintKey, useWidgetMintKeys, useWidgetScriptUrl } from '@/hooks/widget-deployment-queries';
import { relativeTime } from '@/lib/format';
import type { WidgetDeployment, WidgetMintKey } from '@/lib/types/widget-deployments';

/**
 * The keys the bank's server mints one deployment's sessions with (agents-service `/v1/widget-deployments/{id}/keys`,
 * c-131). A key mints for this deployment only; its secret is shown once, because only its hash is kept.
 */
export function WidgetMintKeysDialog({ deployment, open, onOpenChange }: { deployment: WidgetDeployment; open: boolean; onOpenChange: (open: boolean) => void }) {
  const keys = useWidgetMintKeys(open ? deployment.id : undefined);
  const create = useCreateWidgetMintKey();
  const revoke = useRevokeWidgetMintKey();
  const [name, setName] = React.useState('');
  const [days, setDays] = React.useState('90');
  const host = new URL(useWidgetScriptUrl()).origin;
  const endpoint = `${host}/v1/widget-deployments/${deployment.id}/sessions`;
  const [error, setError] = React.useState<string>();
  const [secret, setSecret] = React.useState<string>();
  const [revoking, setRevoking] = React.useState<WidgetMintKey>();

  React.useEffect(() => {
    if (open) return;
    setName('');
    setError(undefined);
    setSecret(undefined);
  }, [open]);

  const submit = async () => {
    if (!name.trim()) return setError('Name the server that will use it, like Intranet server.');
    try {
      const made = await create.mutateAsync({ id: deployment.id, name: name.trim(), expiresInDays: Number(days) });
      setSecret(made.secret);
      setName('');
      toast.success(`Key ${made.key.name} created`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={`Mint keys for ${deployment.name}`}
      description="A mint key is a secret your server keeps. With it, the server asks Ops AI for a session for the person signed in to your page; the page only ever holds that session."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Done
          </Button>
          <LoadingButton type="submit" isLoading={create.isPending} loadingText="Creating…" data-testid="widget-key-create">
            Create key
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-md border bg-muted/40 p-3 text-sm" data-testid="widget-key-facts">
          <dt className="text-muted-foreground">Your server calls</dt>
          <dd className="flex min-w-0 items-start gap-2">
            <code className="min-w-0 break-all font-mono text-xs">POST {endpoint}</code>
            <CopyButton text={endpoint} size="sm" variant="ghost" />
          </dd>
          <dt className="text-muted-foreground">With</dt>
          <dd>
            <code className="font-mono text-xs">Authorization: Bearer &lt;mint key&gt;</code>
          </dd>
          <dt className="text-muted-foreground">Body</dt>
          <dd className="text-xs">
            <code className="font-mono">email</code> of the person signed in (required), their <code className="font-mono">name</code>, and the page&apos;s <code className="font-mono">origin</code>, one of{' '}
            {deployment.origins.map((o, i) => (
              <React.Fragment key={o}>
                {i ? ', ' : ''}
                <code className="font-mono">{o}</code>
              </React.Fragment>
            ))}
          </dd>
          <dt className="text-muted-foreground">It answers</dt>
          <dd className="text-xs">
            <code className="font-mono">{'{ session, expiresIn }'}</code>: a session for that person on that page, for 15 minutes. The page asks your server for a new one before it ends.
          </dd>
        </dl>
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
          <FormField id="widget-key-name" label="Name" error={error}>
            <Input id="widget-key-name" value={name} aria-invalid={!!error} onChange={(e) => (setName(e.target.value), setError(undefined))} placeholder="e.g. Intranet server" />
          </FormField>
          <FormField id="widget-key-days" label="Expires after">
            <Select value={days} onValueChange={setDays}>
              <SelectTrigger id="widget-key-days" className="w-full" data-testid="widget-key-days">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {['30', '90', '180', '365'].map((d) => (
                  <SelectItem key={d} value={d}>
                    {d} days
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        {secret ? (
          <Alert data-testid="widget-key-secret">
            <AlertCircle />
            <AlertDescription className="flex flex-col gap-2">
              <span>Copy this key into the bank server&apos;s secret store now. It is not shown again.</span>
              <span className="flex items-start gap-2">
                <code className="min-w-0 flex-1 break-all font-mono text-xs">{secret}</code>
                <CopyButton text={secret} size="sm" variant="outline" />
              </span>
            </AlertDescription>
          </Alert>
        ) : null}
        {keys.isPending ? (
          <Skeleton className="h-16" />
        ) : keys.isError ? (
          <QueryError what="keys" onRetry={() => keys.refetch()} retrying={keys.isFetching} />
        ) : !keys.data.length ? (
          <p className="text-sm text-muted-foreground">No keys yet.</p>
        ) : (
          <Table data-testid="widget-keys">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.data.map((k) => (
                <TableRow key={k.id}>
                  <TableCell className="font-medium">
                    {k.name} {k.revokedAt ? <Badge variant="secondary">Revoked</Badge> : null}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {relativeTime(k.createdAt)} by {k.createdBy}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{k.lastUsedAt ? relativeTime(k.lastUsedAt) : 'Never'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground" data-testid="widget-key-expires">
                    {k.expiresAt ? new Date(k.expiresAt).toLocaleDateString(undefined, { dateStyle: 'medium' }) : 'Never'}
                  </TableCell>
                  <TableCell className="text-right">
                    {k.revokedAt ? null : (
                      <Button type="button" size="sm" variant="outline" onClick={() => setRevoking(k)}>
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </DialogShell>
      {revoking ? (
        <ConfirmActionDialog
          open={!!revoking}
          onOpenChange={(o) => !o && setRevoking(undefined)}
          title={`Revoke ${revoking.name}`}
          consequence={`The server using ${revoking.name} can no longer start chat sessions on ${deployment.name}. Sessions it already started end within 15 minutes.`}
          runsNow
          note="Takes effect now and cannot be undone. Create a new key to replace it."
          confirmLabel="Revoke"
          destructive
          isPending={revoke.isPending}
          onConfirm={async () => {
            await revoke.mutateAsync({ id: deployment.id, keyId: revoking.id });
            toast.success(`${revoking.name} is revoked`);
          }}
        />
      ) : null}
    </>
  );
}
