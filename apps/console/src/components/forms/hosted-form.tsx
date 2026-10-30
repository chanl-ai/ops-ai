'use client';

import * as React from 'react';
import Link from 'next/link';
import { CircleAlert, CircleCheck } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { type FileControl, missingRequired, RunInputFields } from '@/components/workflows/run-input-form';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import type { HostedFormReceived, HostedFormView } from '@/lib/types/forms';

/** Said after a submission when the form's builder wrote no thank-you of their own. */
const THANKS = 'Thank you. Your request has been sent.';

/**
 * A hosted form as the person filling it sees it (c-535): the title, description and fields of the workflow's start
 * form, Send, then the thank-you. Shared by the embed app's link page and the console's members-only page, which pass
 * how to send and how a file field uploads. A refused submission keeps what was typed and says why.
 */
export function HostedForm({
  form,
  onSubmit,
  fileControl,
  showHeading = true,
}: {
  form: HostedFormView;
  /** Sends the values; throws an Error whose message says why it was refused. */
  onSubmit: (values: Record<string, unknown>) => Promise<HostedFormReceived>;
  fileControl?: FileControl;
  /** Off where the page header already shows the title and description. */
  showHeading?: boolean;
}) {
  const schema = form.form.schema;
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [refused, setRefused] = React.useState<string | null>(null);
  const [sending, setSending] = React.useState(false);
  const [done, setDone] = React.useState<HostedFormReceived | null>(null);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const missing = missingRequired(schema, values);
    setErrors(missing);
    if (Object.keys(missing).length) return;
    setSending(true);
    setRefused(null);
    try {
      setDone(await onSubmit(values));
    } catch (err) {
      setRefused(err instanceof Error ? err.message : 'The form could not be sent. Try again in a minute.');
    } finally {
      setSending(false);
    }
  };

  return (
    <Card className="w-full min-w-0" data-testid="hosted-form">
      <CardContent className="flex min-w-0 flex-col gap-5 pt-6">
        {done ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center" data-testid="hosted-form-thanks">
            <CircleCheck className="size-10 text-success" aria-hidden />
            <p className="max-w-prose text-sm break-words whitespace-pre-line">{form.afterText || THANKS}</p>
            {done.runId && (
              <p className="text-sm text-muted-foreground">
                Your run has started.{' '}
                <Link className="font-medium text-foreground underline underline-offset-4" href={`/workflows/runs/${encodeURIComponent(done.runId)}`}>
                  Open the run
                </Link>
              </p>
            )}
          </div>
        ) : (
          <form className="flex min-w-0 flex-col gap-5" onSubmit={send} noValidate>
            {refused && (
              <Alert variant="destructive" data-testid="hosted-form-refused">
                <CircleAlert />
                <AlertTitle>The form was not sent</AlertTitle>
                <AlertDescription>
                  <p>{refused}</p>
                  <p>What you typed is kept.</p>
                </AlertDescription>
              </Alert>
            )}
            {showHeading && (
              <div className="min-w-0">
                <h1 className="text-xl font-semibold break-words">{form.title}</h1>
                {form.description && <p className="mt-1 text-sm break-words whitespace-pre-line text-muted-foreground">{form.description}</p>}
              </div>
            )}
            <div className="flex min-w-0 flex-col gap-4">
              <RunInputFields schema={schema} value={values} onChange={setValues} errors={errors} fileControl={fileControl} idPrefix="form" />
            </div>
            <LoadingButton type="submit" className="w-full" isLoading={sending} loadingText="Sending…" data-testid="hosted-form-send">
              Send
            </LoadingButton>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

/** Why a form could not be opened: an expired or replaced link, another team's form, or a link cut short. */
export function HostedFormRefused({ title, message }: { title: string; message: string }) {
  return (
    <Alert data-testid="hosted-form-refused">
      <CircleAlert />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
      </AlertDescription>
    </Alert>
  );
}
