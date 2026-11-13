'use client';

import * as React from 'react';
import { Info } from 'lucide-react';

import { CodeBlock } from '@/components/deployments/deployment-meta';
import { CopyButton } from '@/components/shared/copy-button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { plural } from '@/lib/format';
import type { McpLink } from '@/lib/types/mcp-links';
import { cn } from '@/lib/utils';

import { CONNECT_CLIENTS } from './clients';

/**
 * How a person connects their assistant to one link: its address with Copy, what it offers, a tile per assistant and
 * the exact steps for the one picked. Everyone sees it, so a member learns how to connect without managing anything.
 */
export function ConnectTab({ link }: { link: McpLink }) {
  const [picked, setPicked] = React.useState(CONNECT_CLIENTS[0]!.id);
  const client = CONNECT_CLIENTS.find((c) => c.id === picked) ?? CONNECT_CLIENTS[0]!;
  const url = link.url;
  return (
    <Card className="gap-4" data-testid="mcp-connect">
      <CardHeader>
        <CardTitle className="text-base font-medium">How assistants connect</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {url ? (
          <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border bg-muted/30 p-2 pl-3">
            <code className="min-w-0 flex-1 break-all font-mono text-sm" data-testid="mcp-link-url">
              {url}
            </code>
            <CopyButton text={url} variant="outline" size="sm" />
          </div>
        ) : (
          <Alert data-testid="mcp-link-no-url">
            <Info />
            <AlertTitle>This install names no public address for its MCP service</AlertTitle>
            <AlertDescription>An administrator sets OPS_TOOLS_PUBLIC_URL; until then assistants cannot reach this link.</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary" className="font-normal">
            {plural(link.toolCount, 'tool')}
          </Badge>
          <Badge variant="secondary" className="font-normal">
            Sign-in: your own account
          </Badge>
          <Badge variant="outline" className="font-normal">
            Test data
          </Badge>
          {link.paused && (
            <Badge variant="outline" className="border-warning/40 font-normal text-warning-text">
              Paused
            </Badge>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" role="radiogroup" aria-label="Assistant" data-testid="mcp-clients">
          {CONNECT_CLIENTS.map((c) => (
            <button
              key={c.id}
              type="button"
              role="radio"
              aria-checked={c.id === client.id}
              onClick={() => setPicked(c.id)}
              className={cn(
                'flex min-w-0 items-center gap-2.5 rounded-lg border bg-card p-2.5 text-left text-sm transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                c.id === client.id && 'border-foreground ring-1 ring-foreground',
              )}
              data-testid={`mcp-client-${c.id}`}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-muted text-xs font-semibold">{c.initials}</span>
              <span className="min-w-0 truncate font-medium">{c.name}</span>
            </button>
          ))}
        </div>
        <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm" data-testid="mcp-client-steps">
          {client.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        {url && client.kind !== 'url' && <CodeBlock label={client.kind === 'json' ? (client.file ?? 'Config') : 'Command'} code={client.snippet(url, link.slug)} />}
      </CardContent>
    </Card>
  );
}
