'use client';

import * as React from 'react';

import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';

/** A tab list that scrolls sideways instead of spilling its labels; use inside `Tabs`. */
export function ScrollTabsList({
  tabs,
  testId,
  triggerTestId,
}: {
  tabs: { value: string; label: React.ReactNode }[];
  testId?: string;
  triggerTestId?: (value: string) => string;
}) {
  return (
    <ScrollArea className="w-full min-w-0 pb-2" data-testid={testId}>
      <TabsList className="w-max">
        {tabs.map((t) => (
          <TabsTrigger key={t.value} value={t.value} data-testid={triggerTestId?.(t.value)}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
}
