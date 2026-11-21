'use client';

import { Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { SkillCheck, SkillCheckType } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

const SKILL_CHECK_TYPES: { value: SkillCheckType; label: string; hint: string }[] = [
  { value: 'calls_tool', label: 'Calls tool', hint: 'The skill must call this tool, with these arguments when given.' },
  { value: 'not_calls_tool', label: 'Does not call tool', hint: 'Fails if the skill calls this tool.' },
  { value: 'cites', label: 'Cites document', hint: 'The reply must cite this knowledge base, and the section when given.' },
  { value: 'reply_contains', label: 'Reply contains', hint: 'Case-insensitive text the reply must include.' },
  { value: 'reply_not_contains', label: 'Reply must not contain', hint: 'Fails if the reply includes this text.' },
  { value: 'refuses', label: 'Refuses (out of scope)', hint: 'The skill must decline or hand off. Name the topic.' },
  { value: 'extracts', label: 'Extracts field', hint: 'The extracted field must equal this value.' },
  { value: 'rubric', label: 'Rubric (advisory)', hint: 'Advisory: recorded, not scored.' },
];

/** Whether a check has the values its type needs. */
export function checkComplete(c: SkillCheck) {
  if (c.type === 'calls_tool' || c.type === 'not_calls_tool') return !!c.tool;
  if (c.type === 'cites') return !!c.source;
  if (c.type === 'extracts') return !!c.field?.trim() && !!c.value?.trim();
  return !!c.text?.trim();
}

/** One skill test check's editor. */
export function SkillCheckRow({ check, onChange, onRemove, options, index }: { check: SkillCheck; onChange: (c: SkillCheck) => void; onRemove: () => void; options?: { tools: string[]; collections: string[] }; index: number }) {
  const meta = SKILL_CHECK_TYPES.find((t) => t.value === check.type)!;
  const tools = options?.tools ?? [];
  const sel = (id: string, value: string | undefined, items: string[], placeholder: string, set: (v: string) => void, mono = false) => (
    <Select value={value ?? ''} onValueChange={set}>
      <SelectTrigger id={id} className={cn('w-full', mono && 'font-mono text-xs')} aria-label={placeholder}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((t) => (
          <SelectItem key={t} value={t} className={mono ? 'font-mono text-xs' : undefined}>
            {t}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-testid="eval-check-row">
      <div className="flex items-start gap-2">
        <Select value={check.type} onValueChange={(t) => onChange({ type: t as SkillCheckType })}>
          <SelectTrigger className="w-56 shrink-0" aria-label={`Check ${index + 1} type`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SKILL_CHECK_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="min-w-0 flex-1">
          {(check.type === 'calls_tool' || check.type === 'not_calls_tool') && sel(`chk-${index}-tool`, check.tool, tools, 'Choose a tool', (tool) => onChange({ ...check, tool }), true)}
          {check.type === 'cites' && sel(`chk-${index}-src`, check.source, options?.collections ?? [], 'Choose a knowledge base', (source) => onChange({ ...check, source }))}
          {check.type === 'extracts' && (
            <div className="grid gap-2">
              <Input aria-label="Field" value={check.field ?? ''} onChange={(e) => onChange({ ...check, field: e.target.value })} placeholder="e.g. amount" className="font-mono text-xs" />
              <Input aria-label="Value" value={check.value ?? ''} onChange={(e) => onChange({ ...check, value: e.target.value })} placeholder="e.g. 1240.18" />
            </div>
          )}
          {['reply_contains', 'reply_not_contains', 'refuses', 'rubric'].includes(check.type) && (
            <Input
              aria-label={meta.label}
              value={check.text ?? ''}
              onChange={(e) => onChange({ ...check, text: e.target.value })}
              placeholder={check.type === 'refuses' ? 'e.g. Investment advice' : check.type === 'rubric' ? 'e.g. Explains the decision in plain language' : 'e.g. callback'}
            />
          )}
        </div>
        <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label={`Remove check ${index + 1}`} onClick={onRemove}>
          <X className="size-4" />
        </Button>
      </div>
      {check.type === 'cites' && check.source && (
        <Input aria-label="Section" value={check.section ?? ''} onChange={(e) => onChange({ ...check, section: e.target.value || undefined })} placeholder="e.g. Wire Fraud Playbook §3.2 (optional)" />
      )}
      {check.type === 'calls_tool' && check.tool && (
        <div className="flex flex-col gap-1.5">
          {(check.args ?? []).map((a, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input aria-label="Argument" value={a.path} onChange={(e) => onChange({ ...check, args: check.args!.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)) })} placeholder="e.g. amount" className="font-mono text-xs" />
              <span className="text-xs text-muted-foreground">equals</span>
              <Input aria-label="Expected value" value={a.equals} onChange={(e) => onChange({ ...check, args: check.args!.map((x, j) => (j === i ? { ...x, equals: e.target.value } : x)) })} placeholder="e.g. 1240.18" />
              <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label="Remove argument" onClick={() => onChange({ ...check, args: check.args!.filter((_, j) => j !== i) })}>
                <X className="size-3.5" />
              </Button>
            </div>
          ))}
          <Button variant="ghost" size="sm" className="self-start" onClick={() => onChange({ ...check, args: [...(check.args ?? []), { path: '', equals: '' }] })}>
            <Plus className="size-3.5" /> Match an argument
          </Button>
        </div>
      )}
      <p className={cn('text-xs', check.type === 'rubric' ? 'text-warning-text' : 'text-muted-foreground')}>{meta.hint}</p>
    </div>
  );
}
