'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, Plus, Search } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { plural } from '@/lib/format';
import type { CatalogItem } from '@/lib/types/tool-modules';

import { ApprovalStateBadge, CREDENTIAL_KIND, MODULE_TYPE, ModuleMark } from './module-meta';

/** The bank's catalogue of known systems as cards, grouped by category. Connected ones open their module. */
export function CatalogGrid({ items, onAdd }: { items: CatalogItem[]; onAdd: (item: CatalogItem) => void }) {
  const [q, setQ] = React.useState('');
  const shown = items.filter((i) => !q || `${i.name} ${i.description} ${i.category} ${i.owner}`.toLowerCase().includes(q.toLowerCase()));
  const groups = [...new Set(shown.map((i) => i.category))];
  return (
    <div className="flex flex-col gap-4">
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. ServiceNow" className="pl-8" aria-label="Search the catalog" />
      </div>
      {!shown.length && <p className="py-10 text-center text-sm text-muted-foreground">No systems match “{q}”.</p>}
      {groups.map((g) => (
        <section key={g} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">{g}</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {shown
              .filter((i) => i.category === g)
              .map((i) => (
                <Card key={i.id} className={i.available ? 'flex flex-col' : 'flex flex-col opacity-70'}>
                  <CardHeader className="pb-3">
                    <div className="flex items-start gap-2.5">
                      <ModuleMark name={i.name} />
                      <div className="min-w-0 flex-1">
                        <CardTitle className="truncate text-base">{i.name}</CardTitle>
                        <p className="text-xs text-muted-foreground">
                          {i.operations ? plural(i.operations, 'operation') : 'Operations not listed'} · {CREDENTIAL_KIND[i.auth]}
                        </p>
                      </div>
                      {i.moduleId && i.moduleState ? i.moduleState === 'approved' ? <Badge variant="secondary">Connected</Badge> : <ApprovalStateBadge state={i.moduleState} /> : !i.available && <Badge variant="outline">Not available</Badge>}
                    </div>
                    <CardDescription className="line-clamp-2 pt-1">{i.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="mt-auto flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">
                      {MODULE_TYPE[i.type].label} · {i.owner}
                    </span>
                    {i.moduleId ? (
                      <Button size="sm" variant="ghost" asChild>
                        <Link href={`/tools/${i.moduleId}`}>
                          Open <ArrowRight className="size-3.5" />
                        </Link>
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" disabled={!i.available} onClick={() => onAdd(i)}>
                        <Plus className="size-3.5" /> Add
                      </Button>
                    )}
                  </CardContent>
                </Card>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}
