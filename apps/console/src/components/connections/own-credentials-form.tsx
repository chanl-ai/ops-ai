'use client';

import * as React from 'react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useConnectionKinds, useGiveOwn } from '@/hooks/connections-queries';

/**
 * A person's own key, password or token for an account each person signs in to: one field per person field
 * the connection's kind names, labelled as the service labels it. Nothing typed is shown back: secret fields are
 * password inputs with autocomplete off, and every field is cleared once sent.
 */
export function OwnCredentialsForm({
  connectionId,
  connection,
  authKind,
  personFields,
  docsUrl,
  submitLabel,
  cancelLabel = 'Not now',
  onDone,
  onCancel,
}: {
  connectionId: string;
  connection: string;
  authKind?: string;
  personFields: string[];
  docsUrl?: string | null;
  submitLabel: string;
  cancelLabel?: string;
  onDone?: () => void;
  onCancel?: () => void;
}) {
  const kinds = useConnectionKinds();
  const give = useGiveOwn();
  const [values, setValues] = React.useState<Record<string, string>>({});
  const kind = kinds.data?.find((k) => k.id === authKind);
  const fields = personFields.map((name) => kind?.fields?.find((f) => f.name === name) ?? { name, label: name, secret: true });
  const ready = fields.every((f) => (values[f.name] ?? '').trim());

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    try {
      await give.mutateAsync({ connectionId, credentials: values });
      onDone?.();
    } finally {
      setValues({});
    }
  };

  return (
    <form className="mt-2 flex flex-col gap-3" onSubmit={(e) => void submit(e)} data-testid="own-credentials-form" autoComplete="off">
      {fields.map((f) => (
        <div key={f.name} className="flex flex-col gap-1.5">
          <Label htmlFor={`own-${connectionId}-${f.name}`}>{f.secret && fields.length === 1 ? `Your ${kind?.label ?? f.label.toLowerCase()}` : f.label}</Label>
          <Input
            id={`own-${connectionId}-${f.name}`}
            type={f.secret ? 'password' : 'text'}
            autoComplete="off"
            value={values[f.name] ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
            data-testid={`own-field-${f.name}`}
          />
        </div>
      ))}
      {docsUrl && (
        <p className="text-sm text-muted-foreground">
          <a className="underline underline-offset-2" href={docsUrl} target="_blank" rel="noreferrer">
            Where to find it in {connection}
          </a>
        </p>
      )}
      {give.isError && (
        <p className="text-sm text-destructive-text" role="alert" data-testid="own-credentials-error">
          {give.error instanceof Error ? give.error.message : 'That did not save. Try again.'}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <LoadingButton type="submit" size="sm" isLoading={give.isPending} disabled={!ready} data-testid="own-credentials-save">
          {submitLabel}
        </LoadingButton>
        {onCancel && (
          <Button type="button" size="sm" variant="outline" onClick={onCancel} data-testid="own-credentials-cancel">
            {cancelLabel}
          </Button>
        )}
      </div>
    </form>
  );
}
