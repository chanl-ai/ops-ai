'use client';

import type { ReactNode } from 'react';
import { Radio } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { RouteTabs } from '@/components/shared/route-tabs';
import { Note } from '@/components/shared/setting/note';
import { StatusDot, type Health } from '@/components/shared/setting/status-dot';
import { cn } from '@/lib/utils';

import { CHANNEL_TYPES, ROOT, type ChannelType, type Connection, type ConnectionStatus } from '../_sample/data';
import { useConnections } from '../_sample/store';

const DOT: Record<Health, string> = { ok: 'bg-success-text', warn: 'bg-warning-text', error: 'bg-destructive', idle: 'bg-muted-foreground/40' };
const DOT_WORD: Record<Health, string> = { ok: 'receiving', warn: 'needs attention', error: 'failing', idle: 'not set up' };

/** A channel kind's health from its connections: any stuck one wins, then any connected one, else not set up. */
export function kindHealth(type: ChannelType, connections: Connection[]): Health {
  const rows = connections.filter((c) => c.type === type);
  if (rows.some((c) => c.status === 'attention')) return 'warn';
  if (rows.some((c) => c.status === 'connected')) return 'ok';
  return 'idle';
}

/** One tab per channel kind, each with a dot for receiving, needs attention or not set up; kinds coming soon say so. */
function ChannelTabs() {
  const connections = useConnections();
  const tabs = [
    { href: ROOT, label: 'Overview' },
    ...CHANNEL_TYPES.map((t) => {
      const health = kindHealth(t.type, connections);
      return {
        href: t.href,
        label: (
          <span className="inline-flex items-center gap-1.5" data-testid={`channel-tab-${t.type}`} data-health={t.built ? health : 'soon'}>
            {t.built ? <span aria-hidden="true" className={cn('size-1.5 rounded-full', DOT[health])} /> : null}
            {t.title}
            <span className="sr-only">{t.built ? `, ${DOT_WORD[health]}` : ', coming soon'}</span>
          </span>
        ),
      };
    }),
  ];
  return <RouteTabs tabs={tabs} />;
}

/** Header, channel tabs and the design-mock note for every /preview/channels page. Page actions go in `actions`, never mid-page. */
export function ChannelsPageLayout({ title, description, actions, back = false, tabs = true, children }: { title: string; description: string; actions?: ReactNode; back?: string | false; tabs?: boolean; children: ReactNode }) {
  return (
    <PageLayout icon={Radio} title={title} description={description} actions={actions} backHref={back || undefined} tabs={tabs ? <ChannelTabs /> : undefined}>
      <div className="flex flex-col gap-6 pb-16">
        <Note tone="sample" title="Design mock">
          Sample data. Connecting, testing and saving change this page only; nothing is stored.
        </Note>
        {children}
      </div>
    </PageLayout>
  );
}

const HEALTH: Record<ConnectionStatus, { health: Health; label: string }> = {
  connected: { health: 'ok', label: 'Connected' },
  attention: { health: 'warn', label: 'Needs attention' },
  paused: { health: 'idle', label: 'Paused' },
};

/** A connection's status as a dot and a word; the hover card says when it last did something, and why if it is stuck. */
export function ConnectionStatusDot({ status, at, problem }: { status: ConnectionStatus; at?: string; problem?: string }) {
  return <StatusDot status={HEALTH[status].health} label={HEALTH[status].label} at={at} detail={problem} />;
}
