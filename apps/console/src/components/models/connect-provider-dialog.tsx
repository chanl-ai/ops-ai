'use client';

import * as React from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ModelProvider, ProviderHealth, ProviderInput, ProviderType } from '@/lib/types/models';

import { PROVIDER_TYPE_ORDER, PROVIDER_TYPES } from './provider-meta';

type Errors = Partial<Record<'name' | 'baseUrl' | 'keySecret' | 'key' | 'submit', string>>;

/** A test's outcome as one line: what the provider answered, never the key. */
export function TestResult({ health }: { health: ProviderHealth }) {
  if (health.status === 'untested') return null;
  return health.status === 'ok' ? (
    <p className="flex items-center gap-1.5 text-sm text-success-text" data-testid="provider-test-ok">
      <CheckCircle2 className="size-4" /> Connected in {health.latencyMs} ms; the key can call {health.models} models.
    </p>
  ) : (
    <p className="flex items-center gap-1.5 text-sm text-destructive" data-testid="provider-test-failed">
      <XCircle className="size-4" /> The provider refused: {health.error}
    </p>
  );
}

/**
 * Connect a model provider, or change the key of one (`provider`). The key is saved as a workspace secret under
 * `keySecret` and never shown again; Test calls the provider's model list with it before anything is saved.
 */
export function ConnectProviderDialog({
  open,
  onOpenChange,
  provider,
  onTest,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  provider?: ModelProvider | null;
  onTest: (input: ProviderInput) => Promise<ProviderHealth>;
  onSave: (input: ProviderInput) => Promise<void>;
}) {
  const changing = !!provider;
  const [type, setType] = React.useState<ProviderType>('openai');
  const [name, setName] = React.useState('');
  const [baseUrl, setBaseUrl] = React.useState(PROVIDER_TYPES.openai.baseUrl);
  const [keySecret, setKeySecret] = React.useState(PROVIDER_TYPES.openai.secret);
  const [key, setKey] = React.useState('');
  const [errors, setErrors] = React.useState<Errors>({});
  const [tested, setTested] = React.useState<ProviderHealth | null>(null);
  const [testing, setTesting] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => {
    if (!open) return;
    const t = provider?.type ?? 'openai';
    setType(t);
    setName(provider?.name ?? PROVIDER_TYPES[t].label);
    setBaseUrl(provider?.baseUrl ?? PROVIDER_TYPES[t].baseUrl);
    setKeySecret(provider?.keySecret ?? PROVIDER_TYPES[t].secret);
    setKey('');
    setErrors({});
    setTested(null);
  }, [open, provider]);

  const pickType = (t: ProviderType) => {
    setType(t);
    setName(PROVIDER_TYPES[t].label);
    setBaseUrl(PROVIDER_TYPES[t].baseUrl);
    setKeySecret(PROVIDER_TYPES[t].secret);
    setTested(null);
  };
  const input = (): ProviderInput | null => {
    const e: Errors = {
      name: name.trim() ? undefined : 'Name the provider.',
      baseUrl: /^https?:\/\/[^<>\s]+$/.test(baseUrl) ? undefined : 'Enter the endpoint, starting https://.',
      keySecret: /^[A-Z][A-Z0-9_]*$/.test(keySecret) ? undefined : 'Upper case letters, digits and underscores, starting with a letter.',
      key: key || (changing && provider?.keySet) ? undefined : 'Paste the API key.',
    };
    setErrors(e);
    return e.name || e.baseUrl || e.keySecret || e.key ? null : { name: name.trim(), type, baseUrl, keySecret, ...(key ? { key } : {}) };
  };
  const test = async () => {
    const i = input();
    if (!i) return;
    setTesting(true);
    try {
      setTested(await onTest(i));
    } finally {
      setTesting(false);
    }
  };
  const save = async () => {
    const i = input();
    if (!i) return;
    setSaving(true);
    try {
      await onSave(i);
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      onSubmit={save}
      title={changing ? `Change the key of ${provider?.name}` : 'Connect a model provider'}
      description="The key is saved as a workspace secret, encrypted, and never shown again. Every call that uses it is audited."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="button" variant="outline" isLoading={testing} loadingText="Testing…" onClick={test} data-testid="provider-test">
            Test connection
          </LoadingButton>
          <LoadingButton type="submit" isLoading={saving} loadingText="Saving…" data-testid="provider-save">
            {changing ? 'Save key' : 'Connect'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!changing && (
          <>
            <FormField id="provider-type" label="Provider">
              <Select value={type} onValueChange={(v) => pickType(v as ProviderType)}>
                <SelectTrigger id="provider-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPE_ORDER.map((t) => (
                    <SelectItem key={t} value={t}>
                      {PROVIDER_TYPES[t].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="provider-name" label="Name" error={errors.name} hint="How aliases and the request log name it.">
              <Input id="provider-name" value={name} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value), setErrors({}))} />
            </FormField>
            <FormField id="provider-endpoint" label="Endpoint" error={errors.baseUrl}>
              <Input id="provider-endpoint" value={baseUrl} aria-invalid={!!errors.baseUrl} onChange={(e) => (setBaseUrl(e.target.value), setTested(null), setErrors({}))} className="font-mono text-sm" />
            </FormField>
          </>
        )}
        <FormField id="provider-key" label={changing ? 'New API key' : 'API key'} error={errors.key ?? errors.submit} hint={PROVIDER_TYPES[type].keyHint}>
          <Input id="provider-key" type="password" value={key} aria-invalid={!!(errors.key ?? errors.submit)} onChange={(e) => (setKey(e.target.value), setTested(null), setErrors({}))} autoComplete="new-password" data-testid="provider-key" />
        </FormField>
        <FormField id="provider-secret" label="Saved as" error={errors.keySecret} hint="The workspace secret that holds the key. Security admins see it on the Secrets page.">
          <Input id="provider-secret" value={keySecret} disabled={changing} aria-invalid={!!errors.keySecret} onChange={(e) => (setKeySecret(e.target.value.toUpperCase()), setErrors({}))} className="font-mono text-sm" autoComplete="off" />
        </FormField>
        {tested && <TestResult health={tested} />}
      </div>
    </DialogShell>
  );
}
