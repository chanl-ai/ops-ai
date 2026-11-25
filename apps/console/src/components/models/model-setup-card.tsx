'use client';

import { KeyRound } from 'lucide-react';

import { StepList } from '@/components/shared/step-list';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const STEPS = ['Pick your provider from the list, or an OpenAI-compatible URL.', 'Give its key or endpoint; the key is tested with the provider.', 'Make an alias, the name builders pick on an agent.'];

/**
 * First run: a workspace with no model connection cannot chat, so its admin starts here (Connections shows it while the
 * list is empty). The button opens the same connect dialog as Connect a provider.
 */
export function ModelSetupCard({ onSetup }: { onSetup: () => void }) {
  return (
    <Card data-testid="model-setup">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <KeyRound className="size-4 text-muted-foreground" />
          Connect your first AI model
        </CardTitle>
        <CardDescription>This workspace has no model connection yet, so chat and agents cannot answer.</CardDescription>
        <CardAction>
          <Button size="sm" onClick={onSetup} data-testid="model-setup-start">
            Set up
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <StepList title="Three steps" steps={STEPS.map((title) => ({ title, state: 'pending' }))} />
      </CardContent>
    </Card>
  );
}
