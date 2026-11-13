'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Stepper } from '@/components/shared/stepper';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useCheckProviderKey, useProviderKeyModels, useSaveProviderKey, useSetChatModel } from '@/hooks/provider-key-queries';
import { chatModelBody, keyStep, keyWhere, type ProviderStep, providerStep, SETUP_PROVIDERS, setupKeyName } from '@/lib/model-setup';
import type { KeyWhere } from '@/lib/types/provider-keys';

const STEPS = ['Provider', 'Key', 'Chat model'] as const;
const modelStep = z.object({ model: z.string().min(1, 'Pick the model chat answers with.') });

/**
 * First-run model setup in three steps: the provider (Azure OpenAI with its endpoint), the key pasted and tested by
 * models-service, then the chat model picked from what the key lists. The key is saved in the account's one key store
 * (Model providers) under one name per provider, so running setup again replaces it.
 */
export function ModelSetupDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [step, setStep] = React.useState(1);
  const [tested, setTested] = React.useState<KeyWhere | null>(null);
  const [refused, setRefused] = React.useState<string>();
  const first = useForm<ProviderStep>({ resolver: zodResolver(providerStep), defaultValues: { provider: 'openai', endpoint: '', apiVersion: 'v1' } });
  const second = useForm<z.infer<typeof keyStep>>({ resolver: zodResolver(keyStep), defaultValues: { value: '' } });
  const third = useForm<z.infer<typeof modelStep>>({ resolver: zodResolver(modelStep), defaultValues: { model: '' } });
  const save = useSaveProviderKey();
  const check = useCheckProviderKey();
  const choose = useSetChatModel();
  const chosen = first.watch('provider');
  const name = setupKeyName(chosen);
  const models = useProviderKeyModels(name, tested);

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setTested(null);
    setRefused(undefined);
    first.reset();
    second.reset();
    third.reset();
  }, [open, first, second, third]);

  const toKey = first.handleSubmit(() => setStep(2));
  const testKey = second.handleSubmit(async ({ value }) => {
    setRefused(undefined);
    const where = keyWhere(first.getValues());
    try {
      await save.mutateAsync({ name, value });
      // Cleared at once, so the key leaves the page whether or not the provider accepts it.
      second.reset({ value: '' });
      const result = await check.mutateAsync({ name, where });
      if (!result.ok) return setRefused(result.reason ?? 'The provider refused the key.');
      setTested(where);
      setStep(3);
    } catch (e) {
      setRefused((e as Error).message);
    }
  });
  const useModel = third.handleSubmit(async ({ model }) => {
    try {
      await choose.mutateAsync(chatModelBody(first.getValues(), model));
      toast.success('Chat is set up', { description: `Chat and agents answer with ${model}.` });
      onOpenChange(false);
    } catch (e) {
      third.setError('model', { message: (e as Error).message });
    }
  });

  const back = step > 1 && (
    <Button type="button" variant="outline" onClick={() => setStep(step - 1)}>
      Back
    </Button>
  );
  const footer =
    step === 1 ? (
      <Button type="submit" data-testid="model-setup-next">
        Next
      </Button>
    ) : step === 2 ? (
      <>
        {back}
        <LoadingButton type="submit" isLoading={save.isPending || check.isPending} loadingText="Testing…" data-testid="model-setup-test">
          Save and test
        </LoadingButton>
      </>
    ) : (
      <>
        {back}
        <LoadingButton type="submit" isLoading={choose.isPending} loadingText="Saving…" disabled={!models.data?.length} data-testid="model-setup-use">
          Use this model
        </LoadingButton>
      </>
    );

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title="Set up your AI model"
      description="Chat and agents answer with your own provider. The key is kept by the models service and never shown again."
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="model-setup-steps" />}
      onSubmit={step === 1 ? toKey : step === 2 ? testKey : useModel}
      footer={footer}
    >
      {step === 1 && (
        <div className="flex flex-col gap-4">
          <Controller
            control={first.control}
            name="provider"
            render={({ field }) => (
              <ChoiceCards name="model-setup-provider" label="Provider" value={field.value} onChange={(v) => field.onChange(v)} choices={SETUP_PROVIDERS.map((p) => ({ value: p.value, title: p.label, description: p.hint }))} />
            )}
          />
          {chosen === 'azure-openai' && (
            <>
              <FormField id="setup-endpoint" label="Endpoint" error={first.formState.errors.endpoint?.message} hint="The resource’s address, without /openai.">
                <Input id="setup-endpoint" {...first.register('endpoint')} placeholder="https://contoso.openai.azure.com" className="font-mono text-sm" aria-invalid={!!first.formState.errors.endpoint} />
              </FormField>
              <FormField id="setup-api-version" label="API version" hint="v1, or a dated version such as 2024-10-21.">
                <Input id="setup-api-version" {...first.register('apiVersion')} className="font-mono text-sm" />
              </FormField>
            </>
          )}
        </div>
      )}
      {step === 2 && (
        <div className="flex flex-col gap-4">
          <FormField id="setup-key" label={`${SETUP_PROVIDERS.find((p) => p.value === chosen)?.label} key`} error={second.formState.errors.value?.message} hint={`Saved as ${name} under Model providers, then tested with the provider.`}>
            <Input id="setup-key" type="password" autoComplete="off" {...second.register('value')} className="font-mono text-sm" aria-invalid={!!second.formState.errors.value} data-testid="model-setup-key" />
          </FormField>
          {refused && (
            <Alert variant="destructive" data-testid="model-setup-refused">
              <AlertDescription>{refused}</AlertDescription>
            </Alert>
          )}
        </div>
      )}
      {step === 3 && (
        <div className="flex flex-col gap-4">
          <Alert>
            <CheckCircle2 />
            <AlertDescription>The provider accepted the key.</AlertDescription>
          </Alert>
          <FormField id="setup-model" label={chosen === 'azure-openai' ? 'Deployment' : 'Chat model'} error={third.formState.errors.model?.message ?? (models.isError ? (models.error as Error).message : undefined)} hint="The one chat and agents answer with. You can change it later.">
            {models.isPending ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Controller
                control={third.control}
                name="model"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="setup-model" className="w-full font-mono text-sm" data-testid="model-setup-model">
                      <SelectValue placeholder={models.data?.length ? 'Pick a model' : 'The key lists no models'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(models.data ?? []).map((m) => (
                        <SelectItem key={m.id} value={m.id} className="font-mono">
                          {m.model && m.model !== m.id ? `${m.id} (${m.model})` : m.id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
          </FormField>
        </div>
      )}
    </DialogShell>
  );
}
