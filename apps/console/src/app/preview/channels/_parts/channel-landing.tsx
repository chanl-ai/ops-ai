'use client';

import Link from 'next/link';
import { Activity, Check } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Item, ItemContent, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item';
import { plural } from '@/lib/format';

import { CHANNEL_TYPES, ROOT, type ChannelType, type Connection } from '../_sample/data';
import { TYPE_ICON } from './gallery';
import { kindHealth } from './layout';

const STATE: Record<ReturnType<typeof kindHealth>, { label: string; variant: 'secondary' | 'destructive' | 'outline' }> = {
  ok: { label: 'Active', variant: 'secondary' },
  warn: { label: 'Needs attention', variant: 'destructive' },
  error: { label: 'Failing', variant: 'destructive' },
  idle: { label: 'Not set up', variant: 'outline' },
};

/**
 * The top of a channel kind's page: what it does, its state, what it includes, and how much happened through it. The
 * activity itself lives on the one Activity page; this card carries the count and a link that opens it filtered.
 */
export function ChannelLanding({ type, connections, action }: { type: ChannelType; connections: Connection[]; action?: React.ReactNode }) {
  const info = CHANNEL_TYPES.find((t) => t.type === type)!;
  const Icon = TYPE_ICON[type];
  const rows = connections.filter((c) => c.type === type);
  const state = info.built ? STATE[kindHealth(type, connections)] : { label: 'Coming soon', variant: 'outline' as const };
  const week = rows.reduce((n, c) => n + c.activity7d, 0);
  return (
    <Card className="gap-4" data-testid={`channel-landing-${type}`}>
      <CardHeader className="flex flex-row items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
          <Icon className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle className="flex flex-wrap items-center gap-2">
            {info.title} <Badge variant={state.variant}>{state.label}</Badge>
          </CardTitle>
          <CardDescription>{info.description}</CardDescription>
        </div>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
        <ItemGroup className="gap-1">
          {info.includes.map((line) => (
            <Item key={line} size="sm" className="px-0 py-1">
              <ItemMedia>
                <Check className="size-4 text-success-text" />
              </ItemMedia>
              <ItemContent>
                <ItemTitle className="font-normal">{line}</ItemTitle>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
        {info.built && (
          <Item variant="outline" className="flex-col items-start gap-3" data-testid={`channel-activity-${type}`}>
            <ItemContent>
              <span className="text-2xl font-semibold tabular-nums">{week.toLocaleString('en-CA')}</span>
              <span className="text-sm text-muted-foreground">{plural(rows.length, 'connection', 'connections')} · last 7 days</span>
            </ItemContent>
            <Button asChild variant="outline" size="sm">
              <Link href={`${ROOT}/activity?channel=${type}`}>
                <Activity className="size-4" /> View activity
              </Link>
            </Button>
          </Item>
        )}
      </CardContent>
    </Card>
  );
}
