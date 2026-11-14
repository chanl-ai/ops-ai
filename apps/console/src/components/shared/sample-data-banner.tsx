'use client';

import { FlaskConical } from 'lucide-react';

import { Alert, AlertTitle } from '@/components/ui/alert';

const WORDS = {
  page: 'Sample data: this page is not connected to a service yet.',
  section: 'Sample data: no service stores this yet, so it is shown read only.',
} as const;

/**
 * The one way the console says it is showing sample data beside real services: a whole page (PageLayout draws it when
 * the page's area is unserved or the page read the mock) or one section of a live page (SampleDataNote).
 */
export function SampleDataBanner({ scope = 'page' }: { scope?: keyof typeof WORDS }) {
  return (
    <Alert data-testid={scope === 'page' ? 'preview-reason' : 'sample-data-notice'} data-sample-data={scope}>
      <FlaskConical />
      <AlertTitle className="line-clamp-none">{WORDS[scope]}</AlertTitle>
    </Alert>
  );
}
