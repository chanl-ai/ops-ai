'use client';

import Link from 'next/link';
import { KeyRound } from 'lucide-react';

import { StepList } from '@/components/shared/step-list';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useCan } from '@/hooks/me-queries';
import { useProviderKeys } from '@/hooks/provider-key-queries';
import { needsModelSetup } from '@/lib/model-setup';

const STEPS = [
  'Add your provider key: OpenAI, Azure OpenAI or Anthropic.',
  'For Azure OpenAI, connect the endpoint so its deployments can be called.',
  'Chat and agents then answer with your models.',
];

/**
 * First run: a workspace with no model key cannot chat, so its admin sees where to add one, on the Model providers
 * page that already holds keys and connections. Members and a workspace with a key see nothing.
 */
export function ModelSetupCard() {
  const admin = useCan('settings', 'manage') === true;
  const keys = useProviderKeys(admin);
  if (!needsModelSetup({ admin, keys: keys.data })) return null;
  return (
    <Card data-testid="model-setup">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <KeyRound className="size-4 text-muted-foreground" />
          Set up your AI model
        </CardTitle>
        <CardDescription>This workspace has no model key yet, so chat and agents cannot answer.</CardDescription>
        <CardAction>
          <Button asChild size="sm" data-testid="model-setup-start">
            <Link href="/settings/workspace/model-providers">Add a model key</Link>
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <StepList title="Three steps" steps={STEPS.map((title) => ({ title, state: 'pending' }))} />
      </CardContent>
    </Card>
  );
}
