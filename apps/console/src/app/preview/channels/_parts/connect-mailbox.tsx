'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Stepper } from '@/components/shared/stepper';
import { Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { PROVIDERS, blankMailbox, type MailProvider, type MailboxSettings } from '../_sample/data';
import { channelsStore } from '../_sample/store';
import { useSecretAdder } from './add-secret';
import { MailboxFields, checkMailbox, type MailboxErrors, type SecretTarget } from './mailbox-fields';

const STEPS = ['Provider', 'Settings'] as const;

/**
 * Connect a mailbox: pick the provider, then its settings. One form in two shells: `page` on the email channel's
 * Connect page, `dialog` wherever a mailbox is needed in place (the trigger sheet's "Connect a mailbox").
 */
export function ConnectMailbox({ shell, open = false, onOpenChange, onConnected }: { shell: 'page' | 'dialog'; open?: boolean; onOpenChange?: (o: boolean) => void; onConnected: (id: string) => void }) {
  const [step, setStep] = React.useState(1);
  const [provider, setProvider] = React.useState<MailProvider>('gmail');
  const [name, setName] = React.useState('');
  const [settings, setSettings] = React.useState<MailboxSettings>(() => blankMailbox('gmail'));
  const [errors, setErrors] = React.useState<MailboxErrors>({});
  const reset = React.useCallback(() => {
    setStep(1);
    setProvider('gmail');
    setName('');
    setSettings(blankMailbox('gmail'));
    setErrors({});
  }, []);
  React.useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  const patch = (p: Partial<MailboxSettings>) => {
    setSettings((s) => {
      const next = { ...s, ...p };
      // Gmail signs in and sends with the address, so the user name and the from address follow it until changed.
      if (p.address !== undefined && s.provider === 'gmail' && (s.username === s.address || !s.username)) next.username = p.address;
      if (p.address !== undefined && (s.fromAddress === s.address || !s.fromAddress)) next.fromAddress = p.address;
      return next;
    });
    setErrors({});
  };
  const onAdded = React.useCallback((target: SecretTarget, secret: string) => patch({ [target]: secret }), []);
  const adder = useSecretAdder(onAdded);

  const next = () => {
    setSettings((s) => ({ ...blankMailbox(provider), address: s.address, fromAddress: s.fromAddress, username: s.username }));
    setStep(2);
  };
  const connect = () => {
    const e = checkMailbox(settings);
    if (!name.trim()) e.name = 'Name it so the team can tell mailboxes apart.';
    setErrors(e);
    if (Object.keys(e).length) return;
    const id = channelsStore.connectMailbox(name.trim(), settings);
    toast.success(`Connected ${settings.address}`, { description: 'Design mock: nothing was stored.' });
    onOpenChange?.(false);
    onConnected(id);
    if (shell === 'page') reset();
  };
  const submit = step === 1 ? next : connect;

  const body = (
    <div className="flex min-w-0 flex-col gap-5">
      <Stepper steps={STEPS} current={step} testId="connect-mailbox-steps" />
      {step === 1 ? (
        <ChoiceCards name="connect-provider" label="Mail provider" choices={PROVIDERS} value={provider} onChange={(v) => setProvider(v as MailProvider)} />
      ) : (
        <>
          <FormField id="connect-name" label="Name" error={errors.name} hint="Shown in the trigger’s mailbox picker.">
            <Input id="connect-name" value={name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. Levy notices" className="bg-card sm:w-1/2" autoComplete="off" aria-invalid={!!errors.name} />
          </FormField>
          <MailboxFields value={settings} onChange={patch} errors={errors} onAddSecret={adder.start} idPrefix="connect" />
        </>
      )}
    </div>
  );
  const footer = (
    <>
      {step === 1 ? (
        <Button type="button" variant="outline" onClick={() => (shell === 'dialog' ? onOpenChange?.(false) : reset())}>
          Cancel
        </Button>
      ) : (
        <Button type="button" variant="outline" onClick={() => setStep(1)}>
          Back
        </Button>
      )}
      <Button type="submit" data-testid="connect-mailbox-submit">
        {step === 1 ? 'Next' : 'Connect mailbox'}
      </Button>
    </>
  );

  if (shell === 'dialog')
    return (
      <>
        <DialogShell open={open} onOpenChange={(o) => onOpenChange?.(o)} size="lg" title="Connect a mailbox" description="New mail in the folder you pick starts the workflows that watch it." onSubmit={submit} footer={footer} bodyClassName="min-h-96">
          {body}
        </DialogShell>
        {adder.dialog}
      </>
    );
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Section title="Connect a mailbox" description="New mail in the folder you pick starts the workflows that watch it.">
          {body}
          <div className="mt-6 flex justify-end gap-2 border-t pt-4">{footer}</div>
        </Section>
      </form>
      {adder.dialog}
    </>
  );
}
