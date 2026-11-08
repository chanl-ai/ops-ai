'use client';

import * as React from 'react';
import Link from 'next/link';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { initials } from '@/lib/format';

/** How Connectors lays its cards out: one column on a phone, two and then three as the page widens. */
export const APP_CARD_GRID = 'grid grid-cols-1 gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3';

/**
 * One app as a card, for Connectors' two views: logo, name and a line under it, then the card's own lines, and at the
 * foot its state and at most one action. The whole card opens `href`, or calls `onOpen`; the action sits above that.
 */
export function AppCard({
  testId,
  state,
  name,
  logo,
  subtitle,
  href,
  onOpen,
  linkTestId,
  footState,
  action,
  children,
}: {
  testId: string;
  /** The card's state, kept on it for a test or a style to read. */
  state?: string;
  name: string;
  logo?: string | null;
  subtitle?: React.ReactNode;
  href?: string;
  onOpen?: () => void;
  linkTestId?: string;
  footState: React.ReactNode;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  // Stretched over the card, so the whole card opens the app.
  const stretch = 'after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none';
  return (
    <Card className="relative h-full min-h-40 gap-3 transition-all hover:border-primary/40 hover:shadow-md" data-testid={testId} data-state={state}>
      <CardHeader className="flex flex-row items-center gap-2.5 px-4">
        <Avatar className="size-9 rounded-md">
          {logo && <AvatarImage src={logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <CardTitle className="truncate text-base">
            {href ? (
              <Link href={href} className={stretch} data-testid={linkTestId}>
                {name}
              </Link>
            ) : (
              <button type="button" onClick={onOpen} className={`text-left ${stretch}`} data-testid={linkTestId}>
                {name}
              </button>
            )}
          </CardTitle>
          {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 px-4">
        {children}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2">
          {footState}
          {action && <span className="relative z-10">{action}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
