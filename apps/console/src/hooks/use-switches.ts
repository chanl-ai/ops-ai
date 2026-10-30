import { documentReads, hostedForms, workflowBuilder } from '@/lib/api';

/** Console switches read once at build time (lib/api/index.ts); components ask through these, never the client. */
export const useDocumentReads = (): boolean => documentReads;
export const useHostedForms = (): boolean => hostedForms;
export const useWorkflowBuilder = (): boolean => workflowBuilder;
