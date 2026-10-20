'use client';

import * as React from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { CheckIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        // Unchecked border is `muted-foreground/60`, not `border-input`.
        // `--input` is oklch(0.7621) in light mode, ~2:1 against the page
        // background — under the 3:1 WCAG minimum for UI component boundaries
        // (SC 1.4.11). A 16px square whose entire affordance IS its border
        // cannot afford that; a text input has its own size and label to carry
        // the meaning, so `--input` stays correct there.
        'peer border-muted-foreground/60 dark:bg-input/30 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground dark:data-[state=checked]:bg-primary data-[state=checked]:border-primary focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive size-4 shrink-0 rounded-[4px] border shadow-xs transition-shadow outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="flex items-center justify-center text-current transition-none"
      >
        {/*
          The colour is on the ICON, not inherited. Ancestors can carry
          `[&_svg:not([class*='text-'])]:text-muted-foreground` — cmdk's
          CommandItem does — which silently repaints an unclassed icon grey,
          producing a grey tick on the filled primary box. Naming a `text-`
          class opts out of any such rule. The indicator only renders when
          checked, so primary-foreground is always the right colour here.
        */}
        <CheckIcon className="size-3.5 text-primary-foreground" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
