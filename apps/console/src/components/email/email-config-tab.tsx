'use client';

import type { EmailWorkflowConfig, SampleMailInput, SampleMailResult } from '@/lib/types/cases';

import { ApprovalsTab } from './approvals-tab';
import { IntentsTab } from './intents-tab';
import { RoutingTab } from './routing-tab';
import { SampleMailTester } from './sample-mail-tester';
import { useEmailConfig } from '../workflows/email-config-context';

export type EmailTab = 'intents' | 'routing' | 'approvals' | 'sample';

/** Renders one email intake configuration tab against the draft the workflow editor holds. */
export function EmailConfigTab({
  tab,
  queues,
  approverGroups,
  actionOptions,
  moneyTools,
  onTestSample,
  testing,
}: {
  tab: EmailTab;
  queues: string[];
  approverGroups: string[];
  actionOptions: string[];
  moneyTools: string[];
  onTestSample: (config: EmailWorkflowConfig, input: SampleMailInput) => Promise<SampleMailResult>;
  testing: boolean;
}) {
  const { config, setConfig } = useEmailConfig();
  if (!config) return null;
  if (tab === 'intents') return <IntentsTab config={config} onChange={setConfig} actionOptions={actionOptions} />;
  if (tab === 'routing') return <RoutingTab config={config} onChange={setConfig} queues={queues} />;
  if (tab === 'approvals') return <ApprovalsTab config={config} onChange={setConfig} actionOptions={actionOptions} moneyTools={moneyTools} approverGroups={approverGroups} />;
  return <SampleMailTester onRun={(input) => onTestSample(config, input)} isPending={testing} />;
}
