'use client';

import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { plural } from '@/lib/format';
import type { ChannelKindSummary } from '@/lib/types/channels';

import { KINDS } from './kinds';

/** One card per kind, with a state read from its channels (never a bare count) and exactly one action. */
export function ChannelGallery({ kinds }: { kinds: ChannelKindSummary[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="channel-gallery">
      {KINDS.map((k) => {
        const s = kinds.find((x) => x.type === k.type);
        const built = s?.built ?? false;
        const Icon = k.icon;
        return (
          <Card key={k.type} className="gap-3" data-testid={`gallery-${k.type}`}>
            <CardHeader className="flex flex-row items-center gap-3 px-4 pt-4">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <Icon className="size-4 text-muted-foreground" />
              </span>
              <CardTitle className="min-w-0 flex-1 truncate text-sm">{k.title}</CardTitle>
              {!built ? (
                <Badge variant="outline">Coming soon</Badge>
              ) : s && s.attention > 0 ? (
                <Badge variant="destructive">{plural(s.attention, 'needs attention', 'need attention')}</Badge>
              ) : s && s.active > 0 ? (
                <Badge variant="secondary">Active · {s.active}</Badge>
              ) : (
                <Badge variant="outline">Not set up</Badge>
              )}
            </CardHeader>
            <CardContent className="px-4 pb-0">
              <CardDescription className="line-clamp-2 min-h-10 text-xs">{k.description}</CardDescription>
            </CardContent>
            <CardFooter className="mt-auto justify-end border-t px-4 pb-4 [.border-t]:pt-3">
              <Button asChild size="sm" variant={built && !s?.total ? 'default' : 'outline'} data-testid={`gallery-action-${k.type}`}>
                <Link href={k.href}>{!built ? 'Preview' : s?.total ? 'Manage' : 'Connect'}</Link>
              </Button>
            </CardFooter>
          </Card>
        );
      })}
    </div>
  );
}
