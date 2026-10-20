'use client';

import { Copy, FileUp, PenLine, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { SkillEditClass, SkillOrigin, SkillSectionKey, SkillStatus, SkillToolRef, SkillVersionState } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

export const STATUS_LABEL: Record<SkillStatus, string> = { draft: 'Draft', in_review: 'In review', published: 'Published', deprecated: 'Deprecated' };
const STATUS_CLS: Record<SkillStatus, { cls: string; dot: string }> = {
  draft: { cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground/60' },
  in_review: { cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' },
  published: { cls: 'border-success/40 bg-success/10 text-success-text', dot: 'bg-success' },
  deprecated: { cls: 'border-warning/40 bg-warning/10 text-warning-text', dot: 'bg-warning' },
};

export function SkillStatusBadge({ status }: { status: SkillStatus }) {
  const s = STATUS_CLS[status];
  return (
    <span className={cn(pill, s.cls)}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {STATUS_LABEL[status]}
    </span>
  );
}

export const VERSION_STATE_LABEL: Record<SkillVersionState, string> = { draft: 'Draft', in_review: 'In review', published: 'Published', superseded: 'Superseded', deprecated: 'Deprecated', rejected: 'Rejected' };

export const EDIT_CLASS: Record<SkillEditClass, { label: string; hint: string }> = {
  free: { label: 'Free', hint: 'Applies at once and is logged.' },
  re_test: { label: 'Re-test', hint: 'Wording changed: the tests run again and one approver from the owning team decides.' },
  re_approval: { label: 'Re-approval', hint: 'Tools, knowledge bases, guardrails or resources changed: the tests run again and two approvers decide.' },
};

export function EditClassBadge({ editClass }: { editClass: SkillEditClass }) {
  return (
    <span className={cn(pill, editClass === 're_approval' ? 'border-warning/40 bg-warning/10 text-warning-text' : 'border-border bg-card text-muted-foreground')} title={EDIT_CLASS[editClass].hint}>
      {EDIT_CLASS[editClass].label}
    </span>
  );
}

export const ORIGIN: Record<SkillOrigin, { label: string; icon: typeof Sparkles }> = {
  generated: { label: 'Generated', icon: Sparkles },
  blank: { label: 'Written', icon: PenLine },
  imported: { label: 'Imported', icon: FileUp },
  duplicated: { label: 'Duplicated', icon: Copy },
};

export const SECTION_TITLE: Record<SkillSectionKey, string> = { steps: 'Steps', rules: 'Rules', examples: 'Examples', output_format: 'Output format' };
export const SECTIONS: SkillSectionKey[] = ['steps', 'rules', 'examples', 'output_format'];

/** The instructions body is four markdown sections in a fixed order; these convert between the two shapes. */
export function splitSections(instructions: string): Record<SkillSectionKey, string> {
  const out: Record<SkillSectionKey, string> = { steps: '', rules: '', examples: '', output_format: '' };
  let cur: SkillSectionKey = 'steps';
  for (const line of instructions.split('\n')) {
    const h = line.match(/^##\s+(.+)$/);
    const key = h && SECTIONS.find((k) => SECTION_TITLE[k].toLowerCase() === h[1].trim().toLowerCase());
    if (key) cur = key;
    else out[cur] += `${line}\n`;
  }
  for (const k of SECTIONS) out[k] = out[k].trim();
  return out;
}
export const joinSections = (s: Record<SkillSectionKey, string>) => SECTIONS.map((k) => `## ${SECTION_TITLE[k]}\n${s[k].trim()}`).join('\n\n');

export function ToolChips({ tools, max = 4, outOfScope = [] }: { tools: Pick<SkillToolRef, 'toolId' | 'name' | 'access'>[]; max?: number; outOfScope?: string[] }) {
  if (!tools.length) return <span className="text-xs text-muted-foreground">None</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {tools.slice(0, max).map((t) => (
        <Badge key={t.toolId} variant="secondary" className={cn('font-mono text-[11px] font-normal', outOfScope.includes(t.toolId) && 'border-warning/40 bg-warning/10 text-warning-text')}>
          {t.name}
        </Badge>
      ))}
      {tools.length > max && <span className="text-xs text-muted-foreground">+{tools.length - max}</span>}
    </div>
  );
}

/** Line diff of two texts (longest common subsequence), for version comparison. */
export function lineDiff(a: string, b: string): { kind: 'same' | 'add' | 'del'; text: string }[] {
  const x = a.split('\n');
  const y = b.split('\n');
  const m = x.length;
  const n = y.length;
  const dp = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { kind: 'same' | 'add' | 'del'; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (x[i] === y[j]) {
      out.push({ kind: 'same', text: x[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ kind: 'del', text: x[i++] });
    else out.push({ kind: 'add', text: y[j++] });
  }
  while (i < m) out.push({ kind: 'del', text: x[i++] });
  while (j < n) out.push({ kind: 'add', text: y[j++] });
  return out;
}

export function DiffView({ before, after, testId }: { before: string; after: string; testId?: string }) {
  const rows = lineDiff(before, after);
  const changed = rows.some((r) => r.kind !== 'same');
  if (!changed) return <p className="text-sm text-muted-foreground">No differences.</p>;
  return (
    <pre className="max-h-[50vh] overflow-auto rounded-md border bg-muted/30 py-2 font-mono text-xs leading-relaxed" data-testid={testId}>
      {rows.map((r, i) => (
        <div key={i} className={cn('px-3 whitespace-pre-wrap', r.kind === 'add' && 'bg-success/10 text-success-text', r.kind === 'del' && 'bg-destructive/10 text-destructive line-through decoration-destructive/40')}>
          <span className="mr-2 inline-block w-3 select-none text-muted-foreground">{r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ' '}</span>
          {r.text || ' '}
        </div>
      ))}
    </pre>
  );
}

/** Renders a skill body: headings, numbered and bulleted lists, quotes and inline code. */
export function MarkdownPreview({ text, className }: { text: string; className?: string }) {
  const blocks = text.split('\n');
  return (
    <div className={cn('flex flex-col gap-1.5 text-sm leading-relaxed', className)}>
      {blocks.map((l, i) => {
        const inline = (s: string) => s.split(/(`[^`]+`)/g).map((p, k) => (p.startsWith('`') && p.endsWith('`') ? <code key={k} className="rounded bg-muted px-1 font-mono text-xs">{p.slice(1, -1)}</code> : <span key={k}>{p}</span>));
        if (/^##\s/.test(l)) return <h3 key={i} className="mt-2 text-sm font-semibold first:mt-0">{l.replace(/^##\s+/, '')}</h3>;
        if (/^\d+\.\s/.test(l)) return <p key={i} className="pl-5 -indent-5">{inline(l)}</p>;
        if (/^-\s/.test(l)) return <p key={i} className="pl-4 -indent-3">• {inline(l.replace(/^-\s+/, ''))}</p>;
        if (/^>\s?/.test(l)) return <blockquote key={i} className="border-l-2 pl-3 text-muted-foreground italic">{inline(l.replace(/^>\s?/, ''))}</blockquote>;
        if (!l.trim()) return null;
        return <p key={i}>{inline(l)}</p>;
      })}
    </div>
  );
}
