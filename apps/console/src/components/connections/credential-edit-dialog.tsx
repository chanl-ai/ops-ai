'use client';

import * as React from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

import { CallbackUrl } from '@/components/connections/callback-url';
import { secretShown } from '@/components/connections/credential-display';
import { SignInPlace } from '@/components/connections/sign-in-place';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormTextField } from '@/components/shared/form-text-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Form } from '@/components/ui/form';
import { Skeleton } from '@/components/ui/skeleton';
import { type AppCredentialChange, useAppCredential, useChangeAppCredential, useSetCredentialSecret, useSystems } from '@/hooks/systems-queries';
import { configSchema } from '@/lib/field-schema';
import { plural } from '@/lib/format';

type Change = NonNullable<AppCredentialChange>;
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Edit an app credential: every part of the team's own app in one window, as its page holds them: its name, client
 * ID, the permissions it asks for, the settings its app registration keeps (a tenant, a custom app's addresses) and
 * its client secret, left blank to keep the one it holds. A change to the client ID, permissions or settings says
 * first how many accounts must sign in again, and the answer marks them so.
 */
export function CredentialEditDialog({ credentialId, onClose }: { credentialId: string | null; onClose: () => void }) {
  return credentialId ? <EditForm id={credentialId} onClose={onClose} /> : null;
}

function EditForm({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useAppCredential(id);
  const systems = useSystems();
  const change = useChangeAppCredential();
  const setSecret = useSetCredentialSecret();
  const c = q.data;
  const plugin = (systems.data ?? []).find((s) => s.id === c?.app)?.plugin;
  const form = useForm<Record<string, string>>();
  const [scopes, setScopes] = React.useState<string[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!c) return;
    form.reset({ name: c.name, clientId: c.clientId ?? '', scopesText: c.permissions.map((p) => p.id).join(' '), clientSecret: '', ...Object.fromEntries((c.fields ?? []).map((f) => [`setting__${f.name}`, String((c.settings ?? {})[f.name] ?? f.default ?? '')])) });
    setScopes(c.permissions.map((p) => p.id));
  }, [c, form]);

  const picked = (v: Record<string, string>) => (plugin ? (scopes ?? []) : (v.scopesText ?? '').split(/\s+/).filter(Boolean));
  const changes = (v: Record<string, string>): Change => {
    if (!c) return {};
    const body: Change = {};
    if ((v.name ?? '').trim() && v.name.trim() !== c.name) body.name = v.name.trim();
    if ((v.clientId ?? '').trim() && v.clientId.trim() !== c.clientId) body.clientId = v.clientId.trim();
    const now = picked(v);
    const held = c.permissions.map((p) => p.id);
    if (now.join(' ') !== held.join(' ')) body.scopes = now;
    const settings = Object.fromEntries((c.fields ?? []).map((f) => [f.name, (v[`setting__${f.name}`] ?? '').trim()]).filter(([k, val]) => val !== String((c.settings ?? {})[k] ?? (c.fields ?? []).find((f) => f.name === k)?.default ?? '')));
    if (Object.keys(settings).length) body.settings = settings;
    return body;
  };
  const values = form.watch();
  const pending = changes(values);
  const resigns = c && (pending.clientId !== undefined || pending.scopes !== undefined || pending.settings !== undefined) ? c.accounts : 0;

  const save = async () => {
    if (!c) return;
    setError(null);
    const v = form.getValues();
    if (plugin && !(scopes ?? []).length) {
      setError(`Pick at least one permission for ${c.appName} to ask for.`);
      return;
    }
    const checked = configSchema(c.fields ?? []).safeParse(Object.fromEntries((c.fields ?? []).map((f) => [f.name, v[`setting__${f.name}`] ?? ''])));
    if (!checked.success) {
      setError(checked.error.issues[0]?.message ?? 'Check the settings.');
      return;
    }
    try {
      let again = 0;
      if (Object.keys(changes(v)).length) again = (await change.mutateAsync({ id: c.id, body: changes(v) })).signInAgain;
      if ((v.clientSecret ?? '').trim()) await setSecret.mutateAsync({ path: { credential_id: c.id }, body: { clientSecret: v.clientSecret.trim() } });
      toast.success(`Saved ${v.name?.trim() || c.name}`, { description: again ? `${plural(again, 'account')} must sign in again.` : undefined });
      onClose();
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="md"
      title={c ? `Edit ${c.name}` : 'Edit auth config'}
      description={c ? `Your own ${c.appName} app, as you registered it with ${c.appName}.` : undefined}
      data-testid="credential-edit"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton isLoading={change.isPending || setSecret.isPending} disabled={!c} onClick={() => void save()} data-testid="credential-edit-save">
            Save
          </LoadingButton>
        </>
      }
    >
      {q.isError ? (
        <QueryError what="this auth config" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : !c ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <Form {...form}>
          <div className="flex min-w-0 flex-col gap-4">
            <FormTextField control={form.control} name="name" label="Name" testId="credential-edit-name" />
            <FormTextField control={form.control} name="clientId" label="Client ID" testId="credential-edit-client-id" />
            <FormTextField
              control={form.control}
              name="clientSecret"
              label="Client secret"
              type="password"
              optional
              hint={`${secretShown(c)}. Leave blank to keep it.`}
              testId="credential-edit-client-secret"
            />
            <CallbackUrl app={c.appName} id="credential-edit-return" testId="credential-edit-callback" />
            {plugin ? (
              <fieldset className="flex flex-col gap-2" data-testid="credential-edit-scopes">
                <legend className="mb-1 text-sm font-medium">Permissions it asks for</legend>
                {plugin.scopes.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={s.required || (scopes ?? []).includes(s.id)}
                      disabled={s.required}
                      onCheckedChange={(on) => setScopes((cur) => (on ? [...(cur ?? []), s.id] : (cur ?? []).filter((x) => x !== s.id)))}
                      data-testid={`credential-edit-scope-${s.id}`}
                    />
                    {s.label}
                    {s.required && <span className="text-xs text-muted-foreground">Always asked for</span>}
                  </label>
                ))}
              </fieldset>
            ) : (
              <FormTextField control={form.control} name="scopesText" label="Permissions it asks for" optional hint="Separated by spaces, as the app names them." testId="credential-edit-scopes-text" />
            )}
            {(c.fields ?? []).map((f) =>
              f.choices?.length || f.other ? (
                <SignInPlace
                  key={f.name}
                  setting={f}
                  value={values[`setting__${f.name}`] ?? ''}
                  onChange={(v) => form.setValue(`setting__${f.name}`, v)}
                  testId={`credential-edit-setting-${f.name}`}
                />
              ) : (
              <FormTextField key={f.name} control={form.control} name={`setting__${f.name}`} label={f.label} optional hint={f.help ?? undefined} multiline={f.pem} testId={`credential-edit-setting-${f.name}`} />
              ),
            )}
            {resigns > 0 && (
              <Alert data-testid="credential-edit-resign">
                <AlertDescription>{`${plural(resigns, 'account')} signing in with it must sign in again after this change.`}</AlertDescription>
              </Alert>
            )}
            {error && (
              <p className="text-sm text-destructive-text" role="alert" data-testid="credential-edit-error">
                {error}
              </p>
            )}
          </div>
        </Form>
      )}
    </DialogShell>
  );
}
