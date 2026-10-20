'use client';

import * as React from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

export interface DialogScrollAreaProps extends React.ComponentProps<typeof ScrollArea> {
  /**
   * Maximum height of the dialog (default: 85vh)
   * Used to calculate the scroll area height
   */
  dialogMaxHeight?: string;
  /**
   * Space reserved for header, filters, footer, and padding (default: 280px)
   * Adjust if your dialog has different spacing needs
   */
  reservedSpace?: number;
}

/**
 * DialogScrollArea is a ScrollArea component optimized for use in dialogs.
 *
 * Automatically calculates height based on dialog max-height, accounting for
 * header, filters, footer, and padding to ensure proper scrolling behavior.
 *
 * @example
 * ```tsx
 * <DialogContent size="xl" className="max-h-[85vh]">
 *   <DialogHeader>...</DialogHeader>
 *   <DialogScrollArea>
 *     <div>Scrollable content</div>
 *   </DialogScrollArea>
 *   <DialogFooter>...</DialogFooter>
 * </DialogContent>
 * ```
 */
export function DialogScrollArea({
  className,
  dialogMaxHeight = '85vh',
  reservedSpace = 280,
  ...props
}: DialogScrollAreaProps) {
  // Extract numeric value from dialogMaxHeight (e.g., "85vh" -> 85)
  const maxHeightValue = parseInt(dialogMaxHeight.replace(/[^0-9]/g, ''), 10);

  // Calculate height: dialogMaxHeight - reservedSpace
  const height = `calc(${maxHeightValue}vh - ${reservedSpace}px)`;

  return (
    <ScrollArea className={cn('-mx-4', className)} style={{ height, ...props.style }} {...props}>
      {props.children}
    </ScrollArea>
  );
}
