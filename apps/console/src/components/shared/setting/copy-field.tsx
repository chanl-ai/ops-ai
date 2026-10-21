'use client';

import * as React from 'react';
import { Check, Copy } from 'lucide-react';
import { toast } from 'sonner';

import { MiddleTruncate } from '@/components/shared/setting/middle-truncate';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group';

function useCopy(value: string) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Couldn’t copy', { description: 'The browser blocked clipboard access.' });
    }
  };
  return { copied, copy };
}

/** A read-only monospace value with a copy button: ids, URLs, an embed snippet. */
export function CopyField({ value, label, id }: { value: string; label: string; id?: string }) {
  const { copied, copy } = useCopy(value);
  return (
    <InputGroup className="bg-card">
      <InputGroupInput id={id} readOnly value={value} aria-label={label} className="font-mono text-xs" />
      <InputGroupAddon align="inline-end">
        <InputGroupButton size="icon-xs" aria-label={`Copy ${label}`} onClick={copy}>
          {copied ? <Check /> : <Copy />}
        </InputGroupButton>
      </InputGroupAddon>
    </InputGroup>
  );
}

/**
 * A record id for a table cell: copyable, whole value in the title, and whole on screen up to 19 characters. A longer
 * one keeps its first 12 and last 6, enough to tell apart ids that share a prefix (levy_document_… and levy_debtor_…).
 */
export function CopyId({ value, label = 'id' }: { value: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <MiddleTruncate text={value} head={12} tail={6} />
      <CopyIconButton value={value} label={label} />
    </span>
  );
}

/** The copy control alone, for a value shown some other way (a link, say). */
export function CopyIconButton({ value, label = 'id' }: { value: string; label?: string }) {
  const { copied, copy } = useCopy(value);
  return (
    <Button type="button" variant="ghost" size="icon" className="size-6 shrink-0" aria-label={`Copy ${label} ${value}`} onClick={copy}>
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
    </Button>
  );
}
