'use client';

import * as React from 'react';

import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';

/**
 * Full-height chat shell: the conversation rail on the left, the open conversation on the right. Below 1024px
 * the rail moves into a sheet the conversation header opens. Chat pages use this instead of PageLayout because
 * the message list and composer must fill the viewport and scroll on their own.
 */
export function ChatLayout({ rail, railOpen, onRailOpenChange, children }: { rail: React.ReactNode; railOpen: boolean; onRailOpenChange: (open: boolean) => void; children: React.ReactNode }) {
  return (
    <div className="flex h-[calc(100svh-1rem-var(--header-height))] min-h-[480px] overflow-hidden border-t">
      <aside className="hidden w-[272px] shrink-0 overflow-hidden border-r lg:flex">{rail}</aside>
      <Sheet open={railOpen} onOpenChange={onRailOpenChange}>
        <SheetContent side="left" className="flex w-full flex-col gap-0 p-0 sm:max-w-[300px]">
          <SheetHeader className="border-b">
            <SheetTitle>Chats</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1">{rail}</div>
        </SheetContent>
      </Sheet>
      <section className="flex min-w-0 flex-1 flex-col">{children}</section>
    </div>
  );
}
