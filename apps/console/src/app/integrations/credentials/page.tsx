'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { KeyRound } from 'lucide-react';

import { AppCredentialsPanel } from '@/components/connections/app-credentials-panel';
import { PageLayout } from '@/components/page-layout';
import { SecretsPanel } from '@/components/secrets/secrets-panel';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

/**
 * Credentials in the Apps menu (U4): the OAuth apps the team's apps sign in with, and the secret values tools send.
 * The tab lives in ?tab= so a link can open Secrets directly (the old Settings › Security › Secrets address does).
 */
export default function CredentialsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = params.get('tab') === 'secrets' ? 'secrets' : 'apps';
  return (
    <PageLayout icon={KeyRound} title="Auth configs" description="How your apps sign in, and the secret values tools use.">
      <Tabs value={tab} onValueChange={(v) => router.replace(v === 'secrets' ? `${pathname}?tab=secrets` : pathname, { scroll: false })}>
        <TabsList>
          <TabsTrigger value="apps" data-testid="credentials-tab-apps">
            Auth configs
          </TabsTrigger>
          <TabsTrigger value="secrets" data-testid="credentials-tab-secrets">
            Secrets
          </TabsTrigger>
        </TabsList>
        <TabsContent value="apps" className="pt-2">
          <AppCredentialsPanel />
        </TabsContent>
        <TabsContent value="secrets" className="pt-2">
          <SecretsPanel />
        </TabsContent>
      </Tabs>
    </PageLayout>
  );
}
