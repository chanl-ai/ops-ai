'use client';

import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { toast } from 'sonner';
import { formatShortId } from '@/lib/utils/id-utils';

interface ShortIdCellProps {
  /** The full ID to display and copy */
  id: string;
  /** Optional CSS class for styling the container */
  className?: string;
}

/**
 * ShortIdCell Component
 *
 * Displays a shortened ID (last 6 characters with # prefix) with:
 * - Click-to-copy functionality for the full ID
 * - Tooltip showing the full ID on hover
 * - Visual feedback (checkmark) after successful copy
 * - Toast notification on copy
 *
 * @example
 * <ShortIdCell id="507f1f77bcf86cd799439011" />
 * // Displays:"#439011" with copy button
 */
export function ShortIdCell({ id, className }: ShortIdCellProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      toast.success('ID copied to clipboard');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      toast.error('Failed to copy ID');
      console.error('Copy failed:', error);
    }
  };

  if (!id) {
    return <span className="text-muted-foreground">-</span>;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={`flex items-center gap-1 ${className || ''}`}>
            <span className="font-mono text-xs">{formatShortId(id)}</span>
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={handleCopy}
              aria-label="Copy full ID"
            >
              {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p className="font-mono text-xs">{id}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
