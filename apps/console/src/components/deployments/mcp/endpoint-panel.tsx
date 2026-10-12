'use client';

import * as React from 'react';
import Link from 'next/link';

import { CodeBlock } from '@/components/deployments/deployment-meta';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';

import { type ConnectClient, CONNECT_CLIENTS } from './clients';

const SNIPPET_LABEL: Record<ConnectClient['kind'], string> = { json: 'Config', command: 'Command', url: 'MCP URL', link: 'MCP URL' };

/** The URL, what clients see once connected, and the install tiles. Each tile opens the exact snippet for that client. */
export function EndpointPanel({ url, authLabel, exposedCount, live, onCopied }: { url: string; authLabel: string; exposedCount: number; live: boolean; onCopied: () => void }) {
  const [client, setClient] = React.useState<ConnectClient | null>(null);
  return (
    <Card className="gap-4" data-testid="connect-endpoint">
      <CardHeader>
        <CardTitle>How assistants connect</CardTitle>
        <CardDescription>Each person signs in with their own Northfield account, so an assistant can run only what that person may run.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 p-2 pl-3">
          <code className="min-w-0 flex-1 truncate font-mono text-sm" data-testid="connect-url">
            {url}
          </code>
          <CopyButton text={url} variant="outline" size="sm" onCopy={onCopied} />
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary" className="font-normal">
            {plural(exposedCount, 'workflow')} exposed
          </Badge>
          <Badge variant="secondary" className="font-normal">
            Auth · {authLabel}
          </Badge>
          <Badge variant="outline" className={cn('font-normal', live ? 'border-success/40 text-success-text' : 'text-muted-foreground')} data-testid="connect-live">
            {live ? 'Live' : 'Waiting for first call'}
          </Badge>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" data-testid="connect-clients">
          {CONNECT_CLIENTS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setClient(c)}
              className="flex items-center gap-2.5 rounded-lg border bg-card p-2.5 text-left text-sm transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              data-testid={`client-${c.id}`}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-muted text-xs font-semibold">{c.initials}</span>
              <span className="min-w-0 truncate font-medium">{c.name}</span>
            </button>
          ))}
        </div>
      </CardContent>
      <DialogShell
        open={!!client}
        onOpenChange={(o) => !o && setClient(null)}
        size="md"
        title={client ? `Connect ${client.name}` : ''}
        description="Signs in with your Northfield account. No key to paste."
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <Link href="/deployments" className="text-xs text-muted-foreground underline underline-offset-2">
              Advanced: API deployments
            </Link>
            <Button variant="outline" onClick={() => setClient(null)}>
              Done
            </Button>
          </div>
        }
      >
        {client && (
          <div className="flex flex-col gap-4" data-testid="client-dialog">
            <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm">
              {client.steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <CodeBlock label={client.file ? `${SNIPPET_LABEL[client.kind]} · ${client.file}` : SNIPPET_LABEL[client.kind]} code={client.snippet(url)} onCopy={onCopied} />
          </div>
        )}
      </DialogShell>
    </Card>
  );
}
