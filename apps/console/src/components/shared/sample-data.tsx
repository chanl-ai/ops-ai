'use client';

import type { ReactNode } from 'react';
import { FlaskConical } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

/** The banner a page shows while no service stores what it edits. */
export function SampleDataNote() {
  return (
    <Alert data-testid="sample-data-notice">
      <FlaskConical />
      <AlertTitle>Sample data, changes aren’t saved</AlertTitle>
      <AlertDescription>No service stores this page yet. What you see is an example, and its controls stay off until one does.</AlertDescription>
    </Alert>
  );
}

/**
 * Wraps the controls of a page or section that is backed by the mock API. A disabled fieldset switches off every
 * button, field and switch inside it in one place (portalled dialogs cannot open, because their triggers are off), so
 * a page cannot offer a Save that reverts on reload. `contents` keeps the fieldset out of the layout.
 */
export function SampleDataGate({ children }: { children: ReactNode }) {
  return (
    <fieldset disabled className="contents" data-testid="sample-data-gate">
      {children}
    </fieldset>
  );
}

/** Banner plus gate, for a section inside a page that is otherwise live. */
export function SampleData({ children }: { children: ReactNode }) {
  return (
    <>
      <SampleDataNote />
      <SampleDataGate>{children}</SampleDataGate>
    </>
  );
}
