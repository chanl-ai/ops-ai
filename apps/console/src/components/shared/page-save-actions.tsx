'use client';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { RotateCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { LoadingButton } from '@/components/shared/loading-button';

/** The page header's place for Save and Discard, set by `PageLayout`; null outside one. */
export const PageSaveSlot = React.createContext<HTMLElement | null>(null);

/**
 * Save and Discard for a form on the page, drawn in the page header so they are found in one place on every page,
 * however long the form. Save stays disabled until something changed. A form deep in a tab renders this where its
 * state lives; it moves itself into the header. `save` replaces the Save button when saving asks for more first.
 */
export function PageSaveActions({
  dirty,
  saving,
  invalid,
  onSave,
  onDiscard,
  label = 'Save',
  form,
  save,
  testId,
}: {
  dirty: boolean;
  saving: boolean;
  invalid?: boolean;
  onSave?: () => void;
  onDiscard: () => void;
  label?: string;
  /** The id of the form whose submit this is, for a form that saves on submit. */
  form?: string;
  save?: React.ReactNode;
  testId?: string;
}) {
  const slot = React.useContext(PageSaveSlot);
  const actions = (
    <>
      {dirty && (
        <Button type="button" variant="ghost" size="sm" onClick={onDiscard} disabled={saving}>
          <RotateCcw className="size-3.5" /> Discard
        </Button>
      )}
      {save ?? (
        <LoadingButton type={form ? 'submit' : 'button'} form={form} size="sm" isLoading={saving} disabled={!dirty || invalid} onClick={form ? undefined : onSave} data-testid={testId}>
          {label}
        </LoadingButton>
      )}
    </>
  );
  return slot ? createPortal(actions, slot) : <div className="flex items-center justify-end gap-2">{actions}</div>;
}
