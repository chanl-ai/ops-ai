import { Badge } from '@/components/ui/badge';
import type { WidgetTemplate } from '@/lib/types/widgets';

const LABEL = { draft: 'draft', in_review: 'in review', published: 'published', deprecated: 'deprecated' } as const;

/** Where a widget's newest version stands. */
export function WidgetStatusBadge({ widget }: { widget: Pick<WidgetTemplate, 'version' | 'status'> }) {
  const status = widget.status ?? 'published';
  return (
    <Badge variant={status === 'published' ? 'secondary' : 'outline'} data-testid="widget-status">
      v{widget.version} {LABEL[status]}
    </Badge>
  );
}
