'use client';

import * as React from 'react';
import { Cpu } from 'lucide-react';

import { ModelAliasForm } from '@/components/settings/preview/model-alias-form';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { SecretField } from '@/components/shared/setting/secret-field';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { UsageBar } from '@/components/shared/setting/usage-bar';
import { Input } from '@/components/ui/input';
import { usePreviewStore, useViewerRole } from '@/lib/settings-preview-store';

import { mockSave } from '../../_sample/save';

const usd = (n: number) => `$${n.toLocaleString('en-CA')}`;

/** Govern › Models (S43, S28): providers, aliases, keys with budgets, and the per-conversation caps, reusing what the services already hold. */
export default function ModelsPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const aliases = usePreviewStore((s) => s.aliases);
  const [calls, setCalls] = React.useState('200');
  const [cost, setCost] = React.useState('5');
  return (
    <PreviewPageLayout title="Models" description="Providers, aliases, keys and budgets for every model call">
      <section id="providers" className="flex scroll-mt-20 flex-col gap-2">
        <h2 className="text-sm font-semibold">Providers</h2>
        <EntityRow name="Harbor & Pine OpenAI" icon={<Cpu className="size-4" />} meta="openai · key held in the vault as OPENAI_PROD" trailing={<StatusDot status="ok" at={new Date(Date.now() - 180_000).toISOString()} />} actions={admin ? [{ label: 'Rebind key', onClick: () => mockSave('Rebind') }] : undefined} />
        <EntityRow name="Harbor & Pine Anthropic" icon={<Cpu className="size-4" />} meta="anthropic · key held in the vault as ANTHROPIC_PROD" trailing={<StatusDot status="warn" detail="Rate limit reached twice in the last hour." at={new Date(Date.now() - 900_000).toISOString()} />} actions={admin ? [{ label: 'Rebind key', onClick: () => mockSave('Rebind') }] : undefined} />
      </section>
      <section id="aliases" className="flex scroll-mt-20 flex-col gap-3">
        <h2 className="text-sm font-semibold">Aliases</h2>
        <div className="flex flex-col gap-2" data-testid="alias-list">
          {aliases.map((a) => (
            <EntityRow key={a.id} name={a.alias} icon={<Cpu className="size-4" />} meta={`${a.provider} · ${a.model} · cleared for ${a.clearance}`} />
          ))}
        </div>
        <ModelAliasForm shell="card" locked={!admin} />
      </section>
      <section id="keys" className="flex scroll-mt-20 flex-col gap-3">
        <h2 className="text-sm font-semibold">Keys and budgets</h2>
        <SettingCard title="agents-service key" description="The key agents-service spends from." help="Rotating keeps the old key working for one hour." locked={!admin} requiredRole="Admin">
          <div className="flex flex-col gap-4">
            <SecretField name="mk_agents" hint="7e2c" lastUsedAt={new Date(Date.now() - 20_000).toISOString()} rotatedAt={new Date(Date.now() - 86_400_000 * 16).toISOString()} onRotate={async () => 'mk_live_c41d9a07b52e'} canRotate={admin} />
            <UsageBar label="Monthly budget" used={4120} limit={5000} format={usd} />
            <UsageBar label="Requests a minute" used={310} limit={300} />
          </div>
        </SettingCard>
      </section>
      <SettingCard id="caps" title="Per-conversation caps" description="One conversation stops here and asks its owner to continue." help="An agent's own USD ceiling per run still applies." onSave={() => mockSave('Caps')} dirty={calls !== '200' || cost !== '5'} locked={!admin} requiredRole="Admin">
        <div className="flex flex-wrap gap-4">
          <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            Model calls
            <Input type="number" min={1} value={calls} onChange={(e) => setCalls(e.target.value)} className="w-32 bg-card text-sm" />
          </label>
          <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            Cost in USD
            <Input type="number" min={1} value={cost} onChange={(e) => setCost(e.target.value)} className="w-32 bg-card text-sm" />
          </label>
        </div>
      </SettingCard>
    </PreviewPageLayout>
  );
}
