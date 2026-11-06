'use client';

import { KeyRound } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { SecretsPanel } from '@/components/secrets/secrets-panel';

/**
 * Secrets in the Apps menu: the values tools send, such as API keys. An app's auth configs belong to that app and are
 * on its page's Auth configs tab, so they are not listed here a second time.
 */
export default function SecretsPage() {
  return (
    <PageLayout icon={KeyRound} title="Secrets" description="The secret values tools send, such as API keys.">
      <SecretsPanel />
    </PageLayout>
  );
}
