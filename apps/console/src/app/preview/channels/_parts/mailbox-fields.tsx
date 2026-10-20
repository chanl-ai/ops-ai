'use client';

import * as React from 'react';
import { CheckCircle2, KeyRound, Plug, XCircle } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Combobox } from '@/components/shared/setting/pickers';
import { StepList } from '@/components/shared/step-list';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { usePreviewStore } from '@/lib/settings-preview-store';

import { FOLDERS, PROVIDER_LABEL, SENDERS, type MailboxSettings } from '../_sample/data';
import { channelsStore, type TestResult, type TestStep } from '../_sample/store';

export type MailboxErrors = Partial<Record<'name' | 'address' | 'host' | 'tenantId' | 'clientId' | 'secret' | 'fromAddress' | 'smtpHost' | 'senderSecret', string>>;
/** Which secret field an Add secret was opened for, so the new secret fills that field. */
export type SecretTarget = 'secret' | 'senderSecret';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The checks Connect and Save run before anything is sent. */
export function checkMailbox(v: MailboxSettings): MailboxErrors {
  const e: MailboxErrors = {};
  if (!EMAIL.test(v.address)) e.address = 'Enter the mailbox’s address.';
  if (v.provider === 'imap' && !v.host.trim()) e.host = 'Enter the IMAP server.';
  if (v.provider === 'graph' && !v.tenantId.trim()) e.tenantId = 'Enter the directory (tenant) ID.';
  if (v.provider === 'graph' && !v.clientId.trim()) e.clientId = 'Enter the application (client) ID.';
  if (!v.secret) e.secret = 'Pick the secret that holds it, or add one.';
  if (!EMAIL.test(v.fromAddress)) e.fromAddress = 'Enter the address replies come from.';
  if (v.sender === 'smtp' && !v.smtpHost.trim()) e.smtpHost = 'Enter the SMTP server.';
  if (v.sender !== 'graph' && !v.senderSecret) e.senderSecret = 'Pick the secret that holds it, or add one.';
  return e;
}

/** A secret named by reference: pick one from the Secrets list or add one; the value is never typed here. */
function SecretPicker({ id, value, onChange, onAdd }: { id: string; value: string | null; onChange: (name: string) => void; onAdd: () => void }) {
  const secrets = usePreviewStore((s) => s.secrets);
  const options = secrets.map((s) => ({ value: s.name, label: s.name, hint: s.teams.length ? s.teams.join(', ') : 'Every team' }));
  return (
    <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
      <div className="min-w-0 flex-1">
        <Combobox id={id} options={options} value={value} onChange={onChange} noun="secrets" placeholder="Choose a secret" />
      </div>
      <Button type="button" variant="outline" onClick={onAdd} data-testid={`${id}-add`}>
        <KeyRound className="size-4" /> Add secret
      </Button>
    </div>
  );
}

/** Test connection and its result: the steps as they run, then what the newest message was or why sign-in failed. */
function TestConnection({ value }: { value: MailboxSettings }) {
  const [steps, setSteps] = React.useState<TestStep[] | null>(null);
  const [result, setResult] = React.useState<TestResult | null>(null);
  const [running, setRunning] = React.useState(false);
  const run = async () => {
    setRunning(true);
    setResult(null);
    const r = await channelsStore.test(value, setSteps);
    setResult(r);
    setRunning(false);
  };
  return (
    <div className="flex flex-col gap-3" data-testid="mailbox-test">
      <div className="flex flex-wrap items-center gap-3">
        <LoadingButton type="button" variant="outline" onClick={run} isLoading={running} loadingText="Testing…" data-testid="mailbox-test-run">
          <Plug className="size-4" /> Test connection
        </LoadingButton>
        <span className="text-xs text-muted-foreground">Signs in and reads the folder without marking anything read.</span>
      </div>
      {steps && <StepList title="Connection test" steps={steps} />}
      {result && (
        <Alert variant={result.ok ? 'default' : 'destructive'} data-testid="mailbox-test-result" data-ok={result.ok}>
          {result.ok ? <CheckCircle2 className="text-success-text" /> : <XCircle />}
          <AlertTitle>{result.ok ? 'Connected' : 'Sign-in failed'}</AlertTitle>
          <AlertDescription>{result.message}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/**
 * A mailbox's settings: how it signs in, the folder it watches, a test, and the sender replies go out through. One
 * component for the connect dialog, the connect page and the mailbox's settings drawer.
 */
export function MailboxFields({ value, onChange, errors, onAddSecret, idPrefix }: { value: MailboxSettings; onChange: (patch: Partial<MailboxSettings>) => void; errors: MailboxErrors; onAddSecret: (target: SecretTarget) => void; idPrefix: string }) {
  const id = (f: string) => `${idPrefix}-${f}`;
  const text = (field: keyof MailboxSettings & keyof MailboxErrors, label: string, placeholder: string, hint?: string) => (
    <FormField id={id(field)} label={label} hint={hint} error={errors[field]}>
      <Input id={id(field)} value={value[field] as string} onChange={(e) => onChange({ [field]: e.target.value })} placeholder={placeholder} className="bg-card" autoComplete="off" aria-invalid={!!errors[field]} />
    </FormField>
  );
  const secretLabel = value.provider === 'graph' ? 'Client secret' : value.provider === 'gmail' ? 'App password' : 'Password';
  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid="mailbox-fields">
      <section className="flex flex-col gap-4" aria-labelledby={id('signin')}>
        <h3 id={id('signin')} className="text-sm font-semibold">
          Sign-in · {PROVIDER_LABEL[value.provider]}
        </h3>
        {text('address', 'Mailbox address', value.provider === 'gmail' ? 'e.g. intake.test@gmail.com' : 'e.g. intake@bank.example')}
        {value.provider === 'imap' && (
          <div className="grid gap-4 sm:grid-cols-2">
            {text('host', 'IMAP server', 'e.g. mail.bank.example', 'Over TLS on port 993. The server must be an allowed host.')}
            <FormField id={id('username')} label="User name" optional hint="Leave empty to sign in with the address.">
              <Input id={id('username')} value={value.username} onChange={(e) => onChange({ username: e.target.value })} placeholder="e.g. intake" className="bg-card" autoComplete="off" />
            </FormField>
          </div>
        )}
        {value.provider === 'graph' && (
          <div className="grid gap-4 sm:grid-cols-2">
            {text('tenantId', 'Directory (tenant) ID', 'e.g. 00000000-0000-0000-0000-000000000000')}
            {text('clientId', 'Application (client) ID', 'e.g. 00000000-0000-0000-0000-000000000000')}
          </div>
        )}
        <FormField
          id={id('secret')}
          label={secretLabel}
          error={errors.secret}
          hint={value.provider === 'gmail' ? 'A Google app password kept in Secrets. It is read only when the mailbox is read.' : 'A secret on the Secrets page. It is read only when the mailbox is read.'}
        >
          <SecretPicker id={id('secret')} value={value.secret} onChange={(secret) => onChange({ secret })} onAdd={() => onAddSecret('secret')} />
        </FormField>
        <FormField id={id('folder')} label="Folder" hint="New mail here starts runs. Mail already in it when a workflow goes live starts nothing.">
          <div className="w-full sm:w-1/2">
            <Combobox id={id('folder')} options={FOLDERS.map((f) => ({ value: f, label: f }))} value={value.folder} onChange={(folder) => onChange({ folder })} noun="folders" />
          </div>
        </FormField>
        <TestConnection value={value} />
      </section>
      <Separator />
      <section className="flex flex-col gap-4" aria-labelledby={id('replies')}>
        <h3 id={id('replies')} className="text-sm font-semibold">
          Replies
        </h3>
        <ChoiceCards name={id('sender')} label="Send replies with" choices={SENDERS} value={value.sender} onChange={(s) => onChange({ sender: s as MailboxSettings['sender'] })} />
        {text('fromAddress', 'From address', 'e.g. intake@bank.example')}
        {value.sender === 'smtp' && text('smtpHost', 'SMTP server', 'e.g. smtp.bank.example:587')}
        {value.sender !== 'graph' ? (
          <FormField id={id('senderSecret')} label={value.sender === 'resend' ? 'API key' : 'SMTP password'} error={errors.senderSecret} hint="A secret on the Secrets page, read only when a reply is sent.">
            <SecretPicker id={id('senderSecret')} value={value.senderSecret} onChange={(senderSecret) => onChange({ senderSecret })} onAdd={() => onAddSecret('senderSecret')} />
          </FormField>
        ) : (
          <p className="text-sm text-muted-foreground">
            {value.provider === 'graph' ? 'Sends as the from address through Microsoft 365, with the app registration above.' : 'Sends as the from address through the workspace’s Microsoft 365 app registration.'}
          </p>
        )}
      </section>
    </div>
  );
}
