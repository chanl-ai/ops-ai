'use client';

import * as React from 'react';
import { ChevronDown, Cpu, RotateCcw } from 'lucide-react';

import { ModelSelect, modelHint } from '@/components/agents/model-select';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { SchemaForm, type Schema } from '@/components/shared/schema-form';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useCan } from '@/hooks/me-queries';
import { useAliasKnobs } from '@/hooks/model-queries';
import { knobProblems, settingsForAlias } from '@/lib/model-forms';
import type { ModelAlias, ModelSettings } from '@/lib/types/domain';

/** The agent page's model control: the alias it runs on, and a dialog to change it and the settings its model supports. */
export function AgentModelButton({
  model,
  settings,
  aliases,
  aliasesReady,
  editable,
  onApply,
}: {
  model: string;
  settings: ModelSettings;
  aliases: ModelAlias[];
  aliasesReady: boolean;
  editable: boolean;
  onApply: (model: string, settings: ModelSettings) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const changed = Object.keys(settings).length;
  return (
    <>
      <span className="flex min-w-0 max-w-full items-center gap-2">
        <span className="text-sm text-muted-foreground">Model</span>
        <Button type="button" id="ag-model" variant="outline" size="sm" className="max-w-full min-w-0" onClick={() => setOpen(true)} data-testid="agent-model-button">
          <span className="truncate">{model || 'Choose'}</span>
          {changed > 0 && <span className="text-xs text-muted-foreground">{changed} changed</span>}
          <ChevronDown />
        </Button>
      </span>
      <AgentModelDialog open={open} onOpenChange={setOpen} model={model} settings={settings} aliases={aliases} aliasesReady={aliasesReady} editable={editable} onApply={onApply} />
    </>
  );
}

/**
 * Pick the agent's alias and tune only what that alias's model takes. The settings come from the alias's knobs route as
 * JSON Schema, so a model with no temperature shows none; each starts at the catalog default and has its own Reset. The
 * edit stays in the dialog until Done, so a half-typed number is never saved, and a switch to another alias drops any
 * setting the new model does not take.
 */
export function AgentModelDialog({
  open,
  onOpenChange,
  model,
  settings,
  aliases,
  aliasesReady,
  editable,
  onApply,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  model: string;
  settings: ModelSettings;
  aliases: ModelAlias[];
  aliasesReady: boolean;
  editable: boolean;
  onApply: (model: string, settings: ModelSettings) => void;
}) {
  const [alias, setAlias] = React.useState(model);
  const [values, setValues] = React.useState<ModelSettings>(settings);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    if (!open) return;
    setAlias(model);
    setValues(settings);
    setErrors({});
    // Opening is the only reset: a save landing while the dialog is open must not replace what is being typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const admin = useCan('settings', 'manage') === true;
  // Before an admin has made any alias there is nothing to pick: the dialog says what is missing and who can fix it.
  const none = aliasesReady && aliases.length === 0;
  const knobs = useAliasKnobs(alias, open && !none);
  const properties = knobs.data?.knobs.properties;
  const retired = knobs.isError && (knobs.error as { code?: string }).code === 'unknown_model_alias';
  // Settings shown are the ones the alias takes; the rest are dropped when the alias changes (and again on Done).
  const shown = properties ? settingsForAlias(properties, values) : alias === model ? values : {};
  const count = Object.keys(shown).length;

  const done = () => {
    const kept = properties ? settingsForAlias(properties, values) : alias === model ? values : {};
    const found = properties ? knobProblems(properties, kept) : {};
    if (Object.keys(found).length) return setErrors(found);
    onApply(alias, kept);
    onOpenChange(false);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Model"
      description="The alias this agent runs on, and the settings its model supports. A setting left alone uses the model’s catalog default."
      onSubmit={editable ? done : undefined}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {editable ? 'Cancel' : 'Close'}
          </Button>
          {editable && (
            <Button type="submit" data-testid="agent-model-done">
              Done
            </Button>
          )}
        </>
      }
    >
      {none ? (
        <EmptyState
          icon={Cpu}
          title={admin ? 'No models are connected yet' : 'No models are set up yet'}
          description={admin ? 'Connect a provider and make an alias, then pick it here.' : 'An account admin has to connect a provider and make an alias before agents can answer.'}
          action={admin ? { label: 'Set up models', href: '/settings/workspace/model-providers' } : undefined}
          testId="agent-model-none"
        />
      ) : (
        <div className="flex flex-col gap-5">
          {!editable && (
            <Alert data-testid="agent-model-readonly">
              <AlertDescription>You can see this agent’s model and settings. A builder on its team changes them.</AlertDescription>
            </Alert>
          )}
          <FormField id="am-alias" label="Alias" hint={modelHint(aliases, alias)}>
            <fieldset disabled={!editable} className="border-0 p-0">
              <ModelSelect id="am-alias" value={alias} onValueChange={(v) => (setAlias(v), setErrors({}))} aliases={aliases} />
            </fieldset>
          </FormField>
          <div className="flex flex-col gap-4" data-testid="agent-model-knobs">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Settings</h3>
              {editable && count > 0 && (
                <Button type="button" variant="ghost" size="sm" onClick={() => (setValues({}), setErrors({}))} data-testid="agent-model-reset-all">
                  <RotateCcw /> Reset all
                </Button>
              )}
            </div>
            {knobs.isPending ? (
              <div className="flex flex-col gap-3" data-testid="agent-model-loading">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : retired ? (
              <Alert variant="destructive" data-testid="agent-model-retired">
                <AlertDescription>{alias} is no longer offered. Choose another alias to change settings.</AlertDescription>
              </Alert>
            ) : knobs.isError ? (
              <QueryError what={`the settings of ${alias}`} onRetry={() => knobs.refetch()} retrying={knobs.isFetching} error={knobs.error} testId="agent-model-knobs-error" />
            ) : Object.keys(properties ?? {}).length === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="agent-model-no-knobs">
                This model has no settings to change.
              </p>
            ) : (
              <>
                {!knobs.data?.catalogued && <p className="text-xs text-muted-foreground">This model is not in the catalog, so no ranges or defaults are known. The endpoint’s own defaults apply.</p>}
                <SchemaForm
                  schema={knobs.data!.knobs as Schema}
                  value={shown}
                  idPrefix="knob"
                  defaults
                  readOnly={!editable}
                  errors={errors}
                  testIds={Object.fromEntries(Object.keys(properties ?? {}).map((k) => [k, `knob-${k}`]))}
                  onChange={(next) => (setValues(next as ModelSettings), setErrors({}))}
                  testId="agent-model-form"
                />
              </>
            )}
          </div>
        </div>
      )}
    </DialogShell>
  );
}
