'use client';

import * as React from 'react';
import Link from 'next/link';
import { CheckCircle2, Plug } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SearchSelect } from '@/components/shared/search-select';
import { SchemaForm, type Schema } from '@/components/shared/schema-form';
import { Stepper } from '@/components/shared/stepper';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { providerTypeOptions } from '@/hooks/options-queries';
import { useProviderTypes } from '@/hooks/model-queries';
import { useCreateProviderConnection } from '@/hooks/provider-connection-queries';
import { useCheckProviderKey } from '@/hooks/provider-key-queries';
import { connectionBody, connectionDefaults, connectionProblems, keyWhere } from '@/lib/model-forms';
import type { KeyCheck } from '@/lib/types/provider-keys';
import type { ProviderConnection, ProviderConnectionInput, ProviderTypeInfo } from '@/lib/types/models';
import { QueryError } from '@/components/shared/query-states';

const STEPS = ['Provider', 'Details', 'Test'] as const;
// The field a models-service refusal names ("apiVersion is missing: …"), so its message shows under that field.
const NAMED = ['baseUrl', 'apiVersion', 'region', 'keyRef', 'name'];

/**
 * Connect a model provider in three steps: pick the provider from the registry models-service serves (searched, with
 * the endpoint-only types last), fill the form its JSON Schema describes, then see the provider's answer to the saved
 * key. A key is saved with the connection and tested after it, because the test reads the sealed key; a refused key
 * is shown with its reason and tested again after the key is replaced on this page. No provider is named here.
 */
export function ConnectProviderDialog({ open, onOpenChange, onConnected }: { open: boolean; onOpenChange: (open: boolean) => void; onConnected?: (row: ProviderConnection) => void }) {
  const types = useProviderTypes(open);
  const create = useCreateProviderConnection();
  const check = useCheckProviderKey();
  const [step, setStep] = React.useState(1);
  const [type, setType] = React.useState<ProviderTypeInfo>();
  const [name, setName] = React.useState('');
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [made, setMade] = React.useState<{ body: ProviderConnectionInput; result?: KeyCheck; failure?: string }>();

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setType(undefined);
    setName('');
    setValues({});
    setErrors({});
    setMade(undefined);
  }, [open]);

  const pick = (t: ProviderTypeInfo) => {
    setType(t);
    setValues(connectionDefaults(t));
    setName('');
    setErrors({});
    setStep(2);
  };

  const test = async (body: ProviderConnectionInput) => {
    if (!body.keyRef) return setMade({ body });
    try {
      const result = await check.mutateAsync({ name: body.keyRef, where: keyWhere(body.type, body) });
      setMade({ body, result });
    } catch (e) {
      setMade({ body, failure: (e as Error).message });
    }
  };

  const connect = async () => {
    if (!type) return;
    const found = connectionProblems(type, name, values);
    if (Object.keys(found).length) return setErrors(found);
    const body = connectionBody(type, name, values);
    try {
      const saved = await create.mutateAsync(body);
      onConnected?.({ id: saved.id, name: body.name, type: body.type, baseUrl: body.baseUrl ?? null, keyRef: body.keyRef ?? null, apiVersion: body.apiVersion ?? null, region: body.region ?? null, observedRegion: null, regionMismatch: null });
      setStep(3);
      await test(body);
    } catch (e) {
      const message = (e as Error).message.replace(/^Value error, /, '');
      const field = NAMED.find((f) => message.startsWith(f));
      setErrors({ [field ?? 'submit']: message });
    }
  };

  const footer =
    step === 1 ? (
      <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
        Cancel
      </Button>
    ) : step === 2 ? (
      <>
        <Button type="button" variant="outline" onClick={() => setStep(1)}>
          Back
        </Button>
        <LoadingButton type="submit" isLoading={create.isPending} loadingText="Connecting…" data-testid="provider-connect-save">
          Connect
        </LoadingButton>
      </>
    ) : (
      <>
        {made?.body.keyRef && (
          <Button type="button" variant="outline" disabled={check.isPending} onClick={() => made && test(made.body)} data-testid="provider-connect-test-again">
            <Plug /> Test again
          </Button>
        )}
        <Button type="button" variant="outline" asChild>
          <Link href="/settings/workspace/model-aliases" onClick={() => onOpenChange(false)}>
            Make alias
          </Link>
        </Button>
        <Button type="button" onClick={() => onOpenChange(false)} data-testid="provider-connect-done">
          Done
        </Button>
      </>
    );

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={step === 1 || !type ? 'Connect a model provider' : `Connect ${type.label}`}
      description="Only an account admin connects a provider. A key is kept by the models service and never shown again."
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="provider-connect-steps" />}
      onSubmit={step === 2 ? connect : undefined}
      footer={footer}
    >
      {step === 1 && (types.isPending ? <Skeleton className="h-40 w-full" /> : types.isError ? <QueryError what="model providers" onRetry={() => types.refetch()} retrying={types.isFetching} error={types.error} testId="provider-types-error" /> : <ProviderPicker types={types.data ?? []} onPick={pick} />)}
      {step === 2 && type && (
        <div className="flex flex-col gap-4">
          <FormField id="pc-name" label="Name" error={errors.name} hint="How aliases and the call log name this connection.">
            <Input id="pc-name" value={name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. anthropic-main" aria-invalid={!!errors.name} data-testid="provider-connect-name" />
          </FormField>
          <SchemaForm
            schema={type.connection as Schema}
            value={values}
            idPrefix="pc"
            errors={errors}
            testIds={Object.fromEntries(Object.keys(type.connection.properties ?? {}).map((k) => [k, `provider-connect-${k}`]))}
            onChange={(v) => (setValues(v), setErrors({}))}
            testId="provider-connect-form"
          />
          {errors.submit && (
            <Alert variant="destructive" data-testid="provider-connect-error">
              <AlertDescription>{errors.submit}</AlertDescription>
            </Alert>
          )}
        </div>
      )}
      {step === 3 && <TestResult label={type?.label ?? ''} made={made} testing={check.isPending || !made} />}
    </DialogShell>
  );
}

/** Searchable list of the registry's types; with no match it says which type takes any endpoint. */
function ProviderPicker({ types, onPick }: { types: ProviderTypeInfo[]; onPick: (t: ProviderTypeInfo) => void }) {
  const endpoint = types.find((t) => !t.catalogued);
  return (
    <div className="flex flex-col gap-2" data-testid="provider-picker">
      <FormField id="pc-provider" label="Provider" hint="Pick one. Each asks only for what it needs.">
        <SearchSelect
          id="pc-provider"
          source={providerTypeOptions}
          value={null}
          onChange={(_id, o) => o && onPick(o.type)}
          placeholder="Search providers…"
          searchPlaceholder="Search providers…"
          emptyText={endpoint ? `No built-in provider is called that. ${endpoint.label} works for most others.` : 'No provider is called that.'}
          testId="provider-search"
        />
      </FormField>
    </div>
  );
}

function TestResult({ label, made, testing }: { label: string; made?: { body: ProviderConnectionInput; result?: KeyCheck; failure?: string }; testing: boolean }) {
  if (testing) return <Skeleton className="h-16 w-full" data-testid="provider-connect-testing" />;
  if (!made?.body.keyRef)
    return (
      <Alert data-testid="provider-connect-untested">
        <CheckCircle2 />
        <AlertTitle>Connected</AlertTitle>
        <AlertDescription>This connection takes no key, so there is nothing to test. Make an alias to use it.</AlertDescription>
      </Alert>
    );
  if (made.failure || !made.result?.ok)
    return (
      <Alert variant="destructive" data-testid="provider-connect-refused">
        <AlertTitle>{label || 'The provider'} did not accept the key</AlertTitle>
        <AlertDescription>{made.failure ?? made.result?.reason ?? 'The provider refused the key.'} The connection is saved; replace its key under Keys, then test again.</AlertDescription>
      </Alert>
    );
  return (
    <Alert data-testid="provider-connect-passed">
      <CheckCircle2 />
      <AlertTitle>Key accepted</AlertTitle>
      <AlertDescription>The provider answered. This key reaches {made.result.models} {made.result.models === 1 ? 'model' : 'models'}; make an alias for each one builders may pick.</AlertDescription>
    </Alert>
  );
}
