'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { KeyRound } from 'lucide-react';

import { AppCredentialsPanel } from '@/components/connections/app-credentials-panel';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { useCan } from '@/hooks/me-queries';
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
  // Auth configs are read by those who manage the team's apps; anyone else is told so, and whom to ask, not shown a refusal.
  const mayRead = useCan('connections', 'manage');
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
          {mayRead === false ? (
            <p className="py-6 text-sm">
              <AskAnAdmin testId="auth-configs-why" lead="Only people who manage your team's apps see its auth configs." />
            </p>
          ) : mayRead ? (
            <AppCredentialsPanel />
          ) : null}
        </TabsContent>
        <TabsContent value="secrets" className="pt-2">
          <SecretsPanel />
        </TabsContent>
      </Tabs>
    </PageLayout>
  );
}
