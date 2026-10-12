'use client';

import { AlertTriangle, BookOpen, FileText, FlaskConical, Inbox, LayoutTemplate, Mail, Scale, ShieldCheck, Sparkles, Wrench } from 'lucide-react';

import { AccessBadge, RiskBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { plural } from '@/lib/format';
import type { AgentTemplate, AgentTemplateDetail, TemplateCategory } from '@/lib/types/templates';
import { cn } from '@/lib/utils';

export const CATEGORY_ICON: Record<TemplateCategory, typeof Inbox> = {
  'Intake and triage': Inbox,
  Drafting: Mail,
  Documents: FileText,
  Knowledge: BookOpen,
  'Risk and compliance': ShieldCheck,
  Internal: Scale,
  'Start from scratch': Sparkles,
};

export const CATEGORY_ORDER: TemplateCategory[] = ['Intake and triage', 'Drafting', 'Documents', 'Knowledge', 'Risk and compliance', 'Internal', 'Start from scratch'];

export function TemplateStatusBadge({ status }: { status: AgentTemplate['status'] }) {
  if (status === 'published') return null;
  return <Badge variant={status === 'rejected' ? 'destructive' : 'secondary'}>{status === 'in_review' ? 'In review' : 'Rejected'}</Badge>;
}

/** A template in the gallery: what it does and what it expects, so the choice is made before Configure. */
export function TemplateCard({ template: t, selected, onSelect }: { template: AgentTemplate; selected?: boolean; onSelect?: () => void }) {
  const Icon = CATEGORY_ICON[t.category] ?? LayoutTemplate;
  const body = (
    <>
      <span className="flex items-start gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <Icon className="size-4 text-muted-foreground" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{t.name}</span>
            <TemplateStatusBadge status={t.status} />
          </span>
          <span className="block text-xs text-muted-foreground tabular-nums">
            v{t.version} · {t.ownerTeam}
          </span>
        </span>
        {t.category !== 'Start from scratch' && <RiskBadge risk={t.riskTier} />}
      </span>
      <span className="line-clamp-2 text-xs text-muted-foreground">{t.summary}</span>
      <span className="mt-auto flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Wrench className="size-3" /> {plural(t.expectedTools.length, 'tool')}
        </span>
        <span className="flex items-center gap-1">
          <BookOpen className="size-3" /> {plural(t.expectedKnowledge.length, 'knowledge base')}
        </span>
        <span className="flex items-center gap-1">
          <FlaskConical className="size-3" /> {plural(t.starterTestCount, 'starter test')}
        </span>
      </span>
    </>
  );
  const cls = cn('flex h-full w-full flex-col gap-2 rounded-lg border bg-card p-3 text-left transition-colors', onSelect && 'hover:border-primary/50', selected && 'border-primary bg-primary/5 ring-1 ring-primary');
  return onSelect ? (
    <button type="button" className={cls} onClick={onSelect} aria-pressed={selected} data-testid={`template-card-${t.id}`}>
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** Everything a person needs to judge a template: its job, what it expects, its risk and one worked example. */
export function TemplatePreview({ template: t }: { template: AgentTemplateDetail }) {
  return (
    <div className="flex flex-col gap-4 text-sm" data-testid="template-preview">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">{t.name}</h3>
          <TemplateStatusBadge status={t.status} />
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          {t.category} · v{t.version} · {t.ownerTeam} · used by {plural(t.agentCount, 'agent')}
        </p>
        <p className="text-muted-foreground">{t.description}</p>
      </div>
      {t.category !== 'Start from scratch' && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Risk tier</span> <RiskBadge risk={t.riskTier} />
          <span className="text-muted-foreground">· model</span> <code className="font-mono">{t.model}</code>
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-medium text-muted-foreground">Tools it expects</p>
        {t.expectedTools.length === 0 ? (
          <p className="text-xs text-muted-foreground">None</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {t.expectedTools.map((x) => (
              <li key={x.name} className="flex flex-wrap items-center gap-1.5 text-xs">
                <code className="font-mono">{x.name}</code>
                <AccessBadge access={x.access} />
                {t.unavailableTools.includes(x.name) && <span className="text-warning-text">not available to your team</span>}
                <span className="w-full text-muted-foreground">{x.purpose}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-medium text-muted-foreground">Knowledge it expects</p>
        {t.expectedKnowledge.length === 0 ? (
          <p className="text-xs text-muted-foreground">None</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {t.expectedKnowledge.map((k) => (
              <li key={k} className={cn('flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs', t.missingKnowledge.includes(k) && 'border-warning/40 text-warning-text')}>
                {t.missingKnowledge.includes(k) ? <AlertTriangle className="size-3" /> : <BookOpen className="size-3 text-muted-foreground" />} {k}
                {t.missingKnowledge.includes(k) && <span className="sr-only">(missing)</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {t.suggestedSkills.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Skills it suggests</p>
          <ul className="flex flex-col gap-1">
            {t.suggestedSkills.map((x) => (
              <li key={x.skillId} className="text-xs">
                <span className="font-medium">{x.name}</span> <span className="text-muted-foreground">· {x.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {t.example.input !== '—' && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Example</p>
          <div className="rounded-md border bg-muted/30 p-2.5 text-xs">
            <p className="whitespace-pre-wrap">{t.example.input}</p>
            <p className="mt-2 border-t pt-2 whitespace-pre-wrap text-muted-foreground">{t.example.output}</p>
          </div>
        </div>
      )}
    </div>
  );
}
