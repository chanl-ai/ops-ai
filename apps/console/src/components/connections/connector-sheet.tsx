'use client';

import Link from 'next/link';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import type { MyConnector } from '@/hooks/connections-queries';
import { DefaultStar } from '@/components/shared/default-star';
import { usePinDefault, useTestAccount } from '@/hooks/systems-queries';
import { plural, shortDate } from '@/lib/format';
import { appPageHref } from '@/lib/app-links';
import { appStateFor } from '@/lib/app-state';

/** What a member reads on an app the team has not turned on. */
export const NOT_SET_UP = 'Not set up for your team yet';

/** Where a row names its account but the person has none connected, so no row shows a bare dash. */
export const NO_ACCOUNT = 'No account connected';


/** The person's own sign-in on the row's account ended, so it reads Sign in again rather than Connect. */
export const signInEnded = (c: MyConnector) => c.accounts.find((a) => a.connectionId === c.primaryAccountId)?.state === 'expired';

/** Whether chat uses it, as the row's In chat line says it. */
export function inChatWords(c: MyConnector): string {
  if (c.appGroup === 'on') return 'On in chat';
  if (c.appGroup === 'needs_you') return signInEnded(c) ? 'Paused until you sign in' : 'Asks when a tool needs it';
  return c.mayManage ? 'Your team sets it up first' : 'An admin sets it up first';
}

function Section({ title, children, testId }: { title: string; children: React.ReactNode; testId?: string }) {
  return (
    <section className="flex flex-col gap-2" data-testid={testId}>
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  );
}

/**
 * One connector's details, from its row: what it can do as the person (each switched-on tool with Read, Write and
 * Reviewed), where it is used as counts that link to their own pages, the in-chat default, the sign-in the admin
 * chose, the person's own accounts with Add another, then Test now and Disconnect. No related list is nested here.
 */
export function ConnectorSheet({
  connector: c,
  open,
  onOpenChange,
  onConnect,
  onDisconnect,
}: {
  connector: MyConnector | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Starts the person's own sign-in on an account of the app: another account when `another`. */
  onConnect: (c: MyConnector, another: boolean) => void;
  onDisconnect: (c: MyConnector) => void;
}) {
  const test = useTestAccount();
  const pin = usePinDefault();
  if (!c) return null;
  const connected = c.appGroup === 'on';
  const since = c.since ? ` · since ${shortDate(c.since)}` : '';
  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      testId="connector-sheet"
      widthClass="sm:max-w-lg"
      title={
        <span className="flex flex-wrap items-center gap-2">
          {c.name}
          <AppStateBadge card={c} manages={c.mayManage} testId="connector-sheet-state" />
        </span>
      }
      description={connected ? `Acts as you · ${c.account ?? 'your account'}${since}` : c.canDo}
      footerActions={
        connected && c.primaryAccountId ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={test.isPending}
              data-testid="connector-test"
              onClick={() =>
                test.mutate(
                  { appId: c.appId, accountId: c.primaryAccountId ?? '', account: 'self' },
                  {
                    onSuccess: (r) => (r.health?.status === 'ok' ? toast.success(`${c.name} works`) : toast.error(`${c.name}’s test failed`, { description: r.health?.message ?? undefined })),
                    onError: (e) => toast.error('Couldn’t test it', { description: e.message }),
                  },
                )
              }
            >
              Test now
            </Button>
            <Button size="sm" variant="outline" className="text-destructive-text" onClick={() => onDisconnect(c)} data-testid="connector-disconnect">
              Disconnect
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-6">
        <Section title={connected ? 'What it can do as you' : 'What it can do'} testId="connector-tools">
          {c.tools.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tools are switched on for the team yet.</p>
          ) : (
            <div className="flex flex-col divide-y rounded-md border">
              {c.tools.map((t) => (
                <div key={t.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span>{t.title}</span>
                  <span className="flex gap-1">
                    <Badge variant="outline">{t.access === 'read' ? 'Read' : 'Write'}</Badge>
                    {t.reviewed && <Badge variant="secondary">Reviewed</Badge>}
                  </span>
                </div>
              ))}
            </div>
          )}
          {c.tools.some((t) => t.reviewed) && <p className="text-xs text-muted-foreground">Reviewed writes wait for a person’s approval before anything changes.</p>}
        </Section>
        <Separator />
        <Section title="Used by" testId="connector-used-by">
          <p className="flex flex-wrap gap-x-2 text-sm">
            <Link className="underline-offset-4 hover:underline" href="/agents">
              {plural(c.used.agents, 'agent')}
            </Link>
            <span aria-hidden>·</span>
            <Link className="underline-offset-4 hover:underline" href="/workflows">
              {plural(c.used.workflows, 'workflow')}
            </Link>
            <span aria-hidden>·</span>
            <Link className="underline-offset-4 hover:underline" href="/tools/calls">
              {plural(c.used.callsThisWeek, 'tool call')} this week
            </Link>
          </p>
          <p className="text-xs text-muted-foreground">Every call runs as you and is in your Activity.</p>
        </Section>
        <Separator />
        <Section title="In chat">
          <p className="text-sm">{c.inChat ? 'On by default in your chats' : inChatWords(c)}</p>
          {c.inChat && <p className="text-xs text-muted-foreground">Turn it off for one chat from the connectors button in the composer.</p>}
        </Section>
        {c.authConfig && (
          <>
            <Separator />
            <Section title="Signed in through">
              <p className="text-sm">{c.authConfig}</p>
              <p className="text-xs text-muted-foreground">Your team’s admin chose this. You cannot change it here.</p>
            </Section>
          </>
        )}
        <Separator />
        <Section title={c.appGroup !== 'needs_admin' ? 'Account' : NOT_SET_UP} testId="connector-accounts">
          {c.appGroup === 'needs_admin' ? (
            // Someone who manages the team's apps is sent to the app's page for its next step; everyone else asks.
            c.mayManage ? (
              <Button size="sm" asChild>
                <Link href={appPageHref(c.appId)} data-testid="connector-sheet-turn-on">
                  {appStateFor(c.appState, c.appGroup, true).action === 'turn_on' ? 'Turn on for the team' : 'Set it up for the team'}
                </Link>
              </Button>
            ) : (
              <AskAnAdmin testId="connector-ask-admin" lead={`An admin sets ${c.name} up for the team before you can connect it.`} />
            )
          ) : (
            <>
              {c.accounts
                .filter((a) => a.state === 'connected')
                .map((a) => (
                  <div key={a.connectionId} className="flex flex-wrap items-center justify-between gap-2" data-testid={`connector-account-${a.connectionId}`}>
                    <span className="flex min-w-0 items-start gap-2">
                      {c.accountCount > 1 && (
                        <DefaultStar
                          on={a.primary}
                          label="your default"
                          busy={pin.isPending}
                          testId={`connector-make-default-${a.connectionId}`}
                          onSet={() =>
                            pin.mutate(
                              { appId: c.appId, accountId: a.connectionId },
                              {
                                onSuccess: () => toast.success(`${a.name} is your default`, { description: 'Your calls that name no account use it.' }),
                                onError: (e) => toast.error('Couldn’t make it your default', { description: e.message }),
                              },
                            )
                          }
                        />
                      )}
                      <span className="flex min-w-0 flex-col">
                        <span className="text-sm">{a.name}</span>
                        {(a.identity ?? []).length > 0 && (
                          <span className="truncate text-xs text-muted-foreground" data-testid={`connector-account-points-${a.connectionId}`}>
                            {(a.identity ?? []).map((e) => e.shown).join(' · ')}
                          </span>
                        )}
                      </span>
                    </span>
                  </div>
                ))}
              {connected ? (
                <>
                  <Button size="sm" variant="outline" className="self-start" onClick={() => onConnect(c, true)} data-testid="connector-add-account">
                    Add another account
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    {(c.personFields ?? []).length > 0
                      ? `${c.name} signs in with a key, so another account is added by someone who manages the team’s apps.`
                      : 'Another login of yours, such as a personal and an office one, with its own name and where it signs in.'}
                  </p>
                </>
              ) : (
                <Button size="sm" className="self-start" onClick={() => onConnect(c, false)} data-testid="connector-sheet-connect">
                  {signInEnded(c) ? 'Sign in again' : 'Connect'}
                </Button>
              )}
            </>
          )}
        </Section>
      </div>
    </DetailSheet>
  );
}
