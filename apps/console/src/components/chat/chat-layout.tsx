'use client';

import * as React from 'react';

/**
 * Full-height chat shell: the open conversation fills the space beside the app sidebar, whose Chats group lists the
 * person's chats (c-552). Chat pages use this instead of PageLayout because the message list and composer must fill
 * the viewport and scroll on their own.
 */
export function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[calc(100svh-1rem-var(--header-height))] min-h-[480px] overflow-hidden border-t">
      <section className="flex min-w-0 flex-1 flex-col" data-middle-column>
        {children}
      </section>
    </div>
  );
}
