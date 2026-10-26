'use client';

import * as React from 'react';

import { MessagesSquare } from 'lucide-react';

import { useSidebarFoldsWhenNarrow } from '@/components/shared/collapsed-sidebar';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';

const DOCKED_KEY = 'ops.chat.rail-docked';

const RailContext = React.createContext<{ docked: boolean; toggle: () => void } | null>(null);

/**
 * Shows or hides the conversation rail: at 1024px and wider it docks or undocks the rail beside the conversation,
 * below that it opens the rail's sheet. Rendered in the conversation header.
 */
export function ChatRailButton() {
  const rail = React.useContext(RailContext);
  if (!rail) return null;
  return (
    <Button variant="outline" size="sm" onClick={rail.toggle} aria-pressed={rail.docked} aria-label={rail.docked ? 'Hide chats' : 'Show chats'} data-testid="chat-rail-toggle">
      <MessagesSquare className="size-4" /> <span className="sr-only sm:not-sr-only">Chats</span>
    </Button>
  );
}

/**
 * Full-height chat shell: the conversation rail on the left, the open conversation on the right. The conversation
 * keeps priority: below 1440px the app sidebar folds to icons, the rail can be hidden at any width (remembered in this
 * browser), and below 1024px it moves into a sheet the conversation header opens. Chat pages use this instead of PageLayout because
 * the message list and composer must fill the viewport and scroll on their own.
 */
export function ChatLayout({ rail, railOpen, onRailOpenChange, children }: { rail: React.ReactNode; railOpen: boolean; onRailOpenChange: (open: boolean) => void; children: React.ReactNode }) {
  useSidebarFoldsWhenNarrow();
  const [docked, setDocked] = React.useState(true);
  React.useEffect(() => {
    try {
      setDocked(window.localStorage.getItem(DOCKED_KEY) !== 'false');
    } catch {
      // No storage: the rail starts docked.
    }
  }, []);
  const rails = React.useMemo(
    () => ({
      docked,
      toggle: () => {
        if (!window.matchMedia('(min-width: 1024px)').matches) return onRailOpenChange(true);
        setDocked((d) => {
          try {
            window.localStorage.setItem(DOCKED_KEY, String(!d));
          } catch {
            // No storage: the choice lasts for this page only.
          }
          return !d;
        });
      },
    }),
    [docked, onRailOpenChange],
  );
  return (
    <RailContext.Provider value={rails}>
    <div className="flex h-[calc(100svh-1rem-var(--header-height))] min-h-[480px] overflow-hidden border-t">
      <aside className={docked ? 'hidden w-[272px] shrink-0 overflow-hidden border-r lg:flex' : 'hidden'} data-testid="chat-rail">{rail}</aside>
      <Sheet open={railOpen} onOpenChange={onRailOpenChange}>
        <SheetContent side="left" className="flex w-full flex-col gap-0 p-0 sm:max-w-xs">
          <SheetHeader className="border-b">
            <SheetTitle>Chats</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1">{rail}</div>
        </SheetContent>
      </Sheet>
      <section className="flex min-w-0 flex-1 flex-col" data-middle-column>{children}</section>
    </div>
    </RailContext.Provider>
  );
}
