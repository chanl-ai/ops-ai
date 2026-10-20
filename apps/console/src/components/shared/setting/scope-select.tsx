'use client';

import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export type ScopeValue = 'default' | 'on' | 'off';

/** A value per environment (or team) side by side: "Default (on)", "On", "Off". */
export function ScopeSelect({ scopes, value, onChange, defaultIs }: { scopes: { id: string; label: string }[]; value: Record<string, ScopeValue>; onChange: (v: Record<string, ScopeValue>) => void; defaultIs: 'on' | 'off' }) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {scopes.map((s) => (
        <div key={s.id} className="flex flex-col gap-1.5">
          <Label htmlFor={`scope-${s.id}`} className="text-xs text-muted-foreground">
            {s.label}
          </Label>
          <Select value={value[s.id] ?? 'default'} onValueChange={(v) => onChange({ ...value, [s.id]: v as ScopeValue })}>
            <SelectTrigger id={`scope-${s.id}`} className="w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="default">Default ({defaultIs})</SelectItem>
              <SelectItem value="on">On</SelectItem>
              <SelectItem value="off">Off</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ))}
    </div>
  );
}
