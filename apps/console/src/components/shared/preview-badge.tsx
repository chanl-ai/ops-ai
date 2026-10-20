import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** Marks a page or nav row whose data is sample data while other areas of the console run on real services. */
export function PreviewBadge({ className }: { className?: string }) {
  return (
    <Badge variant="outline" className={cn('border-warning/40 text-warning-text', className)} title="Sample data: no service stores or reads this page yet" data-testid="preview-badge">
      Preview
    </Badge>
  );
}
