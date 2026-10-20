'use client';

import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/** The areas a team's publishes are reviewed per, and the modes a review takes (ops_access PUBLISH_AREAS and PUBLISH_MODES). */
export const PUBLISH_AREAS: { id: string; label: string }[] = [
  { id: 'agents', label: 'Agents' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'guardrails', label: 'Guardrails' },
  { id: 'skills', label: 'Skills' },
  { id: 'widgets', label: 'Widgets' },
  { id: 'tools', label: 'Tool modules' },
];
export const PUBLISH_MODES: { id: string; label: string }[] = [
  { id: 'never', label: 'Publish at once' },
  { id: 'major', label: 'Review major changes' },
  { id: 'always', label: 'Review every change' },
];
/** What a team with nothing set gets, as the server reads it. */
export const DEFAULT_PUBLISH_MODE = 'major';

/** One select per area, for the acting team's publish review (policy publishReview). `value` is that team's `{ area: mode }`. */
export function PublishModeEditor({ value, onChange, disabled }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void; disabled?: boolean }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="publish-mode-editor">
      {PUBLISH_AREAS.map((a) => (
        <div key={a.id} className="flex flex-col gap-1.5">
          <Label htmlFor={`publish-${a.id}`} className="text-xs text-muted-foreground">
            {a.label}
          </Label>
          <Select value={value[a.id] ?? DEFAULT_PUBLISH_MODE} onValueChange={(m) => onChange({ ...value, [a.id]: m })} disabled={disabled}>
            <SelectTrigger id={`publish-${a.id}`} className="w-full bg-card" aria-label={`${a.label} review`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PUBLISH_MODES.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ))}
    </div>
  );
}
