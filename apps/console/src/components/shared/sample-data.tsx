'use client';

import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { FlaskConical } from 'lucide-react';

import { Alert, AlertTitle } from '@/components/ui/alert';

const InSample = createContext(false);

/** True inside a sample section: its cards show their values read only, with no Save or other action. */
export const useIsSample = () => useContext(InSample);

/**
 * Lets the page around a sample section know one is on screen, so the page header says in words that parts of it are
 * sample data, whatever its area's own state (PageLayout provides it).
 */
export const SampleOnPage = createContext<((change: 1 | -1) => void) | null>(null);

/** The one line a page or section shows while no service stores what it edits. */
export function SampleDataNote() {
  return (
    <Alert data-testid="sample-data-notice">
      <FlaskConical />
      <AlertTitle>Sample data: no service stores this yet, so it is shown read only.</AlertTitle>
    </Alert>
  );
}

/**
 * Wraps the controls of a page or section that is backed by the mock API. A disabled fieldset switches off every
 * button, field and switch inside it in one place (portalled dialogs cannot open, because their triggers are off), so
 * a page cannot offer a Save that reverts on reload. `contents` keeps the fieldset out of the layout.
 */
export function SampleDataGate({ children }: { children: ReactNode }) {
  const report = useContext(SampleOnPage);
  useEffect(() => {
    report?.(1);
    return () => report?.(-1);
  }, [report]);
  return (
    <InSample.Provider value>
      <fieldset disabled className="contents" data-testid="sample-data-gate">
        {children}
      </fieldset>
    </InSample.Provider>
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
