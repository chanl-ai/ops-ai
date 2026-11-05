'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { DeleteDialog } from '@/components/shared/delete-dialog';
import { FormField } from '@/components/shared/form-field';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { type AppCredentialDetail, useAppCredentials, useDeleteAppCredential } from '@/hooks/systems-queries';
import { plural } from '@/lib/format';

// Ops AI's app has no credential id; a Select item needs a value, so it stands for "move them to Ops AI's app".
const OPS_AI = 'ops-ai';

/**
 * Delete an app credential. With accounts signing in with it, it names them and asks where they move instead of
 * refusing: another of the team's credentials of the same app, or Ops AI's app where the install has one; each moved
 * account signs in again. The client secret goes with it.
 */
export function CredentialDeleteDialog({
  credential,
  platform,
  onOpenChange,
  onDeleted,
}: {
  credential: AppCredentialDetail | null;
  /** Whether the install has Ops AI's app for the credential's app, so accounts may move there. */
  platform: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}) {
  const others = useAppCredentials(credential?.app).data?.filter((c) => c.type === 'own' && c.id !== credential?.id) ?? [];
  const remove = useDeleteAppCredential();
  const [to, setTo] = React.useState<string>('');
  const accounts = credential?.accountsList ?? [];
  const choices = [...(platform ? [{ id: OPS_AI, name: 'Ops AI’s app' }] : []), ...others.map((c) => ({ id: c.id, name: c.name }))];
  // The first choice until the person picks another.
  const chosen = choices.some((c) => c.id === to) ? to : (choices[0]?.id ?? '');
  const stranded = accounts.length > 0 && !choices.length;
  const deleteIt = () =>
    credential &&
    remove.mutate(
      { id: credential.id, move: accounts.length > 0, moveTo: chosen === OPS_AI ? null : chosen },
      {
        onSuccess: (r) => {
          toast.success(`Deleted ${credential.name}`, { description: r.moved ? `${plural(r.moved, 'account')} moved; each signs in again.` : undefined });
          onDeleted();
        },
        onError: (e) => toast.error(`Couldn’t delete ${credential.name}`, { description: e.message }),
      },
    );
  return (
    <DeleteDialog
      open={Boolean(credential)}
      onOpenChange={onOpenChange}
      entityType="auth config"
      entityName={credential?.name}
      isLoading={remove.isPending}
      onConfirm={() => {
        if (!stranded) deleteIt();
      }}
      testIdPrefix="credential"
      description={
        accounts.length
          ? `${plural(accounts.length, 'account')} sign in with it: ${accounts.map((a) => a.name).join(', ')}. They move to the auth config you pick, and each signs in again.`
          : 'Its client secret is deleted with it.'
      }
    >
      {accounts.length > 0 &&
        (stranded ? (
          <p className="text-sm text-destructive" data-testid="credential-delete-stranded">
            {`Add another ${credential?.appName ?? ''} auth config first, so its accounts have somewhere to move.`}
          </p>
        ) : (
          <FormField id="credential-move-to" label="Move its accounts to">
            <Select value={chosen} onValueChange={setTo}>
              <SelectTrigger id="credential-move-to" className="w-full" data-testid="credential-delete-move-to">
                <SelectValue />
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
        ))}
    </DeleteDialog>
  );
}
