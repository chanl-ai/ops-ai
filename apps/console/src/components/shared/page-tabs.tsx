'use client';

import * as React from 'react';

import { Tabs, TabsContent } from '@/components/ui/tabs';

/**
 * Tabs that switch a page's body on the same route, with the strip in PageLayout's `tabs` slot. The root wraps the
 * whole PageLayout so the strip and the body share one tabs context: the selected tab then controls a panel that
 * exists, which a strip on its own (its panel never rendered) does not. For tabs that are routes, use RouteTabs.
 */
export function PageTabs({ value, onValueChange, children }: { value: string; onValueChange: (value: string) => void; children: React.ReactNode }) {
  return (
    <Tabs value={value} onValueChange={onValueChange} className="contents">
      {children}
    </Tabs>
  );
}

/** The page body for the selected tab. Not a tab stop of its own: the controls inside it are. */
export function PageTabPanel({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsContent value={value} tabIndex={-1} className="p-0">
      {children}
    </TabsContent>
  );
}
