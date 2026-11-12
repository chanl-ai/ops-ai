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
    <PageLayout icon={KeyRound} title="Secrets" description="Values the tools send, such as API keys. A value is encrypted, never shown again, and scrubbed from what a system answers.">
      <SecretsPanel />
    </PageLayout>
  );
}
