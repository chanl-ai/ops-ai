'use client';

import { CopyButton } from '@/components/shared/copy-button';
import { FormField } from '@/components/shared/form-field';
import { Input } from '@/components/ui/input';
import { useConnectionKinds } from '@/hooks/systems-queries';

/**
 * The callback URL a team registers in its own app at the system (a Salesforce connected app, a GitHub OAuth app),
 * with a copy button. tools-service builds it from its console URL setting, so it is the address the system returns
 * people to; nothing is shown while that answer is loading.
 */
export function CallbackUrl({ app, id, testId }: { app: string; id: string; testId: string }) {
  const url = useConnectionKinds().data?.redirectUri;
  if (!url) return null;
  return (
    <FormField id={id} label="Callback URL" hint={`Register this callback URL in your ${app} app.`}>
      <div className="flex min-w-0 items-center gap-1" data-testid={testId}>
        <Input id={id} readOnly value={url} className="font-mono text-xs" />
        <CopyButton text={url} />
      </div>
    </FormField>
  );
}
