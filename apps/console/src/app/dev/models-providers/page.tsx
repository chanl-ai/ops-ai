'use client';

import * as React from 'react';
import { notFound } from 'next/navigation';
import { Cpu, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { ConnectProviderDialog } from '@/components/models/connect-provider-dialog';
import { ProvidersTable } from '@/components/models/providers-table';
import { PageLayout } from '@/components/page-layout';
import { SampleDataNote } from '@/components/shared/sample-data';
import { SettingsSection } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { ModelProvider, ProviderInput } from '@/lib/types/models';

import { PROVIDERS, sampleTest } from './sample';

/**
 * The c-177 preview: Govern › Models › Providers, for the owner's design gate before build. An admin connects a model
 * provider by pasting its key, which is saved as a workspace secret; Test calls the provider with it. Mock data, dev
 * server only, not in the nav; nothing here calls a service. The live page reuses components/models.
 */
export default function ModelsProvidersPreview() {
  if (process.env.NODE_ENV !== 'development') notFound();
  return <Preview />;
}

function Preview() {
  const [providers, setProviders] = React.useState<ModelProvider[]>(PROVIDERS);
  const [dialog, setDialog] = React.useState<{ provider: ModelProvider | null } | null>(null);
  const [testing, setTesting] = React.useState<string | null>(null);

  const test = async (p: ModelProvider) => {
    setTesting(p.id);
    await new Promise((r) => setTimeout(r, 400));
    const health = sampleTest({ name: p.name, type: p.type, baseUrl: p.baseUrl, keySecret: p.keySecret ?? '' }, p.keySet && p.health.status !== 'failed');
    setProviders((all) => all.map((x) => (x.id === p.id ? { ...x, health } : x)));
    setTesting(null);
    if (health.status === 'ok') toast.success(`${p.name} answered in ${health.latencyMs} ms`);
    else toast.error(`${p.name} refused the key`, { description: health.error ?? undefined });
  };
  const save = async (input: ProviderInput) => {
    await new Promise((r) => setTimeout(r, 300));
    const health = sampleTest(input, false);
    const editing = dialog?.provider;
    setProviders((all) =>
      editing
        ? all.map((x) => (x.id === editing.id ? { ...x, keySet: true, health } : x))
        : [...all, { id: input.name.toLowerCase().replace(/[^a-z0-9]+/g, '-'), ...input, keySecret: input.keySecret, keySet: true, health, aliases: [] }],
    );
    toast.success(editing ? `Saved a new key for ${editing.name}` : `Connected ${input.name}`, { description: `The key is saved as ${input.keySecret}.` });
  };

  return (
    <PageLayout
      icon={<Cpu />}
      title="Models"
      description="The model providers this workspace calls, the key each one signs in with, and whether it answers."
      actions={
        <Button onClick={() => setDialog({ provider: null })} data-testid="provider-connect">
          <Plus /> Connect a provider
        </Button>
      }
      tabs={
        <Tabs value="providers">
          <TabsList>
            <TabsTrigger value="providers">Providers</TabsTrigger>
            <TabsTrigger value="aliases" disabled>
              Aliases
            </TabsTrigger>
            <TabsTrigger value="spend" disabled>
              Spend
            </TabsTrigger>
            <TabsTrigger value="usage" disabled>
              Usage
            </TabsTrigger>
            <TabsTrigger value="requests" disabled>
              Requests
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      <div className="flex flex-col gap-4">
        <SampleDataNote />
        <SettingsSection title="Providers" description="Agents and workflows never pick a provider: they pick an alias, and the alias routes to one of these. A provider with no key, or one that refuses its key, fails every alias that routes to it.">
          <ProvidersTable providers={providers} testing={testing} onTest={test} onChangeKey={(p) => setDialog({ provider: p })} />
        </SettingsSection>
      </div>
      <ConnectProviderDialog
        open={!!dialog}
        onOpenChange={(o) => !o && setDialog(null)}
        provider={dialog?.provider}
        onTest={async (input) => (await new Promise((r) => setTimeout(r, 400)), sampleTest(input, !!dialog?.provider?.keySet))}
        onSave={save}
      />
    </PageLayout>
  );
}
