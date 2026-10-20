'use client';

import * as React from 'react';
import { KeyRound, RefreshCw } from 'lucide-react';

import { CopyField } from '@/components/shared/setting/copy-field';
import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { relativeTime } from '@/lib/format';

/**
 * A credential: masked at rest, shown once when it is created or rotated, with when it was last used. The value is
 * never read back from the server, so the mask is made of the stored hint (the last four characters).
 */
export function SecretField({
  name,
  hint,
  lastUsedAt,
  rotatedAt,
  onRotate,
  canRotate = true,
}: {
  name: string;
  hint: string;
  lastUsedAt?: string;
  rotatedAt?: string;
  /** Returns the new value, which is shown once. */
  onRotate: () => Promise<string>;
  canRotate?: boolean;
}) {
  const [fresh, setFresh] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const rotate = async () => {
    setBusy(true);
    try {
      setFresh(await onRotate());
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3" data-testid={`secret-field-${name}`}>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <KeyRound className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input readOnly value={`••••••••••••${hint}`} aria-label={`${name} (masked)`} className="bg-card pl-9 font-mono text-xs" />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={rotate} disabled={!canRotate || busy}>
          <RefreshCw className="size-3.5" /> Rotate
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Last used {lastUsedAt ? relativeTime(lastUsedAt) : 'never'} · Rotated {rotatedAt ? relativeTime(rotatedAt) : 'never'}
      </p>
      {fresh && (
        <div className="flex flex-col gap-2" data-testid="secret-shown-once">
          <Note tone="warning" title="Copy it now">
            This value is shown once. After you leave, only the last four characters are kept.
          </Note>
          <CopyField value={fresh} label={`new ${name}`} />
        </div>
      )}
    </div>
  );
}
