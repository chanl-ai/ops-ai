'use client';

import * as React from 'react';
import Link from 'next/link';
import { PanelLeftClose, PanelLeftOpen, SquarePen } from 'lucide-react';

import { SidebarChats } from '@/components/shell/sidebar-chats';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Sidebar, SidebarContent, SidebarHeader } from '@/components/ui/sidebar';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useIsMobile } from '@/hooks/use-mobile';

// Whether the column is folded, kept in this browser only; it starts folded until the person opens it.
const FOLD_KEY = 'ops.chat.list.folded';

function useFolded(): [boolean, (folded: boolean) => void] {
  const [folded, setFolded] = React.useState(true);
  React.useEffect(() => {
    try {
      setFolded(window.localStorage.getItem(FOLD_KEY) !== '0');
    } catch {
      // No storage: the column starts folded.
    }
  }, []);
  const set = React.useCallback((next: boolean) => {
    setFolded(next);
    try {
      window.localStorage.setItem(FOLD_KEY, next ? '1' : '0');
    } catch {
      // Not remembered; the change still applies on this page.
    }
  }, []);
  return [folded, set];
}

function IconAction({ label, children, ...props }: React.ComponentProps<typeof Button> & { label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8" aria-label={label} {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function NewChat({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <IconAction label="New chat" asChild>
      <Link href="/chat" onClick={onNavigate} data-testid="chat-list-new">
        <SquarePen className="size-4" />
      </Link>
    </IconAction>
  );
}

/** The column's own content: a heading with New chat and fold, then the chats with search and paging. */
function ChatList({ onNavigate, fold }: { onNavigate?: () => void; fold?: React.ReactNode }) {
  return (
    <>
      <SidebarHeader className="flex-row items-center gap-1 px-3 py-2">
        <h2 className="flex-1 text-sm font-semibold">Chats</h2>
        <NewChat onNavigate={onNavigate} />
        {fold}
      </SidebarHeader>
      <SidebarContent className="px-1">
        <SidebarChats onNavigate={onNavigate} searchable />
      </SidebarContent>
    </>
  );
}

/**
 * The person's chats beside the open conversation, when the main sidebar lists only a Chat link (area tabs off). A
 * fixed-width column on desktop that folds to a strip of two buttons; on a phone the strip opens the list as a sheet.
 * Built as a non-collapsing `Sidebar` inside the app's one sidebar provider (the registry's nested sidebar pattern), so
 * it has no second keyboard shortcut or stored state of the provider's.
 */
export function ChatListColumn() {
  const isMobile = useIsMobile();
  const [folded, setFolded] = useFolded();
  const [sheetOpen, setSheetOpen] = React.useState(false);

  if (isMobile || folded) {
    return (
      <>
        <nav aria-label="Chats" className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-t py-2" data-testid="chat-list-strip">
          <IconAction label="Show chats" onClick={() => (isMobile ? setSheetOpen(true) : setFolded(false))} data-testid="chat-list-open">
            <PanelLeftOpen className="size-4" />
          </IconAction>
          <NewChat />
        </nav>
        {isMobile && (
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetContent side="left" className="w-72 gap-0 bg-sidebar p-0" data-testid="chat-list-sheet">
              <SheetHeader className="sr-only">
                <SheetTitle>Chats</SheetTitle>
                <SheetDescription>Your chats, with search.</SheetDescription>
              </SheetHeader>
              <ChatList onNavigate={() => setSheetOpen(false)} />
            </SheetContent>
          </Sheet>
        )}
      </>
    );
  }
  return (
    <Sidebar collapsible="none" className="w-64 shrink-0 border-r border-t" aria-label="Chats" data-testid="chat-list-column">
      <ChatList
        fold={
          <IconAction label="Hide chats" onClick={() => setFolded(true)} data-testid="chat-list-fold">
            <PanelLeftClose className="size-4" />
          </IconAction>
        }
      />
    </Sidebar>
  );
}
