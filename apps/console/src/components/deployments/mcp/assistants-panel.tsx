'use client';

import Link from 'next/link';
import { Bot } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, relativeTime } from '@/lib/format';
import type { ConnectedAssistant, IdentityAssurance } from '@/lib/types/connect';
import { cn } from '@/lib/utils';

const ASSURANCE: Record<IdentityAssurance, { label: string; hint: string; cls: string }> = {
  attested: { label: 'Attested', hint: 'Signed in through the workspace IdP', cls: 'border-success/40 text-success-text' },
  claimed: { label: 'Claimed', hint: 'Identity sent by the client, not proven by the IdP', cls: 'border-warning/40 text-warning-text' },
};

/** Who has connected, from which client, and how sure the platform is of who they are. */
export function AssistantsPanel({ assistants, total }: { assistants: ConnectedAssistant[]; total: number }) {
  return (
    <Card className="gap-3" data-testid="connect-assistants">
      <CardHeader>
        <CardTitle>Connected assistants</CardTitle>
        <CardDescription>{total ? `${total} connected` : 'Nobody has connected yet'}</CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {assistants.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Client</TableHead>
                <TableHead>Person</TableHead>
                <TableHead>Identity</TableHead>
                <TableHead className="text-right">Calls</TableHead>
                <TableHead className="pr-6 text-right">Last call</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assistants.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="pl-6 font-medium">{a.client}</TableCell>
                  <TableCell>
                    <div>{a.person}</div>
                    <div className="text-xs text-muted-foreground">{a.team}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={cn('font-normal', ASSURANCE[a.assurance].cls)} title={ASSURANCE[a.assurance].hint}>
                      {ASSURANCE[a.assurance].label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{count(a.calls)}</TableCell>
                  <TableCell className="pr-6 text-right text-sm whitespace-nowrap text-muted-foreground">{relativeTime(a.lastCallAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState icon={Bot} title="No assistants yet" description="Install the URL in a client above. The first person to connect appears here." />
        )}
      </CardContent>
      <CardFooter className="justify-between gap-2 text-sm">
        <Link href="/access" className="underline underline-offset-2">
          Who may run what →
        </Link>
        <Link href="/logs/tool-calls" className="text-muted-foreground underline underline-offset-2">
          Tool calls →
        </Link>
      </CardFooter>
    </Card>
  );
}
