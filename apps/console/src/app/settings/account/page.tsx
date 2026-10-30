'use client';

import * as React from 'react';
import { UserCircle } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { SampleData } from '@/components/shared/sample-data';
import { SettingsSection } from '@/components/shared/settings-section';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useAccountProfile, useUpdateProfile } from '@/hooks/account-queries';
import { useMe, useTeamRole } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';

const initialsOf = (name: string) =>
  name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('');

/** The signed-in person's profile: display name (editable), email (from the identity provider or invite), team and role. */
export default function AccountPage() {
  // On platform sign-in the signed-in person comes from GET /v1/me; no service serves /account yet, so it stays the
  // sample source off platform, where its editor stays too.
  const me = useMe();
  const onPlatform = me.isEnabled;
  const role = useTeamRole();
  const { team } = useTeam();
  const sample = useAccountProfile();
  const update = useUpdateProfile();
  const query = onPlatform ? me : sample;
  const p = onPlatform
    ? me.data && { name: me.data.user.name, email: me.data.user.email, initials: initialsOf(me.data.user.name || me.data.user.email), team: team?.name ?? me.data.teams[0]?.name ?? '', role: role ?? '', authMethod: undefined, ssoProvider: undefined }
    : sample.data;
  const Wrap = onPlatform ? React.Fragment : SampleData;
  const [name, setName] = React.useState('');
  React.useEffect(() => {
    if (p) setName(p.name);
  }, [p]);
  const dirty = !!p && name.trim() !== p.name;
  const saveName = () => {
    if (!dirty || name.trim().length < 2) return;
    update.mutate({ name: name.trim() }, { onSuccess: () => toast.success('Saved your name'), onError: (e) => toast.error('Couldn’t save', { description: e.message }) });
  };

  return (
    <PageLayout icon={UserCircle} title="My account" description="Your name, email and role in the team" preview={!onPlatform}>
      {query.isPending ? (
        <div className="flex max-w-2xl flex-col gap-4" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError && !p ? (
        <QueryError what="your account" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : p ? (
        <div className="flex max-w-2xl flex-col gap-4" data-testid="account-profile">
          <Wrap>
          <div className="flex items-center gap-4 rounded-lg border p-4">
            <Avatar className="size-14">
              <AvatarFallback className="text-lg">{p.initials}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="text-base font-semibold">{p.name}</p>
              <p className="truncate text-sm text-muted-foreground">{p.email}</p>
            </div>
          </div>
          <SettingsSection title="Profile" description="Your name as reviewers and the audit log show it." onSubmit={saveName}>
            <div className="flex flex-col gap-4">
              <FormField id="acc-name" label="Name" hint={onPlatform ? 'Your name comes from your sign-in, so it is changed there.' : undefined} error={name.trim().length < 2 ? 'Enter your name.' : undefined}>
                <Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} readOnly={onPlatform} disabled={onPlatform} className="max-w-sm bg-background" />
              </FormField>
              <FormField id="acc-email" label="Email" hint={p.authMethod === 'sso' ? `Managed by ${p.ssoProvider ?? 'your identity provider'}.` : 'Set by your invitation. Ask an admin to change it.'}>
                <Input id="acc-email" value={p.email} readOnly disabled className="max-w-sm bg-background" />
              </FormField>
              {!onPlatform && (
                <LoadingButton type="submit" size="sm" className="self-start" isLoading={update.isPending} disabled={!dirty || name.trim().length < 2} data-testid="save-profile">
                  Save
                </LoadingButton>
              )}
            </div>
          </SettingsSection>
          <SettingsSection title="Workspace" description="Changed by a team admin in Settings → Members.">
            <div className="flex flex-col">
              <FieldRow label="Team" value={p.team} />
              <FieldRow label="Role" value={p.role} />
              {!onPlatform && <FieldRow label="Signs in with" value={p.authMethod === 'sso' ? (p.ssoProvider ?? 'Single sign-on') : 'Email and password'} />}
            </div>
          </SettingsSection>
          </Wrap>
        </div>
      ) : null}
    </PageLayout>
  );
}
