'use client';

import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';

/** Where a value comes from, so a person who sees it in a team knows whether the team set it or the workspace did. */
export function SourceBadge({ level }: { level: 'Workspace' | 'Team' | 'Agent' | 'Default' }) {
  return (
    <Badge variant="outline" className="font-normal" data-testid="source-badge">
      From {level.toLowerCase()}
    </Badge>
  );
}

/** For a workspace setting: lets teams override it. Off means the workspace value is final. */
export function InheritSwitch({ checked, onChange, id = 'inherit' }: { checked: boolean; onChange: (v: boolean) => void; id?: string }) {
  return (
    <div className="flex items-center gap-3">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <Label htmlFor={id} className="font-normal">
        Allow this setting to be overridden at the team level
      </Label>
    </div>
  );
}
