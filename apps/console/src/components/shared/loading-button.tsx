'use client';

import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { type VariantProps } from 'class-variance-authority';

type ButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export interface LoadingButtonProps extends ButtonProps {
  /**
   * Loading state - when true, button is disabled and shows spinner
   * Can be from React Query mutation (isPending) or manual loading state
   */
  isLoading?: boolean;
  /**
   * Loading text to show when button is loading
   * Defaults to the button's children text with "..." appended
   */
  loadingText?: string;
  /**
   * Whether to show spinner icon when loading
   * @default true
   */
  showSpinner?: boolean;
}

/**
 * LoadingButton - Reusable button component that handles loading states
 *
 * Features:
 * - Automatically disabled when loading
 * - Shows spinner icon when loading
 * - Prevents double-click submissions
 * - Works with React Query mutations (isPending) or manual loading state
 *
 * @example
 * ```tsx
 * // With React Query mutation
 * const mutation = useCreateAgent();
 * <LoadingButton
 *   type="submit"
 *   isLoading={mutation.isPending}
 * >
 *   Create Agent
 * </LoadingButton>
 *
 * // With manual loading state
 * <LoadingButton
 *   onClick={handleSubmit}
 *   isLoading={isSubmitting}
 *   loadingText="Creating..."
 * >
 *   Submit
 * </LoadingButton>
 * ```
 */
export function LoadingButton({
  isLoading = false,
  loadingText,
  showSpinner = true,
  children,
  disabled,
  className,
  ...props
}: LoadingButtonProps) {
  // Button is disabled when loading OR explicitly disabled
  const isDisabled = isLoading || disabled;

  // Determine loading text
  const displayText = isLoading
    ? loadingText || (typeof children === 'string' ? `${children}...` : children)
    : children;

  return (
    <Button {...props} disabled={isDisabled} className={cn(className)}>
      {isLoading && showSpinner && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
      {displayText}
    </Button>
  );
}
