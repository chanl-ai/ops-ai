'use client';

import Link from 'next/link';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { plural } from '@/lib/format';
import type { ConnectOverview } from '@/lib/types/connect';

const config = {
  calls: { label: 'Calls', color: 'var(--chart-1)' },
  held: { label: 'Held for approval', color: 'var(--chart-4)' },
} satisfies ChartConfig;

/** Calls over MCP per day for the selected range; held and failed counts link to where they are handled. */
export function CallsPanel({ series, held, failed, rangeLabel }: { series: ConnectOverview['series']; held: number; failed: number; rangeLabel: string }) {
  return (
    <Card className="gap-3" data-testid="connect-calls">
      <CardHeader>
        <CardTitle>Calls over MCP</CardTitle>
        <CardDescription>{rangeLabel}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-auto h-56 w-full">
          <AreaChart data={series} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} tickFormatter={(d: string) => d.slice(5)} />
            <YAxis tickLine={false} axisLine={false} width={40} fontSize={11} allowDecimals={false} />
            <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
            <Area dataKey="calls" type="monotone" fill="var(--color-calls)" fillOpacity={0.25} stroke="var(--color-calls)" />
            <Area dataKey="held" type="monotone" fill="var(--color-held)" fillOpacity={0.35} stroke="var(--color-held)" />
          </AreaChart>
        </ChartContainer>
      </CardContent>
      <CardFooter className="gap-1 text-sm text-muted-foreground">
        <Link href="/reviews" className="underline underline-offset-2">
          {plural(held, 'call')} held for approval
        </Link>
        <span>·</span>
        <Link href="/logs/tool-calls" className="underline underline-offset-2">
          {failed} failed
        </Link>
      </CardFooter>
    </Card>
  );
}
