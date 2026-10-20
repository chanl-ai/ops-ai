'use client';

import * as React from 'react';
import { Braces, Code2, Globe, Plug } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import type { BlankModuleInput, ModuleType } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

const TYPES: { type: ModuleType; label: string; icon: typeof Plug }[] = [
  { type: 'mcp', label: 'MCP server', icon: Plug },
  { type: 'openapi', label: 'OpenAPI', icon: Braces },
  { type: 'http', label: 'HTTP', icon: Globe },
  { type: 'code', label: 'Code', icon: Code2 },
];

const kebab = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/**
 * New module: one screen, a name and a type. It saves a draft with no operations and no connection and opens the
 * module page, where operations, the connection and every other setting are added tab by tab.
 */
export function NewModuleDialog({ open, onOpenChange, onCreate, creating }: { open: boolean; onOpenChange: (o: boolean) => void; onCreate: (input: BlankModuleInput) => Promise<void>; creating: boolean }) {
  const [displayName, setDisplayName] = React.useState('');
  const [name, setName] = React.useState('');
  const [nameEdited, setNameEdited] = React.useState(false);
  const [type, setType] = React.useState<ModuleType>('http');
  const [description, setDescription] = React.useState('');
  const [err, setErr] = React.useState<{ display?: string; name?: string; form?: string }>({});
  React.useEffect(() => {
    if (!open) return;
    setDisplayName('');
    setName('');
    setNameEdited(false);
    setType('http');
    setDescription('');
    setErr({});
  }, [open]);

  const submit = async () => {
    const e = { display: displayName.trim() ? undefined : 'Give the module a display name.', name: kebab(name) ? undefined : 'Give the module a name, e.g. document-service.' };
    setErr(e);
    if (e.display || e.name) return;
    try {
      await onCreate({ displayName: displayName.trim(), name: kebab(name), type, description: description.trim() || undefined });
    } catch (x) {
      const message = (x as Error).message;
      setErr(/already exists|name/i.test(message) ? { name: message } : { form: message });
    }
  };

  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      size="md"
      title="New module"
      description="Saves a draft. Add operations and the connection on its page."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={creating} loadingText="Saving…" data-testid="new-module-save">
            Save draft
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4" data-testid="new-module-dialog">
        {err.form && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{err.form}</p>}
        <FormField id="nm-display" label="Display name" error={err.display}>
          <Input
            id="nm-display"
            autoFocus
            value={displayName}
            aria-invalid={!!err.display}
            onChange={(e) => {
              setDisplayName(e.target.value);
              if (!nameEdited) setName(kebab(e.target.value));
              setErr({});
            }}
            placeholder="e.g. Document service"
          />
        </FormField>
        <FormField id="nm-name" label="Module name" error={err.name} hint="Workflows pin this name. It follows the display name until you edit it.">
          <Input
            id="nm-name"
            value={name}
            aria-invalid={!!err.name}
            onChange={(e) => {
              setName(e.target.value);
              setNameEdited(true);
              setErr({});
            }}
            placeholder="e.g. document-service"
            className="font-mono"
          />
        </FormField>
        <FormField id="nm-type" label="Type">
          <RadioGroup id="nm-type" value={type} onValueChange={(v) => setType(v as ModuleType)} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {TYPES.map((t) => (
              <label key={t.type} htmlFor={`nm-${t.type}`} className={cn('flex cursor-pointer items-center gap-2 rounded-md border p-2.5 text-sm', type === t.type && 'border-primary bg-primary/5')}>
                <RadioGroupItem value={t.type} id={`nm-${t.type}`} />
                <t.icon className="size-4 text-muted-foreground" /> {t.label}
              </label>
            ))}
          </RadioGroup>
        </FormField>
        <FormField id="nm-desc" label="Description" optional>
          <Textarea id="nm-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Fetches signed loan documents for the lending inbox" className="min-h-16 resize-none" />
        </FormField>
      </div>
    </DialogShell>
  );
}
