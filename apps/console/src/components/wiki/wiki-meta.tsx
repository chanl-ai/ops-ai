import { Bot, FileText, Globe, PenLine } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { dateOnly } from '@/lib/format';
import type { WikiGate, WikiProvenance } from '@/lib/types/wiki';
import { cn } from '@/lib/utils';

export const PROVENANCE: Record<WikiProvenance, { label: string; hint: string; icon: typeof Globe; cls: string }> = {
  external: { label: 'External', hint: 'Synced from a connection', icon: Globe, cls: '' },
  file: { label: 'File', hint: 'From an uploaded document', icon: FileText, cls: '' },
  page: { label: 'Page', hint: 'Written in the Wiki', icon: PenLine, cls: '' },
  remembered: { label: 'Remembered', hint: 'Written by an agent; unverified until a person marks it', icon: Bot, cls: 'border-warning/40 text-warning-text' },
};
export const PROVENANCE_OPTIONS = (Object.keys(PROVENANCE) as WikiProvenance[]).map((v) => ({ value: v, label: PROVENANCE[v].label, icon: PROVENANCE[v].icon }));

export const GATE_LABEL: Record<WikiGate, string> = { open: 'Open', team: 'Team', gated: 'Gated' };

export function ProvenanceChip({ provenance }: { provenance: WikiProvenance }) {
  const p = PROVENANCE[provenance];
  return (
    <Badge variant="outline" className={cn('gap-1 font-normal', p.cls)} title={p.hint}>
      <p.icon className="size-3" /> {p.label}
    </Badge>
  );
}

export function VerifiedText({ at }: { at: string | null }) {
  return at ? <span className="whitespace-nowrap text-xs tabular-nums">{dateOnly(at.slice(0, 10))}</span> : <span className="text-xs text-warning-text">not verified</span>;
}
