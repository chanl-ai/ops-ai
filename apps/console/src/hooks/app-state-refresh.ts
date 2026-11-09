'use client';

import type { QueryClient } from '@tanstack/react-query';

/**
 * Every read that shows an app's state: the catalog, the app's page and its accounts, Mine and the chat picker. A
 * change to an app, an account, an auth config or a sign-in reads all of them again, so no surface keeps an old state
 * until it remounts.
 */
const APP_STATE_READS = [['systems'], ['accounts'], ['apps'], ['connections', 'mine'], ['chat', 'connectors']] as const;

export const refreshAppState = (qc: QueryClient) => Promise.all(APP_STATE_READS.map((queryKey) => qc.invalidateQueries({ queryKey })));
