'use client';

import * as React from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { toast } from 'sonner';

import { DetailSheet } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { SettingsField } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useSaveThreadSettings, useThreadSettings } from '@/hooks/chat-settings-queries';
import { ApiError } from '@/lib/api/contract';
import type { ChatOverridesPatch, ThreadLimits } from '@/lib/types/chat';

/** The overrides the form holds; every control starts from the thread's saved overrides, else the agent's default. */
interface Draft {
  model: string;
  temperature?: number;
  toolsOff: string[];
  instructions: string;
}

/** The panel's four fields only, a cleared one as null, so the save keeps the thread's knowledge, budget and widget overrides. */
function toPatch(d: Draft, limits: ThreadLimits): ChatOverridesPatch {
  return {
    model: d.model !== limits.defaultModel ? d.model : null,
    temperature: d.temperature ?? null,
    toolsOff: d.toolsOff.length ? d.toolsOff : null,
    instructions: d.instructions.trim() || null,
  };
}

/**
 * A thread's settings within its agent's limits (c-071): each control offers only what the agent allows, so a banker
 * never builds a request the server refuses. The model picker is hidden when there is one model, the temperature when
 * the agent sets no range, tools can only be switched off, and added instructions show only when the agent allows them.
 * Knowledge is chosen with the chips under the thread title, so the thread has one place for it.
 */
export function ThreadSettingsButton({ threadId, disabled }: { threadId: string; disabled?: boolean }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} disabled={disabled} aria-label="Thread settings">
        <SlidersHorizontal className="size-4" /> Settings
      </Button>
      {open && <ThreadSettingsSheet threadId={threadId} open={open} onOpenChange={setOpen} />}
    </>
  );
}

function ThreadSettingsSheet({ threadId, open, onOpenChange }: { threadId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const settings = useThreadSettings(threadId, open);
  const save = useSaveThreadSettings(threadId);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [fieldError, setFieldError] = React.useState<{ field: string; message: string } | null>(null);

  React.useEffect(() => {
    const s = settings.data;
    if (!s || draft) return;
    setDraft({
      model: s.overrides?.model ?? s.limits.defaultModel,
      temperature: s.overrides?.temperature,
      toolsOff: s.overrides?.toolsOff ?? [],
      instructions: s.overrides?.instructions ?? '',
    });
  }, [settings.data, draft]);

  const limits = settings.data?.limits;
  const errorFor = (field: string) => (fieldError?.field.endsWith(`.${field}`) ? fieldError.message : undefined);

  const onSave = () => {
    if (!draft || !limits) return;
    setFieldError(null);
    save.mutate(toPatch(draft, limits), {
      onSuccess: () => {
        toast.success('Thread settings saved', { description: 'Every new message in this thread uses them.' });
        onOpenChange(false);
      },
      onError: (e) => {
        const field = e instanceof ApiError && typeof e.details?.field === 'string' ? e.details.field : '';
        setFieldError({ field, message: e.message.replace(/^overrides\.\w+\.\w+: /, '') });
      },
    });
  };

  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Thread settings"
      description="Narrow the agent for this thread, within what its owner allows. The agent's own instructions and guardrails always apply."
      widthClass="sm:max-w-md"
      testId="thread-settings"
      footerActions={
        <LoadingButton type="submit" form="thread-settings-form" size="sm" isLoading={save.isPending} loadingText="Saving…" disabled={!draft}>
          Save
        </LoadingButton>
      }
    >
      {settings.isPending || !draft || !limits ? (
        settings.isError ? (
          <QueryError what="thread settings" onRetry={() => settings.refetch()} retrying={settings.isFetching} />
        ) : (
          <div className="space-y-4">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )
      ) : (
        // The sheet draws Save in its footer, outside the body, so the button names this form by id.
        <form
          id="thread-settings-form"
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            onSave();
          }}
        >
          {limits.allowedModels.length > 1 && (
            <FormField id="ts-model" label="Model" error={errorFor('model')} hint="Only the models this agent allows.">
              <Select value={draft.model} onValueChange={(model) => setDraft({ ...draft, model })}>
                <SelectTrigger id="ts-model" className="w-full" aria-label="Model">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {limits.allowedModels.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                      {m === limits.defaultModel ? ' (default)' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}

          {limits.temperatureMin !== undefined && limits.temperatureMax !== undefined && limits.temperatureMin < limits.temperatureMax && (
            <FormField id="ts-temperature" label={`Temperature ${draft.temperature !== undefined ? `· ${draft.temperature.toFixed(1)}` : '· agent default'}`} error={errorFor('temperature')} hint={`Lower is steadier, higher more varied; ${limits.temperatureMin} to ${limits.temperatureMax}.`}>
              <Slider
                id="ts-temperature"
                min={limits.temperatureMin}
                max={limits.temperatureMax}
                step={0.1}
                value={[draft.temperature ?? limits.temperatureMin]}
                onValueChange={([t]) => setDraft({ ...draft, temperature: t })}
                aria-label="Temperature"
              />
            </FormField>
          )}

          {limits.switchableTools.length > 0 && (
            <div className="space-y-2">
              <Label>Tools</Label>
              <p className="text-xs text-muted-foreground">Switch a tool off for this thread. Tools can be switched off here, never added.</p>
              <div className="space-y-3" data-testid="thread-settings-tools">
                {limits.switchableTools.map((t) => {
                  const on = !draft.toolsOff.includes(t.id);
                  return (
                    <SettingsField key={t.id} label={t.name} htmlFor={`ts-tool-${t.id}`} description={on ? 'On' : 'Off for this thread'}>
                      <Switch id={`ts-tool-${t.id}`} checked={on} onCheckedChange={(v) => setDraft({ ...draft, toolsOff: v ? draft.toolsOff.filter((x) => x !== t.id) : [...draft.toolsOff, t.id] })} aria-label={t.name} />
                    </SettingsField>
                  );
                })}
              </div>
              {errorFor('toolsOff') && <p className="text-xs text-destructive">{errorFor('toolsOff')}</p>}
            </div>
          )}

          {limits.mayAddInstructions && (
            <FormField id="ts-instructions" label="Add instructions" optional error={errorFor('instructions')} hint="Added after the agent's instructions, never instead of them.">
              <Textarea id="ts-instructions" rows={4} value={draft.instructions} onChange={(e) => setDraft({ ...draft, instructions: e.target.value })} placeholder="e.g. Answer in two sentences and name the policy section." />
            </FormField>
          )}

          {fieldError && !['model', 'temperature', 'toolsOff', 'instructions'].some((f) => fieldError.field.endsWith(`.${f}`)) && <p className="text-sm text-destructive">{fieldError.message}</p>}
        </form>
      )}
    </DetailSheet>
  );
}
