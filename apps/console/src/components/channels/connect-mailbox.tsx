'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Stepper } from '@/components/shared/stepper';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { LoadingButton } from '@/components/shared/loading-button';
import { useConnectMailbox } from '@/hooks/channels-queries';
import type { Mailbox, MailProvider } from '@/lib/types/channels';

import { MailboxFields, PROVIDERS, blankForm, checkMailbox, toInput, type MailboxErrors, type MailboxForm } from './mailbox-fields';

const STEPS = ['Provider', 'Settings'] as const;
const PICKABLE = PROVIDERS.filter((p) => !p.disabled).map((p) => ({ value: p.value, title: p.title, description: p.description }));

/**
 * Connect a mailbox: pick the provider, then its settings and a test. One form in two shells: `page` on Channels >
 * Email > Connect, `dialog` where a mailbox is needed in place (the Email received trigger's sheet).
 */
export function ConnectMailbox({ shell, open = false, onOpenChange, onConnected }: { shell: 'page' | 'dialog'; open?: boolean; onOpenChange?: (o: boolean) => void; onConnected: (m: Mailbox) => void }) {
  const connect = useConnectMailbox();
  const [step, setStep] = React.useState(1);
  const [form, setForm] = React.useState<MailboxForm>(() => blankForm('gmail'));
  const [errors, setErrors] = React.useState<MailboxErrors>({});
  const [failure, setFailure] = React.useState<string | null>(null);
  const reset = React.useCallback(() => {
    setStep(1);
    setForm(blankForm('gmail'));
    setErrors({});
    setFailure(null);
  }, []);
  React.useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  const patch = (p: Partial<MailboxForm>) => (setForm((f) => ({ ...f, ...p })), setErrors({}), setFailure(null));
  const save = async () => {
    const e = checkMailbox(form);
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      const m = await connect.mutateAsync(toInput(form));
      toast.success(`Connected ${m.address}`);
      onOpenChange?.(false);
      onConnected(m);
      if (shell === 'page') reset();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : 'The mailbox could not be connected.');
    }
  };
  const submit = step === 1 ? () => setStep(2) : save;

  const body = (
    <div className="flex min-w-0 flex-col gap-5">
      <Stepper steps={STEPS} current={step} testId="connect-mailbox-steps" />
      {step === 1 ? (
        <ChoiceCards name="connect-provider" label="Mail provider" choices={PICKABLE} value={form.provider} onChange={(v) => setForm((f) => ({ ...blankForm(v as MailProvider), name: f.name, address: f.address }))} />
      ) : (
        <>
          {failure && (
            <Alert variant="destructive" data-testid="connect-mailbox-error">
              <AlertDescription>{failure}</AlertDescription>
            </Alert>
          )}
          <MailboxFields value={form} onChange={patch} errors={errors} idPrefix={`connect-${shell}`} testTarget={() => (Object.keys(checkMailbox(form)).length ? (setErrors(checkMailbox(form)), null) : { input: toInput(form) })} />
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
      <LoadingButton type="submit" isLoading={connect.isPending} loadingText="Connecting…" data-testid="connect-mailbox-submit">
        {step === 1 ? 'Next' : 'Connect mailbox'}
      </LoadingButton>
    </>
  );

  if (shell === 'dialog')
    return (
      <DialogShell open={open} onOpenChange={(o) => onOpenChange?.(o)} size="lg" title="Connect a mailbox" description="New mail in the folder you pick starts the workflows that watch it." onSubmit={submit} footer={footer} bodyClassName="min-h-96">
        {body}
      </DialogShell>
    );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <Section title="Connect a mailbox" description="New mail in the folder you pick starts the workflows that watch it.">
        {body}
        <div className="mt-6 flex flex-wrap justify-end gap-2 border-t pt-4">{footer}</div>
      </Section>
    </form>
  );
}
