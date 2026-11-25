'use client';

import Link from 'next/link';
import { toast } from 'sonner';
import { Layers, MessageSquare, PlugZap, Wrench } from 'lucide-react';

import { AttributeCard } from '@/components/shared/record-layout';
import { DefaultStar } from '@/components/shared/default-star';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { CouldntConnect, MyAppAction, NOT_SET_UP, inChatWords, signInEnded, type MyAppControls } from '@/components/connections/my-app-actions';
import type { MyConnector } from '@/hooks/connections-queries';
import { usePinDefault, useTestAccount } from '@/hooks/systems-queries';
import { plural, shortDate } from '@/lib/format';

/**
 * One app on the person's own page: its state and next step, what it can do as them (each switched-on tool with Read,
 * Write and Reviewed), their accounts with Add another and Test now, where it is used as counts that link to their own
 * pages, and the in-chat default. No related list is nested here.
 */
export function MyAppDetails({ c, controls }: { c: MyConnector; controls: MyAppControls }) {
  const test = useTestAccount();
  const pin = usePinDefault();
  const connected = c.appGroup === 'on';
  return (
    <div className="flex max-w-3xl flex-col gap-4" data-testid="my-app">
      <AttributeCard title="Your sign-in" icon={PlugZap} action={<AppStateBadge card={c} manages={c.mayManage} testId="my-app-state" />} testId="connector-accounts">
        <div className="flex flex-col gap-3">
          <CouldntConnect appId={c.appId} why={controls.failed[c.appId]} />
          {c.appGroup === 'needs_admin' && <p className="text-sm text-muted-foreground">{NOT_SET_UP}.</p>}
          {c.accounts
            .filter((a) => a.state === 'connected')
            .map((a) => (
              <div key={a.connectionId} className="flex min-w-0 items-start gap-2" data-testid={`connector-account-${a.connectionId}`}>
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
              </div>
            ))}
          {connected && c.since && <p className="text-xs text-muted-foreground">{`Acts as you · ${c.account ?? 'your account'} · since ${shortDate(c.since)}`}</p>}
          {c.appGroup === 'needs_you' && signInEnded(c) && <p className="text-sm text-muted-foreground">{`Your sign-in${c.account ? ` as ${c.account}` : ''} ended.`}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <MyAppAction c={c} controls={controls} />
            {connected && c.primaryAccountId && (
              <>
                <Button size="sm" variant="outline" onClick={() => controls.another(c)} data-testid="connector-add-account">
                  Add account
                </Button>
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
                <Button size="sm" variant="outline" className="text-destructive-text" onClick={() => controls.disconnect(c)} data-testid="connector-disconnect">
                  Disconnect
                </Button>
              </>
            )}
          </div>
          {connected && (c.personFields ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">{`${c.name} signs in with a key, so another account is added by someone who manages the team’s apps.`}</p>
          )}
          {c.authConfig && <p className="text-xs text-muted-foreground">{`Signed in through ${c.authConfig}.`}</p>}
        </div>
      </AttributeCard>

      <AttributeCard title={connected ? 'What it can do as you' : 'What it can do'} icon={Wrench} testId="connector-tools">
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
        {c.tools.some((t) => t.reviewed) && <p className="mt-2 text-xs text-muted-foreground">Reviewed writes wait for a person’s approval before anything changes.</p>}
      </AttributeCard>

      <AttributeCard title="In chat" icon={MessageSquare}>
        <p className="text-sm">{c.inChat ? 'On by default in your chats' : inChatWords(c)}</p>
        {c.inChat && <p className="text-xs text-muted-foreground">Turn it off for one chat from the apps button in the composer.</p>}
      </AttributeCard>

      <AttributeCard title="Used by" icon={Layers} testId="connector-used-by">
        <p className="flex flex-wrap gap-x-2 text-sm">
          <Link className="underline-offset-4 hover:underline" href="/build/agents">
            {plural(c.used.agents, 'agent')}
          </Link>
          <span aria-hidden>·</span>
          <Link className="underline-offset-4 hover:underline" href="/build/workflows">
            {plural(c.used.workflows, 'workflow')}
          </Link>
          <span aria-hidden>·</span>
          <Link className="underline-offset-4 hover:underline" href="/govern/activity/tool-calls">
            {plural(c.used.callsThisWeek, 'tool call')} this week
          </Link>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">Every call runs as you and is in your Activity.</p>
      </AttributeCard>
    </div>
  );
}
