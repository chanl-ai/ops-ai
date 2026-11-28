'use client';

import * as React from 'react';

/**
 * The task's pinned bar, as the decision form sees it: `slot` is where the form draws its Reject and Approve, so the
 * buttons and the reason they check stay one form (ReviewDecisionForm); `setReturn` hands the bar's More menu the
 * form's own Return, offered only where the server says the person may return the task (`canReturn`).
 */
export interface DecisionBar {
  slot: HTMLElement | null;
  setReturn: (submit: (() => void) | null) => void;
}

export const DecisionBarContext = React.createContext<DecisionBar | null>(null);
