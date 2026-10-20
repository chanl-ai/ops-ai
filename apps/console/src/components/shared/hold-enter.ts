import type { KeyboardEvent } from 'react';

/**
 * For a settings form that saves a new version: Enter in a field does nothing, so the Save button is the only way to
 * create one. Each save is a version people can be asked to explain or roll back, and a stray Enter in a
 * text field must not make one. Buttons, links and textareas keep their own Enter. Plain create and edit dialogs do
 * not use this; they save on Enter.
 */
export function holdEnter(e: KeyboardEvent<HTMLElement>) {
  if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault();
}
