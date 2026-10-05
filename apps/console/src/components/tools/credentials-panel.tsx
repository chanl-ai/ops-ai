'use client';

import * as React from 'react';
import { KeyRound, Vault } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { relativeTime } from '@/lib/format';
import type { ModuleCredential, ToolModuleDetail } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

import { CREDENTIAL_KIND, ENV_LABEL } from './module-meta';

function RotateText({ c }: { c: ModuleCredential }) {
  const days = Math.round((new Date(c.rotateBy).getTime() - Date.now()) / 86_400_000);
  return (
    <span className={cn('text-xs whitespace-nowrap tabular-nums', c.status === 'overdue' ? 'font-medium text-red-600 dark:text-red-400' : c.status === 'rotate_soon' ? 'font-medium text-amber-700 dark:text-amber-400' : 'text-muted-foreground')}>
      {days < 0 ? `Overdue by ${Math.abs(days)} ${Math.abs(days) === 1 ? 'day' : 'days'}` : `Rotate in ${days} ${days === 1 ? 'day' : 'days'}`}
    </span>
  );
}

/** Vault references per environment. Values are never returned by the API, so there is nothing here to reveal. */
export function CredentialsPanel({ module, onChangeRef, saving }: { module: ToolModuleDetail; onChangeRef: (c: ModuleCredential, ref: string) => Promise<unknown>; saving: boolean }) {
  const [editing, setEditing] = React.useState<ModuleCredential | null>(null);
  const [ref, setRef] = React.useState('');
  React.useEffect(() => {
    if (editing) setRef(editing.secretRef);
  }, [editing]);

  return (
    <div className="flex flex-col gap-4">
      <Alert>
        <Vault className="size-4" />
        <AlertDescription>
          Secrets are managed in the bank vault and rotated there. The data gateway resolves the reference on each call; workers, agents and this console never see the value.
          {module.auth.header && (
            <>
              {' '}
              Sent as the <code className="font-mono">{module.auth.header}</code> header.
            </>
          )}
        </AlertDescription>
      </Alert>
      {!module.credentials.length ? (
        <EmptyState icon={KeyRound} title="No credential" description={module.auth.kind === 'none' ? 'This module is served inside the gateway and needs no credential.' : 'Add the vault reference when you connect the module.'} />
      ) : (
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Environment</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Vault reference</TableHead>
                <TableHead>Set</TableHead>
                <TableHead>Rotation</TableHead>
                <TableHead className="w-36" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {module.credentials.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{ENV_LABEL[c.environment]}</TableCell>
                  <TableCell className="text-sm whitespace-nowrap">{CREDENTIAL_KIND[c.kind]}</TableCell>
                  <TableCell>
                    <span className="flex items-center gap-1">
                      <code className="font-mono text-xs break-all">{c.secretRef}</code>
                      <CopyButton text={c.secretRef} className="size-7 shrink-0 p-0" />
                    </span>
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                    {c.setBy}
                    <div>{relativeTime(c.setAt)}</div>
                  </TableCell>
                  <TableCell>
                    <RotateText c={c} />
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>
                      Change reference
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <DialogShell
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        size="sm"
        title={`Change the ${editing ? ENV_LABEL[editing.environment].toLowerCase() : ''} reference`}
        description="Calls use the new reference from the next request. Check the path exists in the vault first; a wrong path fails every call."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setEditing(null)} disabled={saving}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={saving}
              disabled={!ref.trim() || ref.trim() === editing?.secretRef}
              onClick={async () => {
                if (!editing) return;
                await onChangeRef(editing, ref.trim());
                setEditing(null);
              }}
            >
              Save reference
            </LoadingButton>
          </div>
        }
      >
        <FormField id="cred-ref" label="Vault path">
          <Input id="cred-ref" value={ref} onChange={(e) => setRef(e.target.value)} className="font-mono text-sm" placeholder="e.g. vault://prod/data-gateway/core-banking/oauth-client" />
        </FormField>
      </DialogShell>
    </div>
  );
}
