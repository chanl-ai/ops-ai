'use client';

import * as React from 'react';
import { notFound, useParams } from 'next/navigation';
import { ExternalLink, KeyRound, Plug, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

import { ConnectSystemDialog } from '@/components/connections/connect-system-dialog';
import { HealthLine } from '@/components/connections/health-line';
import { CONNECTED_MESSAGE, openSignIn, type ConnectedMessage } from '@/components/connections/sign-in';
import { PageLayout } from '@/components/page-layout';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  type ConnectionDetail,
  useChangeConnection,
  useConnectionDetail,
  useConnectionKinds,
  useStartSignIn,
  useTestEnvironment,
} from '@/hooks/systems-queries';
import { leading, type Kinds } from '@/lib/connect-plan';
import { shortDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { personalSignIn, realConnections } from '@/lib/api';

type Choice = 'team' | 'person' | 'backup';

const CHOICES: { value: Choice; label: string; hint: string }[] = [
  { value: 'team', label: 'Team account', hint: 'Every call signs in as one account the team connects.' },
  {
    value: 'person',
    label: 'Each person’s own account',
    hint: 'Calls act as the person who asked or started the run. Anyone who has not connected is asked.',
  },
  {
    value: 'backup',
    label: 'Each person, team account as backup',
    hint: 'Runs with nobody behind them, such as schedules and mailboxes, use the team account. People are still asked.',
  },
];

const STATUS: Record<string, string> = {
  draft: 'Draft',
  healthy: 'Healthy',
  needs_reconnect: 'Needs reconnect',
  expiring: 'Expiring',
  revoked: 'Revoked',
  error: 'Error',
};

const choiceOf = (c: ConnectionDetail): Choice =>
  c.signIn === 'team' || !c.signIn ? 'team' : c.signIn === 'person_or_team' && c.teamBackup ? 'backup' : 'person';

type EnvState = ConnectionDetail['environments'][string];

/**
 * One connection (c-558, c-580): whose account its tools use, each environment's keys and last test, Test connection
 * with the person's own account or the team's, signing the team account in, and who has connected. Only the settings
 * the connection's kind supports are offered; only an admin of the team changes them, tests the team's account or
 * edits keys, which open the one connect dialog on that environment.
 */
function ConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const conn = useConnectionDetail(id);
  const kinds = useConnectionKinds();
  const change = useChangeConnection();
  const test = useTestEnvironment();
  const start = useStartSignIn();
  const [choice, setChoice] = React.useState<Choice | null>(null);
  const [editing, setEditing] = React.useState<{ environment?: string } | null>(null);
  const [testingAll, setTestingAll] = React.useState(false);
  const opened = React.useRef<Window | null>(null);

  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage>) => {
      if (e.origin !== window.location.origin || e.data?.type !== CONNECTED_MESSAGE || e.source !== opened.current) return;
      opened.current = null;
      toast.success(`${e.data.connection} is connected`);
      void conn.refetch();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [conn]);

  if (conn.isPending || kinds.isPending) return <RecordSkeleton />;
  if (conn.isError) return <QueryError what="this connection" onRetry={() => void conn.refetch()} retrying={conn.isFetching} error={conn.error} />;
  if (kinds.isError)
    return <QueryError what="how this connection signs in" onRetry={() => void kinds.refetch()} retrying={kinds.isFetching} error={kinds.error} />;
  const c = conn.data;
  const all = kinds.data as Kinds;
  const kind = all.kinds.find((k) => k.id === c.authKind);
  const offered = kind?.perPerson ? CHOICES : CHOICES.filter((x) => x.value === 'team');
  const current = choiceOf(c);
  const picked = choice ?? current;
  const set = all.environments.filter((e) => c.environments[e.id]?.set).map((e) => e.id);
  // The environment a test and a sign-in use: the production one once it is set, else the first that is.
  const environment = leading(all, set) ?? all.environments[0]?.id ?? 'test';
  const personal = c.signIn === 'person' || c.signIn === 'person_or_team';
  // Someone signs the team's account in once for a kind that signs in, unless every call acts as its own person.
  const teamSignIn = Boolean(kind?.signsIn) && c.mayManage && (c.signIn === 'team' || c.signIn === 'person_or_team' || !c.signIn);
  const needsReconnect = c.status === 'needs_reconnect';

  const save = () =>
    change.mutate(
      {
        path: { connection_id: c.id },
        body: { revision: c.revision, signIn: picked === 'team' ? 'team' : picked === 'backup' ? 'person_or_team' : 'person', teamBackup: picked === 'backup' },
      },
      {
        onSuccess: () => (setChoice(null), toast.success('Sign-in setting saved')),
        onError: (e) => toast.error('Couldn’t save the sign-in setting', { description: e.message }),
      },
    );
  const runTest = (account: 'team' | 'self', env = environment) =>
    test.mutateAsync({ connectionId: c.id, environment: env, account }).catch((e: Error) => {
      toast.error('Couldn’t run the test', { description: e.message });
    });
  const testAll = async () => {
    setTestingAll(true);
    for (const env of set) await runTest('team', env);
    setTestingAll(false);
  };
  const signIn = (account: 'team' | 'self') =>
    start.mutate(
      { connectionId: c.id, environment, account },
      {
        onSuccess: (s) => void (opened.current = openSignIn(s, c.id)),
        onError: (e) => toast.error('Couldn’t start the sign-in', { description: e.message }),
      },
    );

  return (
    <PageLayout
      icon={Plug}
      title={c.name}
      description={`${c.kindLabel}, ${all.environments.find((e) => e.id === environment)?.label ?? environment}`}
      breadcrumbs={[{ label: 'Tools', href: '/tools' }, { label: 'Connections', href: realConnections ? '/integrations' : undefined }, { label: c.name }]}
      badge={<Badge variant={c.status === 'healthy' ? 'secondary' : 'outline'}>{STATUS[c.status] ?? c.status}</Badge>}
    >
      <div className="flex min-w-0 flex-col gap-4">
        <Section
          title="Whose account do tools use?"
          description={
            kind?.perPerson
              ? 'A person who has not connected is asked in the chat, never covered by someone else’s account.'
              : `${c.kindLabel} signs in with the team’s account only.`
          }
          actions={
            c.mayManage && kind?.perPerson ? (
              <LoadingButton size="sm" onClick={save} isLoading={change.isPending} disabled={picked === current} data-testid="sign-in-save">
                Save
              </LoadingButton>
            ) : undefined
          }
        >
          <RadioGroup
            value={picked}
            onValueChange={(v) => setChoice(v as Choice)}
            disabled={!c.mayManage}
            className="grid gap-2 md:grid-cols-3"
            data-testid="sign-in-setting"
          >
            {offered.map((o) => (
              <label
                key={o.value}
                htmlFor={`sign-in-${o.value}`}
                className={cn(
                  'flex items-start gap-3 rounded-md border p-3',
                  c.mayManage ? 'cursor-pointer' : 'cursor-default',
                  picked === o.value && 'border-primary bg-primary/5',
                )}
              >
                <RadioGroupItem value={o.value} id={`sign-in-${o.value}`} className="mt-0.5" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{o.label}</span>
                  <span className="block text-xs text-muted-foreground">{o.hint}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </Section>

        <Section
          title="Health"
          description="Test connection signs in as a call would and reads the system's test address."
          actions={
            <div className="flex flex-wrap gap-2">
              {teamSignIn && (
                <Button
                  size="sm"
                  variant={needsReconnect ? 'default' : 'outline'}
                  onClick={() => signIn('team')}
                  disabled={start.isPending}
                  data-testid="connect-team"
                >
                  {needsReconnect ? <RefreshCw /> : <ExternalLink />}
                  {needsReconnect ? 'Reconnect the team account' : 'Connect the team account'}
                </Button>
              )}
              {/* A person's own key or password is given in the chat card (its own card); only a sign-in opens a window. */}
              {personal && kind?.signsIn && (
                <Button size="sm" variant="outline" onClick={() => signIn('self')} disabled={start.isPending} data-testid="connect-own">
                  <ExternalLink />
                  Connect your account
                </Button>
              )}
              {c.mayManage && (
                <LoadingButton
                  size="sm"
                  variant="outline"
                  onClick={() => void runTest('team')}
                  isLoading={test.isPending && test.variables?.account === 'team' && !testingAll}
                  data-testid="test-team"
                >
                  Test the team account
                </LoadingButton>
              )}
              {personal && (
                <LoadingButton
                  size="sm"
                  onClick={() => void runTest('self')}
                  isLoading={test.isPending && test.variables?.account === 'self'}
                  data-testid="test-own"
                >
                  Test connection
                </LoadingButton>
              )}
            </div>
          }
        >
          {c.health ? (
            <HealthLine health={c.health} />
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="health-none">
              Not tested yet.
            </p>
          )}
        </Section>

        <Section
          title="Environments"
          description="Each environment's keys and its last test. A saved key is sealed and never shown."
          flush
          actions={
            c.mayManage && set.length > 1 ? (
              <LoadingButton size="sm" variant="outline" onClick={() => void testAll()} isLoading={testingAll} data-testid="test-all">
                Test all
              </LoadingButton>
            ) : undefined
          }
        >
          <Rows testId="environments">
            {all.environments.map((e) => {
              const state: EnvState | undefined = c.environments[e.id];
              return (
                <Row
                  key={e.id}
                  wrap
                  title={
                    <span className="flex items-center gap-2">
                      {e.label}
                      {e.production && <Badge variant="outline">Live runs</Badge>}
                    </span>
                  }
                  description={state?.set ? undefined : 'No keys yet'}
                  trailing={
                    c.mayManage ? (
                      <>
                        {state?.set && (
                          <LoadingButton
                            size="sm"
                            variant="ghost"
                            onClick={() => void runTest('team', e.id)}
                            isLoading={test.isPending && test.variables?.environment === e.id}
                            data-testid={`test-env-${e.id}`}
                          >
                            Run test
                          </LoadingButton>
                        )}
                        <Button size="sm" variant="outline" onClick={() => setEditing({ environment: e.id })} data-testid={`edit-${e.id}`}>
                          <KeyRound />
                          {state?.set ? 'Edit keys' : 'Add keys'}
                        </Button>
                      </>
                    ) : undefined
                  }
                >
                  {state?.health && (
                    <div className="pt-2">
                      <HealthLine health={state.health} testId={`health-${e.id}`} who={false} />
                    </div>
                  )}
                </Row>
              );
            })}
          </Rows>
        </Section>

        {personal && (
          <Section title="People connected" flush>
            {c.people?.length ? (
              <Rows testId="people-connected">
                {c.people.map((p) => (
                  <Row
                    key={`${p.personId}:${p.environment}`}
                    wrap
                    title={p.account ?? p.personId}
                    description={[p.environment, p.since ? `since ${shortDate(p.since)}` : null].filter(Boolean).join(' · ')}
                    trailing={<Badge variant="secondary">Connected</Badge>}
                  />
                ))}
              </Rows>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">Nobody has connected yet. People are asked in the chat when a tool needs their account.</p>
            )}
          </Section>
        )}
      </div>
      {editing && (
        <ConnectSystemDialog
          target={{ kind: 'connection', connectionId: c.id }}
          mode="edit"
          environment={editing.environment}
          open
          onOpenChange={(o) => !o && setEditing(null)}
        />
      )}
    </PageLayout>
  );
}

/** Offered once the personal sign-in switch or the real-connections switch is on (lib/api/index.ts). */
export default function Page() {
  if (!personalSignIn && !realConnections) notFound();
  return <ConnectionPage />;
}
