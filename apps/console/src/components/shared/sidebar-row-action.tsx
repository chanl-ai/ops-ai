'use client';

import * as React from 'react';

import { SidebarMenuAction } from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';

/**
 * A sidebar row's own button (a section's show/hide chevron, a chat's menu) at 32×32, the full height of a default row
 * and the width the row already leaves free for it (`pr-8`). The primitive's 20px square is under WCAG 2.2's 24px
 * target minimum, and its larger hit area exists on phones only.
 */
export function SidebarRowAction({ className, ...props }: React.ComponentProps<typeof SidebarMenuAction>) {
  return (
    <SidebarMenuAction
      className={cn(
        'right-0 w-8 top-0 peer-data-[size=sm]/menu-button:top-0 peer-data-[size=default]/menu-button:top-0 peer-data-[size=lg]/menu-button:top-2',
        className
      )}
      {...props}
    />
  );
}
