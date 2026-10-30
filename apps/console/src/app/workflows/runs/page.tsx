'use client';

import * as React from 'react';
import { History, Mail } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { RunnerRuns } from '@/components/workflows/runner-runs';

/**
 * Workflows › Runs: every workflow's runs, from agents-service `/v1/runs`. A `?run=` link naming a run opens that run's
 * page; one naming a run of the earlier workflow engine, which the console no longer shows, says so above the list.
 */
export default function RunsPage() {
  const router = useRouter();
  const run = useSearchParams().get('run');
  const current = run?.startsWith('wfrun_');
  React.useEffect(() => {
    if (run && current) router.replace(`/workflows/runs/${encodeURIComponent(run)}`);
  }, [run, current, router]);
  return (
    <PageLayout icon={Mail} title="Runs" switcher description="Runs across every workflow: what is open, what waits on a person, and what the agent did">
      {run && !current && (
        <Alert className="mb-4" data-testid="run-no-longer-available">
          <History />
          <AlertDescription>That run belongs to an earlier kind of workflow and is no longer available here. Every current run is listed below.</AlertDescription>
        </Alert>
      )}
      <RunnerRuns />
    </PageLayout>
  );
}
