'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ChevronLeft, ChevronRight } from 'lucide-react';

// ── Kbd ──────────────────────────────────────────────────────────────────────

/** Small keyboard shortcut badge, styled for tooltip backgrounds. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center rounded border border-primary-foreground/30 bg-primary-foreground/10 px-1.5 py-0.5 text-[10px] font-mono leading-none min-w-[1.25rem]">
      {children}
    </kbd>
  );
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface DetailSheetNavigation {
  onPrev?: () => void;
  onNext?: () => void;
  currentIndex: number;
  totalCount: number;
}

export interface DetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;

  /** Title line */
  title: ReactNode;
  /** Subtitle line below title (e.g., timestamp) */
  description?: ReactNode;
  /** Tags/badges rendered below title + description */
  tags?: ReactNode;

  /** Prev/next navigation — enables keyboard shortcuts (j/k, arrows) */
  navigation?: DetailSheetNavigation;

  /** Extra actions rendered in the footer before the nav (left side) */
  footerActions?: ReactNode;

  /** Width class override (default: sm:max-w-2xl) */
  widthClass?: string;

  /** Scrollable body content */
  children: ReactNode;

  /** data-testid on the SheetContent */
  testId?: string;
  /** Changing this scrolls the body back to the top (e.g. the record id when stepping prev/next). */
  scrollKey?: string | number;
}

// ── Component ────────────────────────────────────────────────────────────────

export function DetailSheet({
  open,
  onOpenChange,
  title,
  description,
  tags,
  navigation,
  footerActions,
  widthClass = 'sm:max-w-2xl',
  children,
  testId,
  scrollKey,
}: DetailSheetProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [scrollKey]);
  // ── Keyboard shortcuts (j/k, arrows) ──
  useEffect(() => {
    if (!open || !navigation) return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      ) {
        return;
      }
      // A dialog opened on top of the sheet owns the keyboard; stepping records under it would change what it acts on.
      if (document.querySelectorAll('[role="dialog"][data-state="open"]').length > 1) return;
      if (e.key === 'j' || e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        navigation.onNext?.();
      } else if (e.key === 'k' || e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        navigation.onPrev?.();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, navigation]);

  const hasPrev = !!navigation?.onPrev;
  const hasNext = !!navigation?.onNext;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className={`w-full ${widthClass} p-0 flex flex-col h-full bg-background`}
        onOpenAutoFocus={(e) => e.preventDefault()}
        data-testid={testId}
      >
        {/* ── Sticky Header ── */}
        <SheetHeader className="px-6 py-4 border-b bg-background shrink-0 pr-12">
          <SheetTitle className="text-left" data-testid="detail-sheet-title">
            {title}
          </SheetTitle>
          {description && (
            <SheetDescription className="text-left text-xs">{description}</SheetDescription>
          )}
          {tags && <div className="flex items-center gap-2 flex-wrap pt-1">{tags}</div>}
        </SheetHeader>

        {/* ── Scrollable Body ── */}
        <div ref={bodyRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-4">{children}</div>

        {/* ── Sticky Footer ── */}
        <SheetFooter className="px-6 py-3 border-t bg-background shrink-0 flex-row items-center justify-between">
          <div className="flex items-center gap-2">{footerActions}</div>

          {navigation && (
            <div className="flex items-center gap-1" data-testid="detail-sheet-nav">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8"
                    onClick={navigation.onPrev}
                    disabled={!hasPrev}
                    data-testid="detail-sheet-prev"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    <span className="sr-only">Previous</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <span className="flex items-center gap-1.5">
                    Previous
                    <Kbd>K</Kbd>
                    <Kbd>↑</Kbd>
                  </span>
                </TooltipContent>
              </Tooltip>

              <span className="text-xs text-muted-foreground tabular-nums px-1 min-w-[3.5rem] text-center">
                {navigation.currentIndex + 1} of {navigation.totalCount}
              </span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8"
                    onClick={navigation.onNext}
                    disabled={!hasNext}
                    data-testid="detail-sheet-next"
                  >
                    <ChevronRight className="h-4 w-4" />
                    <span className="sr-only">Next</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <span className="flex items-center gap-1.5">
                    Next
                    <Kbd>J</Kbd>
                    <Kbd>↓</Kbd>
                  </span>
                </TooltipContent>
              </Tooltip>
            </div>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
