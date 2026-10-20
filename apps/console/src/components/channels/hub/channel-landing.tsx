'use client';

import Link from 'next/link';
import { Activity, Check } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Item, ItemContent, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item';
import { plural } from '@/lib/format';
import type { ChannelKindSummary, ChannelType } from '@/lib/types/channels';

import { HEALTH_WORD, kindInfo } from './kinds';

/**
 * The top of a kind's page: what it does, its state, what it includes, and how much happened through it in a week.
 * The activity itself is on the Activity page, which View activity opens filtered to this kind's channels.
 */
export function ChannelLanding({ type, summary, week, sources, action }: { type: ChannelType; summary?: ChannelKindSummary; week: number | null; sources: string[]; action?: React.ReactNode }) {
  const k = kindInfo(type);
  const Icon = k.icon;
  const built = summary?.built ?? false;
  const state = !built ? 'Coming soon' : HEALTH_WORD[summary?.health ?? 'idle'];
  const variant = !built || state === 'Not set up' ? 'outline' : summary?.health === 'warn' || summary?.health === 'error' ? 'destructive' : 'secondary';
  const activityHref = `/activity?${new URLSearchParams([...sources.map((s) => ['source', s] as [string, string]), ['name', k.title]])}`;
  return (
    <Card className="gap-4" data-testid={`channel-landing-${type}`}>
      <CardHeader className="flex flex-row items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted">
          <Icon className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle className="flex flex-wrap items-center gap-2">
            {k.title} <Badge variant={variant}>{state}</Badge>
          </CardTitle>
          <CardDescription>{k.description}</CardDescription>
        </div>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
        <ItemGroup className="gap-1">
          {k.includes.map((line) => (
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
        {built && (
          <Item variant="outline" className="flex-col items-start gap-3" data-testid={`channel-activity-${type}`}>
            <ItemContent>
              <span className="text-2xl font-semibold tabular-nums">{week === null ? '—' : week.toLocaleString('en-CA')}</span>
              <span className="text-sm text-muted-foreground">
                {plural(summary?.total ?? 0, 'connection', 'connections')} · last 7 days
              </span>
            </ItemContent>
            <Button asChild variant="outline" size="sm" disabled={!sources.length}>
              <Link href={activityHref}>
                <Activity className="size-4" /> View activity
              </Link>
            </Button>
          </Item>
        )}
      </CardContent>
    </Card>
  );
}
