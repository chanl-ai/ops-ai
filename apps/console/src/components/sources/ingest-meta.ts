import type { IngestPresetId, IngestStrategy } from '@/lib/types/knowledge-ingest';

/** Words for each split step and preset id; the steps and defaults themselves come from kb-service. */
export const STRATEGY_LABEL: Record<IngestStrategy, string> = {
  structure: 'Split at headings',
  fixed: 'Fixed-size splitting',
  topic: 'Topic grouping',
  faq: 'Likely questions',
  faq_pairs: 'FAQ drafts',
  context_headers: 'Context headers',
  parent_child: 'Parent and child',
  table_rows: 'Table rows',
  clean: 'Cleaning',
};

export const PRESET_LABEL: Record<IngestPresetId, string> = { policy_manual: 'Policy manual', help_centre: 'Help centre', rate_table: 'Rate table', email_templates: 'Email templates', custom: 'Custom' };
