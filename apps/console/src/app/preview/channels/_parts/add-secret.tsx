'use client';

import * as React from 'react';

import { SecretForm } from '@/components/settings/preview/secret-form';
import { usePreviewStore } from '@/lib/settings-preview-store';

import type { SecretTarget } from './mailbox-fields';

/**
 * Add secret, opened from a mailbox's secret field: the settings mock's own Secrets form in a dialog. The secret it
 * saves fills the field it was opened for. Render `dialog` outside any `<form>`: React carries a submit through a
 * portal to the outer form, which would submit the mailbox too.
 */
export function useSecretAdder(onAdded: (target: SecretTarget, name: string) => void) {
  const secrets = usePreviewStore((s) => s.secrets);
  const [open, setOpen] = React.useState(false);
  // Refs, because the save adds the secret and closes the dialog in one batch: state would read as closed by then.
  const target = React.useRef<SecretTarget | null>(null);
  const before = React.useRef<Set<string>>(new Set());
  React.useEffect(() => {
    if (!target.current) return;
    const added = secrets.find((s) => !before.current.has(s.name));
    if (!added) return;
    onAdded(target.current, added.name);
    target.current = null;
  }, [secrets, onAdded]);
  const start = (t: SecretTarget) => {
    before.current = new Set(secrets.map((s) => s.name));
    target.current = t;
    setOpen(true);
  };
  const dialog = <SecretForm shell="dialog" open={open} onOpenChange={setOpen} />;
  return { start, dialog };
}
