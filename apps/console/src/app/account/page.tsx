'use client';

import * as React from 'react';
import { UserCircle } from 'lucide-react';
import { toast } from 'sonner';

import { AccountTabs } from '@/components/account/account-tabs';
import { PageLayout } from '@/components/page-layout';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { SettingsSection } from '@/components/shared/settings-section';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useAccountProfile, useUpdateProfile } from '@/hooks/account-queries';

/** The signed-in person's profile: display name (editable), email (from the identity provider or invite), team and role. */
export default function AccountPage() {
  const query = useAccountProfile();
  const update = useUpdateProfile();
  const p = query.data;
  const [name, setName] = React.useState('');
  React.useEffect(() => {
    if (p) setName(p.name);
  }, [p]);
  const dirty = !!p && name.trim() !== p.name;

  return (
    <PageLayout icon={UserCircle} title="Account" description="Your profile and how you sign in" tabs={<AccountTabs />}>
      {query.isPending ? (
        <div className="flex max-w-2xl flex-col gap-4" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError && !p ? (
        <QueryError what="your account" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : p ? (
        <div className="flex max-w-2xl flex-col gap-4" data-testid="account-profile">
          <div className="flex items-center gap-4 rounded-lg border p-4">
            <Avatar className="size-14">
              <AvatarFallback className="text-lg">{p.initials}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="text-base font-semibold">{p.name}</p>
              <p className="truncate text-sm text-muted-foreground">{p.email}</p>
            </div>
          </div>
          <SettingsSection title="Profile" description="Your name as reviewers and the audit log show it.">
            <div className="flex flex-col gap-4">
              <FormField id="acc-name" label="Name" error={name.trim().length < 2 ? 'Enter your name.' : undefined}>
                <Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} className="max-w-sm bg-background" />
              </FormField>
              <FormField id="acc-email" label="Email" hint={p.authMethod === 'sso' ? `Managed by ${p.ssoProvider ?? 'your identity provider'}.` : 'Set by your invitation. Ask an admin to change it.'}>
                <Input id="acc-email" value={p.email} readOnly disabled className="max-w-sm bg-background" />
              </FormField>
              <LoadingButton
                size="sm"
                className="self-start"
                isLoading={update.isPending}
                disabled={!dirty || name.trim().length < 2}
                onClick={() => update.mutate({ name: name.trim() }, { onSuccess: () => toast.success('Saved your name'), onError: (e) => toast.error('Couldn’t save', { description: e.message }) })}
                data-testid="save-profile"
              >
                Save
              </LoadingButton>
            </div>
          </SettingsSection>
          <SettingsSection title="Workspace" description="Changed by a team admin in Settings → Members.">
            <div className="flex flex-col">
              <FieldRow label="Team" value={p.team} />
              <FieldRow label="Role" value={p.role} />
              <FieldRow label="Signs in with" value={p.authMethod === 'sso' ? (p.ssoProvider ?? 'Single sign-on') : 'Email and password'} />
            </div>
          </SettingsSection>
        </div>
      ) : null}
    </PageLayout>
  );
}
