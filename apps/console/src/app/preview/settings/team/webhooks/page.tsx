'use client';

import * as React from 'react';
import { Plus, Webhook } from 'lucide-react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { KeyValueEditor, type KeyValue } from '@/components/shared/setting/key-value-editor';
import { MultiSelect } from '@/components/shared/setting/pickers';
import { SecretField } from '@/components/shared/setting/secret-field';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useViewerRole } from '@/lib/settings-preview-store';

import { WEBHOOKS } from '../../_sample/data';
import { mockSave } from '../../_sample/save';

const EVENTS = ['run.finished', 'review.requested', 'sla.breached', 'guardrail.blocked'].map((e) => ({ value: e, label: e }));

/** Team › Webhooks (S12): the list is entity rows; Add webhook is a header action that opens the form in a dialog. */
export default function WebhooksPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const [open, setOpen] = React.useState(false);
  const [events, setEvents] = React.useState<string[]>([]);
  const [headers, setHeaders] = React.useState<KeyValue[]>([{ key: 'X-Source', value: 'ops-ai' }]);
  return (
    <PreviewPageLayout
      title="Webhooks"
      description="Send events to the bank's other systems as they happen"
      actions={
        <Button onClick={() => setOpen(true)} disabled={!admin}>
          <Plus className="size-4" /> Add webhook
        </Button>
      }
    >
      <div className="flex flex-col gap-2" data-testid="webhook-list">
        {WEBHOOKS.map((w) => (
          <EntityRow key={w.id} name={w.name} icon={<Webhook className="size-4" />} meta={`${w.url} · ${w.events.join(', ')}`} trailing={<StatusDot status={w.health} at={w.lastDeliveryAt} detail={w.health === 'warn' ? '2 of the last 20 deliveries failed.' : undefined} />} actions={admin ? [{ label: 'Send a test', onClick: () => mockSave('Test') }, { label: 'Pause', onClick: () => mockSave('Pause') }, { label: 'Delete', onClick: () => mockSave('Delete'), destructive: true }] : undefined} />
        ))}
      </div>
      <SettingCard id="signing" title="Signing secret" description="Every request carries a signature made with this secret. Verify it before trusting the body." help="Rotating it breaks receivers until they take the new one." locked={!admin} requiredRole="Team admin">
        <SecretField name="WEBHOOK_SIGNING" hint="a91c" lastUsedAt={new Date(Date.now() - 120_000).toISOString()} rotatedAt={new Date(Date.now() - 86_400_000 * 33).toISOString()} onRotate={async () => 'whsec_7d41c0b9e2a85f36'} canRotate={admin} />
      </SettingCard>
      <DialogShell
        open={open}
        onOpenChange={setOpen}
        size="md"
        title="Add webhook"
        description="Events are sent as they happen, signed with the secret above."
        onSubmit={() => (mockSave('Webhook'), setOpen(false))}
        footer={
          <>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Add webhook</Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField id="wh-name" label="Name">
            <Input id="wh-name" placeholder="e.g. Case system" className="bg-card" />
          </FormField>
          <FormField id="wh-url" label="URL">
            <Input id="wh-url" placeholder="e.g. https://cases.example.com/hooks" className="bg-card font-mono text-xs" />
          </FormField>
          <FormField id="wh-events" label="Events">
            <MultiSelect options={EVENTS} value={events} onChange={setEvents} noun="events" />
          </FormField>
          <FormField id="wh-headers" label="Headers" optional>
            <KeyValueEditor label="Headers" value={headers} onChange={setHeaders} />
          </FormField>
        </div>
      </DialogShell>
    </PreviewPageLayout>
  );
}
