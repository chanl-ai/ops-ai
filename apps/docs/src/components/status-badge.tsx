import { cn } from '@/lib/cn';

// Green is working today, amber part-way, blue designed but not built, grey not built or no longer current.
const TONES: Record<string, string> = {
  built: 'built',
  done: 'built',
  passing: 'built',
  current: 'built',
  decided: 'built',
  approved: 'built',
  accepted: 'built',
  'runs today': 'built',
  partial: 'partial',
  'partly built': 'partial',
  'in progress': 'partial',
  blocked: 'partial',
  failing: 'drop',
  planned: 'planned',
  designed: 'planned',
  proposed: 'planned',
  proposal: 'planned',
  option: 'planned',
  draft: 'planned',
};

export function StatusBadge({ status, label, className }: { status: string; label?: string; className?: string }) {
  return <span className={cn('ops-badge', `ops-badge-${TONES[status] ?? 'muted'}`, className)}>{label ?? status}</span>;
}
