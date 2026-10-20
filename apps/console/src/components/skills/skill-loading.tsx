import { FormField } from '@/components/shared/form-field';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { SkillLoading } from '@/lib/types/skills';

export const SKILL_LOADING_LABEL: Record<SkillLoading, string> = { on_match: 'On match', always: 'Always on' };
export const SKILL_LOADING_OPTIONS = (Object.keys(SKILL_LOADING_LABEL) as SkillLoading[]).map((value) => ({ value, label: SKILL_LOADING_LABEL[value] }));

/** Small chip marking a skill that is in every turn; on-match skills show nothing. */
export function AlwaysChip({ loading, className }: { loading: SkillLoading; className?: string }) {
  if (loading !== 'always') return null;
  return (
    <Badge variant="outline" className={className ?? 'text-[10px] font-normal'} data-testid="skill-always-chip">
      Always
    </Badge>
  );
}

/** Loading mode picker for create and edit forms; the hint says what each mode does. */
export function SkillLoadingField({ id, value, onChange, disabled }: { id: string; value: SkillLoading; onChange: (v: SkillLoading) => void; disabled?: boolean }) {
  return (
    <FormField id={id} label="Loading" hint={value === 'always' ? 'Added to every turn of every agent that pins it, after the agent’s own instructions. For shared wording such as a disclosure or tone guide; no use-when line.' : 'Loaded when a message matches the use-when line.'}>
      <Select value={value} disabled={disabled} onValueChange={(v) => onChange(v as SkillLoading)}>
        <SelectTrigger id={id} className="w-48" data-testid={`${id}-select`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SKILL_LOADING_OPTIONS.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
