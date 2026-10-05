'use client';

import * as React from 'react';

import type { EmailWorkflowConfig } from '@/lib/types/cases';

/**
 * The email intake configuration being edited. The workflow editor owns it alongside the canvas so a config
 * change is part of the same autosaved draft, validated and published with the graph.
 */
export const EmailConfigContext = React.createContext<{ config: EmailWorkflowConfig | undefined; setConfig: (c: EmailWorkflowConfig) => void } | null>(null);

export function useEmailConfig() {
  const ctx = React.useContext(EmailConfigContext);
  if (!ctx) throw new Error('useEmailConfig must be used inside the workflow editor');
  return ctx;
}
