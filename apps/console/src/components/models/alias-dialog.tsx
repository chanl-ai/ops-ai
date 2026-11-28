'use client';

import * as React from 'react';
import { Brain, Eye } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SearchSelect } from '@/components/shared/search-select';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useSaveAlias } from '@/hooks/model-queries';
import { providerConnectionOptions, modelOptions } from '@/hooks/options-queries';
import { aliasNameProblem, aliasSaveErrors, SENSITIVITIES, priceProblem } from '@/lib/model-forms';
import type { CatalogModel, ModelAliasRow, ProviderConnection } from '@/lib/types/models';

type Picked = { id: string; label: string };
type Errors = Partial<Record<'name' | 'connection' | 'model' | 'inputPerMillion' | 'outputPerMillion' | 'submit', string>>;

/**
 * Make an alias, or save a new version of one: the name builders pick, the connection and model it calls, what data it
 * is cleared for and its prices. The model list is the connection's catalog (or the ids its key lists); a model's
 * catalog price is the starting value and stays editable for a negotiated rate. The name is fixed once made.
 */
export function AliasDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (open: boolean) => void; editing: ModelAliasRow | null }) {
  const save = useSaveAlias();
  const [name, setName] = React.useState('');
  const [connection, setConnection] = React.useState<(Picked & { row?: ProviderConnection }) | null>(null);
  const [model, setModel] = React.useState<Picked | null>(null);
  const [catalog, setCatalog] = React.useState<CatalogModel | null>(null);
  const [cleared, setCleared] = React.useState('internal');
  const [input, setInput] = React.useState('');
  const [output, setOutput] = React.useState('');
  const [errors, setErrors] = React.useState<Errors>({});

  React.useEffect(() => {
    if (!open) return;
    setErrors({});
    setCatalog(null);
    setName(editing?.name ?? '');
    setCleared(editing?.clearedSensitivity ?? 'internal');
    setInput(editing?.inputPerMillion ?? '');
    setOutput(editing?.outputPerMillion ?? '');
    setModel(editing ? { id: editing.modelId, label: editing.modelId } : null);
    setConnection(null);
    if (editing) {
      // The stored choice is shown by name: the connection is read by its id.
      void providerConnectionOptions.fetch({ ids: [editing.providerId] }).then((page) => {
        const c = page.data[0];
        if (c) setConnection({ id: c.id, label: c.label, row: c.connection });
      });
    }
  }, [open, editing]);

  const source = React.useMemo(() => (connection?.row ? modelOptions(connection.row) : null), [connection?.row]);

  const submit = async () => {
    const found: Errors = {
      name: editing ? undefined : aliasNameProblem(name),
      connection: connection ? undefined : 'Pick the connection it calls.',
      model: model ? undefined : 'Pick the model.',
      inputPerMillion: priceProblem(input) ?? (!input.trim() && output.trim() ? 'Enter the input price too, or clear both to use the catalog price.' : undefined),
      outputPerMillion: priceProblem(output) ?? (input.trim() && !output.trim() ? 'Enter the output price too, or clear both to use the catalog price.' : undefined),
    };
    if (Object.values(found).some(Boolean)) return setErrors(found);
    // Both blank sends no price, so models-service prices the model from its catalog or says it needs one.
    const price = input.trim() ? { inputPerMillion: Number(input), outputPerMillion: Number(output) } : {};
    const body = { providerId: connection!.id, modelId: model!.id, clearedSensitivity: cleared, ...price };
    try {
      const saved = await save.mutateAsync({ name: editing?.name ?? name.trim(), version: !!editing, input: body });
      toast.success(editing ? `Saved ${saved.name} as version ${saved.version}` : `Made ${saved.name}`, { description: 'Builders can pick it on an agent.' });
      onOpenChange(false);
    } catch (e) {
      setErrors(aliasSaveErrors(e as { message: string; code?: string }, !!editing));
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={editing ? `Edit ${editing.name}` : 'Make an alias'}
      description="Only an account admin makes aliases."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={save.isPending} loadingText="Saving…" data-testid="alias-save">
            {editing ? 'Save version' : 'Make alias'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {editing && (
          <Alert data-testid="alias-new-version">
            <AlertTitle>Saves as version {editing.version + 1}</AlertTitle>
            <AlertDescription>Agents on {editing.name} pick up the new model on their next run; versions already published keep working.</AlertDescription>
          </Alert>
        )}
        <FormField id="al-name" label="Alias name" error={errors.name} hint={editing ? 'Fixed once made. A change saves as a new version under the same name.' : 'What builders see, such as careful-writer. Lowercase letters, digits and dashes.'}>
          <Input id="al-name" value={name} readOnly={!!editing} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. careful-writer" aria-invalid={!!errors.name} data-testid="alias-name" />
        </FormField>
        <FormField id="al-connection" label="Connection" error={errors.connection}>
          <SearchSelect
            id="al-connection"
            source={providerConnectionOptions}
            value={connection}
            onChange={(id, o) => {
              setConnection(o ? { id, label: o.label, row: o.connection } : null);
              setModel(null);
              setCatalog(null);
              setErrors({});
            }}
            placeholder="Pick a connection"
            searchPlaceholder="Search connections…"
            testId="alias-connection"
          />
        </FormField>
        <FormField id="al-model" label="Model" error={errors.model} hint="Searchable. Listed by the connection’s catalog, or by its key.">
          {source ? (
            <SearchSelect
              id="al-model"
              source={source}
              value={model}
              onChange={(id, o) => {
                setModel({ id, label: id });
                setCatalog(o?.model ?? null);
                if (o?.model) {
                  if (o.model.inputPerMillion !== null) setInput(String(o.model.inputPerMillion));
                  if (o.model.outputPerMillion !== null) setOutput(String(o.model.outputPerMillion));
                }
                setErrors({});
              }}
              placeholder="Pick a model"
              searchPlaceholder="Search models…"
              testId="alias-model"
            />
          ) : (
            <SearchSelect id="al-model" source={providerConnectionOptions} value={null} onChange={() => undefined} placeholder="Pick a connection first" disabled testId="alias-model" />
          )}
        </FormField>
        {catalog && (
          <div className="flex flex-wrap items-center gap-1 rounded-lg border bg-muted/40 p-3" data-testid="alias-catalog">
            {catalog.reasoning && (
              <Badge variant="outline">
                <Brain /> Thinking
              </Badge>
            )}
            {catalog.images && (
              <Badge variant="outline">
                <Eye /> Vision
              </Badge>
            )}
            {catalog.context !== null && <Badge variant="outline">{Math.round(catalog.context / 1000)}k context</Badge>}
            <span className="w-full text-xs text-muted-foreground">From the model catalog. Read only here; the catalog is the source.</span>
          </div>
        )}
        <FormField id="al-cleared" label="Cleared for data up to" hint="An agent holding more sensitive data cannot use this alias.">
          <Select value={cleared} onValueChange={setCleared}>
            <SelectTrigger id="al-cleared" className="w-full sm:w-60" data-testid="alias-cleared">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SENSITIVITIES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <div className="flex flex-col gap-4">
          <FormField id="al-in" label="Input price per 1M tokens" error={errors.inputPerMillion} hint="Catalog price. Change it for a negotiated rate.">
            <Input id="al-in" type="number" min={0} step="any" value={input} onChange={(e) => (setInput(e.target.value), setErrors({}))} placeholder="0.00" data-testid="alias-input-price" />
          </FormField>
          <FormField id="al-out" label="Output price per 1M tokens" error={errors.outputPerMillion}>
            <Input id="al-out" type="number" min={0} step="any" value={output} onChange={(e) => (setOutput(e.target.value), setErrors({}))} placeholder="0.00" data-testid="alias-output-price" />
          </FormField>
        </div>
        {errors.submit && (
          <Alert variant="destructive" data-testid="alias-error">
            <AlertDescription>{errors.submit}</AlertDescription>
          </Alert>
        )}
      </div>
    </DialogShell>
  );
}
