'use client';

import * as React from 'react';

import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';

/** A tab list that scrolls sideways instead of spilling its labels; use inside `Tabs`. */
export function ScrollTabsList({ tabs }: { tabs: { value: string; label: React.ReactNode }[] }) {
  return (
    <ScrollArea className="w-full">
      <TabsList className="w-max">
        {tabs.map((t) => (
          <TabsTrigger key={t.value} value={t.value}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
}
