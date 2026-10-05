'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpCircle, KeyRound, Pause, Play, Rocket } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { Input } from '@/components/ui/input';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import type { Deployment, DeploymentPatch } from '@/lib/types/domain';

import { CHANNELS, DeploymentSetup, DeploymentStatusBadge, EnvironmentBadge, VersionCell } from './deployment-meta';

/** One deployment: how to connect it, which version it serves, and the actions that change what customers get. */
export function DeploymentSheet({
  deployment: d,
  navigation,
  onOpenChange,
  onUpdate,
  updating,
  onRotateKey,
  rotating,
  onPromote,
  promoting,
  productionTwins,
}: {
  deployment: Deployment | null;
  navigation?: DetailSheetNavigation;
  onOpenChange: (open: boolean) => void;
  onUpdate: (patch: DeploymentPatch, done: string) => void;
  updating: boolean;
  onRotateKey: () => Promise<string>;
  rotating: boolean;
  onPromote: (input: { name: string; allowedDomains?: string[] }) => Promise<unknown>;
  promoting: boolean;
  /** Production deployments of the same workflow and channel, to stop promoting a duplicate. */
  productionTwins: Deployment[];
}) {
  const [newKey, setNewKey] = React.useState<string | null>(null);
  const [confirmRotate, setConfirmRotate] = React.useState(false);
  const [confirmMove, setConfirmMove] = React.useState(false);
  const [promoteOpen, setPromoteOpen] = React.useState(false);
  const [promoteName, setPromoteName] = React.useState('');
  const [promoteDomains, setPromoteDomains] = React.useState('');
  const [promoteError, setPromoteError] = React.useState<string | null>(null);
  const openPromote = () => {
    if (!d) return;
    setPromoteName(d.name.replace(/\s*\(staging\)\s*$/i, ''));
    setPromoteDomains(d.widget?.allowedDomains.filter((x) => !x.startsWith('staging.')).join(', ') ?? '');
    setPromoteError(null);
    setPromoteOpen(true);
  };

  return (
    <>
      <DetailSheet
        open={!!d}
        onOpenChange={onOpenChange}
        title={d?.name}
        description={d ? `${CHANNELS[d.channel].label} · ${d.workflowName} · updated ${relativeTime(d.updatedAt)}` : undefined}
        tags={
          d && (
            <>
              <EnvironmentBadge environment={d.environment} />
              <DeploymentStatusBadge status={d.status} sync={d.email?.sync} />
            </>
          )
        }
        navigation={navigation}
        scrollKey={d?.id}
        testId="deployment-sheet"
        footerActions={
          d && (
            <>
              <Button size="sm" variant="outline" disabled={updating} onClick={() => onUpdate({ status: d.status === 'active' ? 'paused' : 'active' }, d.status === 'active' ? `Paused ${d.name}` : `Resumed ${d.name}`)}>
                {d.status === 'active' ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                {d.status === 'active' ? 'Pause' : 'Resume'}
              </Button>
              {d.environment === 'staging' && (
                <Button size="sm" variant="outline" disabled={updating} onClick={openPromote}>
                  <Rocket className="size-3.5" /> Promote to production
                </Button>
              )}
            </>
          )
        }
      >
        {d && (
          <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
              <FieldSectionLabel>Serves</FieldSectionLabel>
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
                <div>
                  <Link href={`/workflows/${d.workflowId}`} className="font-medium hover:underline">
                    {d.workflowName}
                  </Link>
                  <div className="mt-0.5">
                    <VersionCell d={d} />
                  </div>
                </div>
                {d.version < d.latestVersion && (
                  <LoadingButton size="sm" variant="outline" isLoading={updating} onClick={() => setConfirmMove(true)}>
                    <ArrowUpCircle className="size-3.5" /> Move to v{d.latestVersion}
                  </LoadingButton>
                )}
              </div>
            </section>

            <section className="flex flex-col gap-2">
              <FieldSectionLabel>Connect</FieldSectionLabel>
              <DeploymentSetup
                d={d}
                reconnecting={updating}
                onReconnect={() => d.email && onUpdate({ email: { ...d.email, sync: { status: 'syncing', lastMessageAt: d.email.sync?.lastMessageAt ?? null, messages24h: d.email.sync?.messages24h ?? 0 } } }, `Reconnected ${d.email.inboundAddress}`)}
              />
            </section>

            {d.channel === 'api' && (
              <section className="flex flex-col gap-2">
                <FieldSectionLabel>API key</FieldSectionLabel>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
                  <code className="font-mono text-sm">{d.api?.keyPrefix}••••••••</code>
                  <Button size="sm" variant="outline" onClick={() => setConfirmRotate(true)}>
                    <KeyRound className="size-3.5" /> Rotate key
                  </Button>
                </div>
              </section>
            )}

            <section className="flex flex-col gap-2">
              <FieldSectionLabel>Last 24 hours</FieldSectionLabel>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-sm">
                <div className="bg-card p-3">
                  <dt className="text-xs text-muted-foreground">{d.channel === 'api' ? 'Requests' : d.channel === 'email' ? 'Threads' : 'Conversations'}</dt>
                  <dd className="text-lg font-semibold tabular-nums">{d.traffic24h.toLocaleString()}</dd>
                </div>
                <div className="bg-card p-3">
                  <dt className="text-xs text-muted-foreground">Errors</dt>
                  <dd className="text-lg font-semibold tabular-nums">{d.errors24h}</dd>
                </div>
              </dl>
            </section>
          </div>
        )}
      </DetailSheet>

      <DialogShell
        open={confirmMove}
        onOpenChange={setConfirmMove}
        size="sm"
        title={`Move ${d?.name} to v${d?.latestVersion}?`}
        description={
          d?.environment === 'production'
            ? `Customers on this ${d ? CHANNELS[d.channel].label.toLowerCase() : 'channel'} get v${d?.latestVersion} on their next message. Conversations in progress finish on v${d?.version}.`
            : `Staging switches to v${d?.latestVersion} immediately.`
        }
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmMove(false)} disabled={updating}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={updating}
              onClick={() => {
                if (!d) return;
                onUpdate({ version: d.latestVersion }, `${d.name} now serves v${d.latestVersion}`);
                setConfirmMove(false);
              }}
            >
              Move to v{d?.latestVersion}
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">You can move back from version history if v{d?.latestVersion} misbehaves.</p>
      </DialogShell>

      <DialogShell
        open={promoteOpen}
        onOpenChange={setPromoteOpen}
        size="sm"
        title="Promote to production"
        description="Creates a production deployment with the same settings. The staging one keeps running for testing."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setPromoteOpen(false)} disabled={promoting}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={promoting}
              loadingText="Promoting…"
              onClick={async () => {
                const domains = promoteDomains.split(',').map((x) => x.trim()).filter(Boolean);
                if (!promoteName.trim()) return setPromoteError('Name the production deployment.');
                const twin = productionTwins.find((t) => t.name.toLowerCase() === promoteName.trim().toLowerCase());
                if (twin) return setPromoteError(`${twin.name} is already in production. Open it and move it to v${d?.version} instead.`);
                if (d?.channel === 'widget' && !domains.length) return setPromoteError('Add the production domains the widget may load on.');
                try {
                  await onPromote({ name: promoteName.trim(), allowedDomains: d?.channel === 'widget' ? domains : undefined });
                  setPromoteOpen(false);
                } catch (e) {
                  setPromoteError((e as Error).message);
                }
              }}
            >
              Promote
            </LoadingButton>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField id="promote-name" label="Production name" error={promoteError && (!promoteName.trim() || d?.channel !== 'widget' || promoteError.includes('already in production')) ? promoteError : undefined}>
            <Input id="promote-name" value={promoteName} onChange={(e) => (setPromoteName(e.target.value), setPromoteError(null))} />
          </FormField>
          {d?.channel === 'widget' && (
            <FormField id="promote-domains" label="Production domains" hint="Comma separated. Staging domains are left out." error={promoteError && promoteName.trim() && !promoteError.includes('already in production') ? promoteError : undefined}>
              <Input id="promote-domains" value={promoteDomains} onChange={(e) => (setPromoteDomains(e.target.value), setPromoteError(null))} placeholder="e.g. www.example.com" />
            </FormField>
          )}
        </div>
      </DialogShell>

      <DialogShell
        open={confirmRotate || !!newKey}
        onOpenChange={(o) => {
          if (!o) {
            setConfirmRotate(false);
            setNewKey(null);
          }
        }}
        size="sm"
        title={newKey ? 'Copy the new key now' : 'Rotate the API key?'}
        description={newKey ? 'It is shown once. The old key stopped working when this one was issued.' : 'The current key stops working immediately. Callers fail until they use the new key.'}
        footer={
          <div className="flex w-full justify-end gap-2">
            {newKey ? (
              <Button
                onClick={() => {
                  setNewKey(null);
                  setConfirmRotate(false);
                }}
              >
                Done
              </Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setConfirmRotate(false)} disabled={rotating}>
                  Cancel
                </Button>
                <LoadingButton variant="destructive" isLoading={rotating} onClick={async () => setNewKey(await onRotateKey())}>
                  Rotate key
                </LoadingButton>
              </>
            )}
          </div>
        }
      >
        {newKey ? (
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
            <code className="min-w-0 flex-1 truncate font-mono text-sm">{newKey}</code>
            <CopyButton text={newKey} variant="outline" size="sm" />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Use this when a key may have leaked or a caller is retired.</p>
        )}
      </DialogShell>
    </>
  );
}
