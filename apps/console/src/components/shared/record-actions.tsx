'use client';

import type { ReactNode } from 'react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { comboLabel, useShortcut } from '@/hooks/use-shortcut';

export const SAVE_COMBO = 'mod+s';

/**
 * The header actions of a record's edit page, in the one order every such page uses: save state, Save, Test, the
 * primary action, the overflow menu. Pass them to `PageLayout`'s `actions`; a page cannot reorder them. Save also
 * answers Cmd/Ctrl+S, listed in the command menu. `primary` is the only filled button; the others are outlines.
 */
export function RecordActions({
  status,
  save,
  test,
  primary,
  menu,
}: {
  /** The page's SaveState (or null when the person cannot edit). */
  status?: ReactNode;
  save?: { onSave: () => void; disabled?: boolean; saving?: boolean; testId?: string };
  test?: ReactNode;
  primary?: ReactNode;
  menu?: ReactNode;
}) {
  useShortcut({ id: 'save', label: 'Save', combo: SAVE_COMBO, run: () => save && !save.disabled && !save.saving && save.onSave() }, !!save);
  return (
    <>
      {status}
      {save && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <LoadingButton type="button" variant="outline" isLoading={!!save.saving} disabled={save.disabled} onClick={save.onSave} data-testid={save.testId ?? 'record-save'}>
                Save
              </LoadingButton>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            Save <kbd className="ml-1 font-mono text-xs">{comboLabel(SAVE_COMBO)}</kbd>
          </TooltipContent>
        </Tooltip>
      )}
      {test}
      {primary}
      {menu}
    </>
  );
}

