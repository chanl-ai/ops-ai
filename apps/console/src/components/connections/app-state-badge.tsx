'use client';

import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { AppState } from '@/hooks/systems-queries';
import { APP_STATES, labelFor, type AppStateShown, type AppTone } from '@/lib/app-state';

// The words of each state come from the one table (lib/app-state.ts); this adds only how it looks. Typed by the SDK's
// AppState, so a state the API adds fails the build until the table has it.
const TABLE: Record<AppState, AppStateShown> = APP_STATES;
const TONE: Record<AppTone, { className: string; icon?: typeof CircleCheck }> = {
  success: { className: 'border-success/40 bg-success/10 text-success-text', icon: CircleCheck },
  warning: { className: 'border-warning/40 bg-warning/10 text-warning-text', icon: CircleAlert },
  muted: { className: 'text-muted-foreground' },
  destructive: { className: 'border-destructive/40 bg-destructive/10 text-destructive-text', icon: CircleAlert },
};
export const APP_STATE_LOOK = Object.fromEntries(
  (Object.keys(TABLE) as AppState[]).map((k) => [k, { label: TABLE[k].label, ...TONE[TABLE[k].tone], ...(k === 'test_failed' ? { icon: TriangleAlert } : {}) }]),
) as Record<AppState, { label: string; className: string; icon?: typeof CircleCheck }>;

/** An app's state as a badge, worded the same on its card, its page, Mine and the chat Connect card; `manages` false
 * gives the member's words. */
export function AppStateBadge({
  card,
  testId,
  manages = true,
  whose,
}: {
  card: { appState: AppState };
  testId?: string;
  manages?: boolean;
  /** Whose state this is ("You", "Team account"), said before the badge where it could be read as another's. */
  whose?: string | null;
}) {
  if (!card.appState) return null;
  const shown = { ...APP_STATE_LOOK[card.appState], label: labelFor(card.appState, manages) };
  const Icon = shown.icon;
  const badge = (
    <Badge variant="outline" className={shown.className} data-testid={testId} data-state={card.appState}>
      {Icon && <Icon />}
      {shown.label}
    </Badge>
  );
  if (!whose) return badge;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" data-testid={testId ? `${testId}-whose` : undefined}>
      {whose}:{badge}
    </span>
  );
}
