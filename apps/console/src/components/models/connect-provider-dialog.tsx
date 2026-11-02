'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ProviderConnectionInput } from '@/lib/types/models';

import { CONNECTABLE_TYPES, type ConnectableType, ENDPOINT_FIELD, PROVIDER_TYPES } from './provider-meta';

type Field = 'name' | 'baseUrl' | 'apiVersion' | 'region' | 'keyRef';
type Errors = Partial<Record<Field | 'submit', string>>;
const NO_KEY = '__none__';
// The field a models-service refusal names ("apiVersion is missing: …"), so its message shows under that field.
const NAMED: Field[] = ['baseUrl', 'apiVersion', 'region', 'keyRef', 'name'];

/**
 * Connect a model provider: the picked type decides the fields asked. Azure OpenAI asks its endpoint, API version and
 * an optional region; OpenAI-compatible its base URL. Both name a key saved under Keys (`keys`), never the key itself. The rules
 * on each value are models-service's, and its refusal shows under the field it names.
 */
export function ConnectProviderDialog({
  open,
  onOpenChange,
  keys,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The names of the account's saved model provider keys. */
  keys: string[];
  saving: boolean;
  onSave: (input: ProviderConnectionInput) => Promise<void>;
}) {
  const [type, setType] = React.useState<ConnectableType>('azure-openai');
  const [name, setName] = React.useState('');
  const [baseUrl, setBaseUrl] = React.useState('');
  const [apiVersion, setApiVersion] = React.useState('');
  const [region, setRegion] = React.useState('');
  const [keyRef, setKeyRef] = React.useState('');
  const [errors, setErrors] = React.useState<Errors>({});
  React.useEffect(() => {
    if (!open) return;
    setType('azure-openai');
    setName('');
    setBaseUrl('');
    setApiVersion('');
    setRegion('');
    setKeyRef('');
    setErrors({});
  }, [open]);
  const azure = type === 'azure-openai';
  const edit = (set: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement>) => (set(e.target.value), setErrors({}));

  const submit = async () => {
    const missing: Errors = {
      name: name.trim() ? undefined : 'Name the connection.',
      baseUrl: baseUrl.trim() ? undefined : 'Enter the endpoint.',
      apiVersion: !azure || apiVersion.trim() ? undefined : 'Enter v1 or a dated version, such as 2024-10-21.',
      keyRef: !azure || keyRef ? undefined : 'Pick the key it signs in with.',
    };
    if (Object.values(missing).some(Boolean)) return setErrors(missing);
    const key = keyRef && keyRef !== NO_KEY ? keyRef : null;
    const input: ProviderConnectionInput = { name: name.trim(), type, baseUrl: baseUrl.trim(), keyRef: key };
    try {
      await onSave(azure ? { ...input, apiVersion: apiVersion.trim(), ...(region.trim() ? { region: region.trim() } : {}) } : input);
      onOpenChange(false);
    } catch (e) {
      const message = (e as Error).message.replace(/^Value error, /, '');
      const field = NAMED.find((f) => message.startsWith(f));
      setErrors(field ? { [field]: message } : { submit: message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      onSubmit={submit}
      title="Connect a model provider"
      description="Only an account admin connects a provider. The key is saved under Keys and never shown again."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={saving} loadingText="Connecting…" data-testid="provider-connect-save">
            Connect
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="provider-type" label="Provider" hint="Each type asks only for what it needs.">
          <Select value={type} onValueChange={(v) => (setType(v as ConnectableType), setErrors({}))}>
            <SelectTrigger id="provider-type" className="w-full" data-testid="provider-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CONNECTABLE_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {PROVIDER_TYPES[t].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="provider-name" label="Name" error={errors.name} hint="How aliases and the request log name it.">
          <Input id="provider-name" value={name} aria-invalid={!!errors.name} onChange={edit(setName)} placeholder="e.g. claims-azure" />
        </FormField>
        <FormField id="provider-endpoint" label="Endpoint" error={errors.baseUrl} hint={ENDPOINT_FIELD[type].hint}>
          <Input id="provider-endpoint" value={baseUrl} aria-invalid={!!errors.baseUrl} onChange={edit(setBaseUrl)} placeholder={ENDPOINT_FIELD[type].placeholder} className="font-mono text-sm" />
        </FormField>
        {azure && (
          <>
            <FormField id="provider-api-version" label="API version" error={errors.apiVersion} hint="v1 for Azure’s v1 API, or a dated version from 2024-10-21 on.">
              <Input id="provider-api-version" value={apiVersion} aria-invalid={!!errors.apiVersion} onChange={edit(setApiVersion)} placeholder="e.g. 2024-10-21" className="font-mono text-sm" />
            </FormField>
            <FormField id="provider-region" label="Region" optional error={errors.region} hint="Where the resource runs. A call answered from another region is flagged on the connection and in the call log.">
              <Input id="provider-region" value={region} aria-invalid={!!errors.region} onChange={edit(setRegion)} placeholder="e.g. swedencentral" />
            </FormField>
          </>
        )}
        <FormField
          id="provider-key"
          label="Key"
          error={errors.keyRef}
          hint={keys.length ? (azure ? 'The saved key it signs in with. The alias’s model is the deployment name.' : 'Sent as a bearer token.') : 'No key saved yet: add one under Keys first.'}
        >
          <Select value={keyRef} onValueChange={(v) => (setKeyRef(v), setErrors({}))}>
            <SelectTrigger id="provider-key" className="w-full font-mono text-sm" aria-invalid={!!errors.keyRef} data-testid="provider-key-ref">
              <SelectValue placeholder="Pick a saved key" />
            </SelectTrigger>
            <SelectContent>
              {!azure && <SelectItem value={NO_KEY}>None (the endpoint takes no key)</SelectItem>}
              {keys.map((k) => (
                <SelectItem key={k} value={k} className="font-mono">
                  {k}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {azure && (
          <Alert>
            <AlertDescription>Global and Data Zone deployments may process a request outside this region. Use a Standard (regional) deployment to keep data in it.</AlertDescription>
          </Alert>
        )}
        {errors.submit && <p className="text-sm text-destructive">{errors.submit}</p>}
      </div>
    </DialogShell>
  );
}
