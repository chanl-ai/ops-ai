'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, Plus, Search } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { plural } from '@/lib/format';
import type { CatalogSystem } from '@/lib/types/integrations';

import { AUTH, SystemMark } from './integration-meta';

/** Systems the bank lets teams connect, as cards grouped by category. Connected ones link to their connection. */
export function CatalogGrid({ items, onConnect }: { items: CatalogSystem[]; onConnect: (item: CatalogSystem) => void }) {
  const [q, setQ] = React.useState('');
  const shown = items.filter((i) => !q || `${i.name} ${i.description} ${i.category} ${i.owner}`.toLowerCase().includes(q.toLowerCase()));
  const groups = [...new Set(shown.map((i) => i.category))];
  return (
    <div className="flex flex-col gap-4">
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. ServiceNow" className="pl-8" aria-label="Search the catalog" />
      </div>
      {!shown.length && (
        <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
          No systems match “{q}”.
          <Button size="sm" variant="outline" onClick={() => setQ('')}>
            Clear search
          </Button>
        </div>
      )}
      {groups.map((g) => (
        <section key={g} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">{g}</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {shown
              .filter((i) => i.category === g)
              .map((i) => (
                <Card key={i.id} className={i.available ? 'flex flex-col' : 'flex flex-col opacity-70'} data-testid={`catalog-${i.id}`}>
                  <CardHeader className="pb-3">
                    <div className="flex items-start gap-2.5">
                      <SystemMark kind={i.kind} />
                      <div className="min-w-0 flex-1">
                        <CardTitle className="truncate text-base">{i.name}</CardTitle>
                        <p className="truncate text-xs text-muted-foreground">
                          {i.authMethods.map((a) => AUTH[a].label).join(' or ')}
                          {i.scopes.length > 0 && ` · ${plural(i.scopes.length, 'scope')}`}
                        </p>
                      </div>
                      {i.connected > 0 ? <Badge variant="secondary">{i.connected === 1 ? 'Connected' : `${i.connected} connected`}</Badge> : !i.available && <Badge variant="outline">Not available</Badge>}
                    </div>
                    <CardDescription className="line-clamp-2 pt-1">{i.available ? i.description : `${i.description} ${i.unavailableReason ?? ''}`}</CardDescription>
                  </CardHeader>
                  <CardContent className="mt-auto flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-muted-foreground">Owner {i.owner}</span>
                    <div className="flex shrink-0 gap-1">
                      {i.connectionId && (
                        <Button size="sm" variant="ghost" asChild>
                          <Link href={`/integrations/${i.connectionId}`}>
                            Open <ArrowRight className="size-3.5" />
                          </Link>
                        </Button>
                      )}
                      <Button size="sm" variant="outline" disabled={!i.available} onClick={() => onConnect(i)}>
                        <Plus className="size-3.5" /> {i.connected ? 'Connect another' : 'Connect'}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}
