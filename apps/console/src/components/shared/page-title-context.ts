'use client';

import { createContext } from 'react';

/** True inside a PageLayout, whose title is the page's one h1; a state that replaces the whole page (not found, signed out) then draws its own. */
export const InPageLayout = createContext(false);
