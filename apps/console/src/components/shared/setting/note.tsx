import type { ReactNode } from 'react';
import { FlaskConical, Info, TriangleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/lib/utils';

export type NoteTone = 'info' | 'warning' | 'sample';

const ICON = { info: Info, warning: TriangleAlert, sample: FlaskConical } as const;

/** An inline banner on the page or inside a card: information, a warning, or the sample-data notice. */
export function Note({ tone = 'info', title, children, className }: { tone?: NoteTone; title?: ReactNode; children?: ReactNode; className?: string }) {
  const Icon = ICON[tone];
  return (
    <Alert className={cn(tone === 'warning' && 'border-warning/40 [&>svg]:text-warning-text', className)} data-testid={`note-${tone}`}>
      <Icon />
      {title && <AlertTitle>{title}</AlertTitle>}
      {children && <AlertDescription className={cn(!title && 'col-start-2')}>{children}</AlertDescription>}
    </Alert>
  );
}
