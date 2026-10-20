'use client';

import * as React from 'react';
import { KeyRound } from 'lucide-react';
import { toast } from 'sonner';

import { SignInProviderDialog } from '@/components/settings/sign-in-provider-dialog';
import { SignInDomainsSection, SignInProvidersSection } from '@/components/settings/sign-in-providers';
import { SignInSecuritySection, SignInSignupSection } from '@/components/settings/sign-in-sections';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { SampleData } from '@/components/shared/sample-data';
import { Skeleton } from '@/components/ui/skeleton';
import { useSignInPolicySettings } from '@/hooks/account-queries';
import { useRemoveSignInProvider, useSamlMetadataUrl, useSaveSignInProvider, useSignInProviders, useSignInSecretNames, useVerifySignInDomain } from '@/hooks/sign-in-provider-queries';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';
import type { SignInProvider } from '@/lib/types/sign-in';

const newId = () => `sip_${Math.random().toString(36).slice(2, 12)}`;

/**
 * Settings → Sign-in (c-195): the workspace's providers and the DNS proof of each domain, on platform-service. MFA,
 * session length and sign-up have no service yet, so they show as sample sections below.
 */
export default function SignInSettingsPage() {
  const providers = useSignInProviders();
  const forbidden = providers.error instanceof ApiError && providers.error.status === 403;
  const secretNames = useSignInSecretNames(providers.isSuccess);
  const metadataUrl = useSamlMetadataUrl();
  const policy = useSignInPolicySettings();
  const { teams } = useTeam();
  const save = useSaveSignInProvider();
  const remove = useRemoveSignInProvider();
  const verify = useVerifySignInDomain();
  const [dialog, setDialog] = React.useState<{ open: boolean; provider: SignInProvider | null }>({ open: false, provider: null });
  const [removing, setRemoving] = React.useState<SignInProvider | null>(null);
  const [verifying, setVerifying] = React.useState<string | null>(null);
  const teamName = (id: string) => teams.find((t) => t.id === id)?.name ?? id;

  const onVerify = (domain: string) => {
    setVerifying(domain);
    verify.mutate(domain, {
      onSuccess: () => toast.success(`Verified ${domain}`, { description: 'People on this domain now sign in through its provider.' }),
      onError: (e) => toast.error(`Couldn’t verify ${domain}`, { description: e.message }),
      onSettled: () => setVerifying(null),
    });
  };

  const body = (() => {
    if (providers.isPending) {
      return (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      );
    }
    if (forbidden) return <EmptyState icon={KeyRound} title="Sign-in is set by the Security team" description={(providers.error as Error).message} testId="sign-in-no-access" />;
    if (providers.isError) return <QueryError what="the sign-in providers" onRetry={() => providers.refetch()} retrying={providers.isFetching} />;
    const rows = providers.data ?? [];
    return (
      <div className="flex flex-col gap-4" data-testid="sign-in-settings">
        <SignInProvidersSection providers={rows} teamName={teamName} onAdd={() => setDialog({ open: true, provider: null })} onEdit={(p) => setDialog({ open: true, provider: p })} onRemove={setRemoving} />
        <SignInDomainsSection providers={rows} verifying={verifying} onVerify={onVerify} />
        {policy.data && (
          <SampleData>
            <SignInSecuritySection policy={policy.data} saving={false} onSave={async () => undefined} />
            <SignInSignupSection policy={policy.data} saving={false} onSave={async () => undefined} />
          </SampleData>
        )}
      </div>
    );
  })();

  return (
    <SettingsPageLayout section="Sign-in" description="How people sign in to this workspace: its identity providers and the email domains each one serves.">
      {body}
      <SignInProviderDialog
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        provider={dialog.provider}
        teams={teams}
        secretNames={secretNames.data ?? []}
        metadataUrl={metadataUrl}
        pending={save.isPending}
        onSubmit={async (input) => {
          const id = dialog.provider?.id ?? newId();
          const saved = await save.mutateAsync({ id, input });
          const pending = saved.verification.filter((c) => !c.verifiedAt).length;
          toast.success(`Saved ${saved.label}`, { description: pending ? `Publish the TXT record shown for ${pending === 1 ? 'its new domain' : `its ${pending} new domains`}, then verify.` : 'Applies at the next sign-in.' });
        }}
      />
      <ConfirmActionDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Delete ${removing?.label ?? 'provider'}?`}
        consequence="People on its domains can no longer sign in through it, and its domains must be verified again if added back."
        runsNow
        confirmLabel="Delete provider"
        destructive
        isPending={remove.isPending}
        onConfirm={async () => {
          await remove.mutateAsync(removing!.id);
          toast.success(`Deleted ${removing!.label}`);
          setRemoving(null);
        }}
      />
    </SettingsPageLayout>
  );
}
