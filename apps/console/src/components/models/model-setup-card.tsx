'use client';

import * as React from 'react';
import { KeyRound } from 'lucide-react';

import { ModelSetupDialog } from '@/components/models/model-setup-dialog';
import { StepList } from '@/components/shared/step-list';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useCan } from '@/hooks/me-queries';
import { useProviderKeys } from '@/hooks/provider-key-queries';
import { needsModelSetup } from '@/lib/model-setup';

const STEPS = ['Pick your provider: OpenAI, Azure OpenAI or Anthropic.', 'Paste its key; it is tested with the provider.', 'Pick the model chat and agents answer with.'];

/**
 * First run: a workspace with no model key cannot chat, so its admin sets one up here in three steps (the key goes to
 * the same key store as Model providers). Members and a workspace with a key see nothing.
 */
export function ModelSetupCard() {
  const admin = useCan('settings', 'manage') === true;
  const keys = useProviderKeys(admin);
  const [open, setOpen] = React.useState(false);
  // Saving the key in step two ends the need for this card; it stays until the dialog closes so step three can run.
  if (!open && !needsModelSetup({ admin, keys: keys.data })) return null;
  return (
    <Card data-testid="model-setup">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <KeyRound className="size-4 text-muted-foreground" />
          Set up your AI model
        </CardTitle>
        <CardDescription>This workspace has no model key yet, so chat and agents cannot answer.</CardDescription>
        <CardAction>
          <Button size="sm" onClick={() => setOpen(true)} data-testid="model-setup-start">
            Set up
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <StepList title="Three steps" steps={STEPS.map((title) => ({ title, state: 'pending' }))} />
      </CardContent>
      <ModelSetupDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}
