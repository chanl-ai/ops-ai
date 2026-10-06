'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Ban, Cable, ChevronDown, KeyRound, LogIn, RefreshCw, SearchX, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { vaultProblem } from '@/components/integrations/connect-dialog';
import { AUTH, IntegrationStatusBadge, KIND, SystemMark } from '@/components/integrations/integration-meta';
import { ActivityPanel, AuditPanel, OverviewPanel, ScopesPanel, UsedByPanel } from '@/components/integrations/integration-panels';
import { RevokeDialog } from '@/components/integrations/revoke-dialog';
import { ScopePicker } from '@/components/integrations/scope-picker';
import { PageLayout } from '@/components/page-layout';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout, RecordStatRow } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { ExpiryText } from '@/components/tools/module-meta';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useCheckIntegration, useIntegration, useReconnectIntegration, useRequestScopes, useRevokeIntegrations, useRotateIntegration } from '@/hooks/integration-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { plural, shortDate } from '@/lib/format';
import type { IntegrationDetail } from '@/lib/types/integrations';

const TABS = ['overview', 'scopes', 'used-by', 'activity', 'audit'] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { overview: 'Overview', scopes: 'Scopes', 'used-by': 'Used by', activity: 'Activity', audit: 'Audit' };

export default function IntegrationPage() {
  const { id } = useParams<{ id: string }>();
  const query = useIntegration(id);
  if (query.isPending) return <RecordSkeleton />;
  if (query.isError)
    return (
      <PageLayout icon={Cable} title="Integration" backHref="/integrations">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Integration not found" description="It may have been removed, or the link is wrong." action={{ label: 'Back to integrations', href: '/integrations' }} />
        ) : (
          <QueryError what="this integration" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );
  return <IntegrationView i={query.data} />;
}

function IntegrationView({ i }: { i: IntegrationDetail }) {
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'overview');
  const reconnect = useReconnectIntegration();
  const rotate = useRotateIntegration();
  const check = useCheckIntegration();
  const revoke = useRevokeIntegrations();
  const requestScopes = useRequestScopes();
  const [dialog, setDialog] = React.useState<'reconnect' | 'rotate' | 'revoke' | 'scopes' | null>(null);
  const [ref, setRef] = React.useState('');
  const [refTouched, setRefTouched] = React.useState(false);
  const [wanted, setWanted] = React.useState<string[]>([]);
  const [why, setWhy] = React.useState('');
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });
  const oauth = i.authMethod === 'oauth_consent';
  const total = i.usedBy.sources + i.usedBy.modules + i.usedBy.mailboxes;
  const refProblem = vaultProblem(ref) ?? (ref.trim() === i.credentialRef ? 'That is the reference already in use.' : null);

  const openRotate = () => {
    setRef(i.credentialRef ?? '');
    setRefTouched(false);
    setDialog('rotate');
  };
  const recheck = () =>
    check.mutate(i.id, {
      onSuccess: (x) => (x.checks[0]?.ok ? toast.success('Health check passed', { description: `${x.checks[0].latencyMs} ms` }) : toast.error('Health check failed', { description: x.checks[0]?.message })),
      onError: fail('run the check'),
    });
  const fix = () => (i.fix?.action === 'rotate' ? openRotate() : i.fix?.action === 'reconnect' ? setDialog('reconnect') : recheck());

  return (
    <PageLayout
      icon={<SystemMark kind={i.kind} size="lg" />}
      title={i.name}
      badge={<IntegrationStatusBadge status={i.status} />}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>{KIND[i.kind].label}</span>
          <span>{AUTH[i.authMethod].label}</span>
          <span>Owner {i.ownerTeam}</span>
          <span className="max-w-full truncate font-mono text-xs">{i.instanceUrl}</span>
        </span>
      }
      backHref="/integrations"
      actions={
        <div className="flex items-center gap-2">
          <LoadingButton variant="outline" isLoading={check.isPending} disabled={i.status === 'revoked'} onClick={recheck}>
            <RefreshCw className="size-4" /> Re-check
          </LoadingButton>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>
                Actions <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={i.status === 'healthy'} onClick={() => setDialog('reconnect')}>
                <LogIn className="size-4" /> {oauth ? 'Reconnect and renew consent' : 'Reconnect'}
              </DropdownMenuItem>
              <DropdownMenuItem disabled={oauth || i.status === 'revoked'} onClick={openRotate}>
                <KeyRound className="size-4" /> Rotate credential reference
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={i.status === 'revoked'}
                onClick={() => {
                  setWanted([]);
                  setWhy('');
                  setDialog('scopes');
                }}
              >
                <ShieldCheck className="size-4" /> Request more scopes
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" disabled={i.status === 'revoked'} onClick={() => setDialog('revoke')}>
                <Ban className="size-4" /> Revoke
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      }
    >
      <RecordLayout
        rail={
          <AttributeCard title="Connection" icon={Cable}>
            <FieldRow label="System" value={KIND[i.kind].label} />
            <FieldRow label="Sign-in" value={AUTH[i.authMethod].label} />
            <FieldRow label={i.tenant ? 'Tenant' : 'Instance'} value={i.tenant ?? i.instanceUrl.replace(/^https?:\/\//, '')} mono />
            {i.tenant && <FieldRow label="Instance" value={i.instanceUrl.replace(/^https?:\/\//, '')} mono />}
            <FieldRow label="Owner" value={i.ownerTeam} />
            <FieldRow label="Created by" value={i.createdBy} />
            <FieldRow label="Created" value={shortDate(i.createdAt)} />
            <FieldRow label="Expiry" value={i.status === 'revoked' ? 'Revoked' : <ExpiryText at={i.expiresAt} />} />
            <FieldRow label="Rotate by" value={oauth ? 'Renewed by consent' : i.rotateBy ? <ExpiryText at={i.rotateBy} /> : undefined} />
            <FieldRow label="Credential" value={oauth ? 'Token held in the vault' : <span title={i.credentialRef}>{i.credentialRef}</span>} mono={!oauth} />
          </AttributeCard>
        }
      >
        <div className="flex flex-col gap-4">
          <RecordStatRow
            stats={[
              { label: 'Sources', value: i.usedBy.sources },
              { label: 'Tool modules', value: i.usedBy.modules },
              { label: 'Mailboxes', value: i.usedBy.mailboxes },
            ]}
          />
          <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
            <TabsList>
              {TABS.map((t) => (
                <TabsTrigger key={t} value={t}>
                  {LABEL[t]}
                  {t === 'used-by' && <span className="ml-1 text-muted-foreground tabular-nums">{total}</span>}
                  {t === 'scopes' && i.scopeRequests.some((r) => r.status === 'pending') && <span className="ml-1 text-amber-700 tabular-nums dark:text-amber-400">1</span>}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          {tab === 'overview' && <OverviewPanel i={i} onFix={fix} fixing={reconnect.isPending || rotate.isPending} onRecheck={recheck} rechecking={check.isPending} />}
          {tab === 'scopes' && (
            <ScopesPanel
              i={i}
              onRequest={() => {
                setWanted([]);
                setWhy('');
                setDialog('scopes');
              }}
            />
          )}
          {tab === 'used-by' && <UsedByPanel i={i} onRevoke={() => setDialog('revoke')} />}
          {tab === 'activity' && <ActivityPanel i={i} />}
          {tab === 'audit' && <AuditPanel i={i} />}
        </div>
      </RecordLayout>

      <DialogShell
        open={dialog === 'reconnect'}
        onOpenChange={(o) => !o && setDialog(null)}
        size="sm"
        title={oauth ? 'Renew consent?' : `Reconnect ${i.name}?`}
        description={
          oauth
            ? `An administrator signs in and approves the same ${plural(i.scopes.length, 'scope')} again. Consent then runs for 90 days.`
            : 'The gateway signs in again with the current vault reference. If the secret changed, rotate the reference instead.'
        }
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDialog(null)} disabled={reconnect.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={reconnect.isPending}
              loadingText={oauth ? 'Signing in…' : 'Reconnecting…'}
              onClick={() =>
                reconnect.mutate(i.id, {
                  onSuccess: () => {
                    toast.success(`${i.name} reconnected`, { description: total ? `${plural(total, 'dependant')} resume.` : undefined });
                    setDialog(null);
                  },
                  onError: fail('reconnect'),
                })
              }
            >
              {oauth ? `Sign in and renew` : 'Reconnect'}
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">{total ? `${plural(total, 'dependant')} use this connection and resume as soon as it is healthy.` : 'Nothing uses this connection yet.'}</p>
      </DialogShell>

      <DialogShell
        open={dialog === 'rotate'}
        onOpenChange={(o) => !o && setDialog(null)}
        size="sm"
        title="Rotate the credential reference"
        description="Point the connection at the new secret’s vault path. The gateway uses it from the next call; a wrong path fails every call."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDialog(null)} disabled={rotate.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={rotate.isPending}
              onClick={() => {
                setRefTouched(true);
                if (refProblem) return;
                rotate.mutate(
                  { id: i.id, credentialRef: ref.trim() },
                  {
                    onSuccess: (x) => {
                      toast.success('Reference saved', { description: x.checks[0]?.ok ? 'The check with the new reference passed.' : 'The next call uses it.' });
                      setDialog(null);
                    },
                    onError: fail('save the reference'),
                  },
                );
              }}
            >
              Save reference
            </LoadingButton>
          </div>
        }
      >
        <FormField id="rot-ref" label="Vault path" error={refTouched ? (refProblem ?? undefined) : undefined} hint={i.credentialRef ? `Now ${i.credentialRef}` : undefined}>
          <Input id="rot-ref" value={ref} onChange={(e) => setRef(e.target.value)} className="font-mono text-sm" placeholder="e.g. vault://prod/integrations/servicenow/client-secret" aria-invalid={refTouched && !!refProblem} autoComplete="off" spellCheck={false} />
        </FormField>
      </DialogShell>

      <DialogShell
        open={dialog === 'scopes'}
        onOpenChange={(o) => !o && setDialog(null)}
        size="md"
        title="Request more scopes"
        description={`${i.systemOwner} decides the request. Until then the connection keeps the scopes it has.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDialog(null)} disabled={requestScopes.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={requestScopes.isPending}
              disabled={!wanted.length || !why.trim()}
              onClick={() =>
                requestScopes.mutate(
                  { id: i.id, scopes: wanted, justification: why },
                  {
                    onSuccess: () => {
                      toast.success('Scope request sent', { description: `Waiting for ${i.systemOwner}.` });
                      setDialog(null);
                      setTab('scopes');
                    },
                    onError: fail('send the request'),
                  },
                )
              }
            >
              Send request
            </LoadingButton>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <ScopePicker scopes={i.availableScopes} locked={i.scopes} selected={wanted} onChange={setWanted} />
          <FormField id="sr-why" label="What they are for">
            <Textarea id="sr-why" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Branch chat should cite knowledge articles on account opening" />
          </FormField>
        </div>
      </DialogShell>

      <RevokeDialog
        open={dialog === 'revoke'}
        onOpenChange={(o) => !o && setDialog(null)}
        names={[i.name]}
        impact={{ dependants: i.dependants, sources: i.usedBy.sources, modules: i.usedBy.modules, mailboxes: i.usedBy.mailboxes }}
        impactLoading={false}
        isPending={revoke.isPending}
        onConfirm={(reason) =>
          revoke.mutateAsync({ ids: [i.id], reason }).then(
            (r) => {
              if (r.skipped.length) toast.error('Couldn’t revoke', { description: r.skipped[0].reason });
              else toast.success(`Revoked ${i.name}`, { description: total ? `${plural(total, 'dependant')} stopped.` : undefined });
              setDialog(null);
              router.refresh();
            },
            fail('revoke the connection'),
          )
        }
      />
    </PageLayout>
  );
}
