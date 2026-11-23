'use client';

import * as React from 'react';
import { User, Users } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SearchSelect } from '@/components/shared/search-select';
import { Button } from '@/components/ui/button';
import { roleHolderOptions } from '@/hooks/options-queries';

type Holder = { kind: 'person' | 'group'; id: string };

/** A picked value, `person:<user id>` or `group:<group id>`, as the holder the route takes. */
const holderOf = (value: string): Holder => {
  const [kind, ...rest] = value.split(':');
  return { kind: kind === 'group' ? 'group' : 'person', id: rest.join(':') };
};

/**
 * Gives a custom role to a person or a group in the team the console acts in, picked from one searched list of the
 * team's people and the workspace's groups (the search runs on the server). The server's refusal (not an admin of the
 * team, held already, a role a group is never given) shows here.
 */
export function GiveRoleToDialog({
  open,
  onOpenChange,
  roleId,
  roleName,
  teamName,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roleId: string;
  roleName: string;
  /** The team the console acts in, where the role is given. */
  teamName: string;
  pending: boolean;
  onSubmit: (holder: Holder) => Promise<unknown>;
}) {
  const source = React.useMemo(() => roleHolderOptions(roleId), [roleId]);
  const [picked, setPicked] = React.useState<{ id: string; label: string } | null>(null);
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    if (!open) return;
    setPicked(null);
    setError('');
  }, [open]);

  const submit = async () => {
    if (!picked) {
      setError('Choose a person or a group.');
      return;
    }
    try {
      await onSubmit(holderOf(picked.id));
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !pending && onOpenChange(o)}
      size="md"
      title={`Give ${roleName}`}
      description={`In ${teamName}: the role adds what it allows there, on top of each holder's team role, from their next action. To give it in another team, switch to that team first.`}
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive-text" data-testid="give-role-to-error">
            {error}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending} loadingText="Giving…" disabled={!picked} data-testid="give-role-to-submit">
              Give role
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="give-role-to" label="Person or group" hint="The team's people and the workspace's groups. A group's members hold the role while they are in it.">
          <SearchSelect
            id="give-role-to"
            source={source}
            value={picked}
            onChange={(id, o) => (setPicked(o ? { id, label: o.label } : null), setError(''))}
            placeholder="Choose a person or a group"
            searchPlaceholder="Search people and groups…"
            emptyText="No person or group matches."
            renderOption={(o) => (
              <span className="flex min-w-0 items-center gap-2">
                {o.id.startsWith('group:') ? <Users className="size-4 shrink-0 text-muted-foreground" /> : <User className="size-4 shrink-0 text-muted-foreground" />}
                <span className="truncate">{o.label}</span>
                {o.hint && <span className="truncate text-xs text-muted-foreground">{o.hint}</span>}
              </span>
            )}
            testId="give-role-to-holder"
            className="w-full"
          />
        </FormField>
      </div>
    </DialogShell>
  );
}
